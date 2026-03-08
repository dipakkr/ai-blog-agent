"""
Node: revision_agent

Rewrites sections that caused SEO check failures. Targets only the failing
checks so the rewrite is surgical rather than regenerating the full article.
Updates job status to REVISING and increments revision_count.
"""

import logging
import re

from app.config import settings
from app.models.article import ArticleSection, Outline
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service
from app.utils.text_utils import count_words, section_max_tokens

logger = logging.getLogger(__name__)

_SYSTEM_BASE = (
    "You are an expert SEO content editor. "
    "You receive article sections that failed specific SEO checks. "
    "Rewrite them to fix the identified issues while preserving quality, "
    "tone, and factual accuracy. Do not add keyword stuffing."
)

_FORMAT_REVISION_SUFFIX = {
    "tutorial": (
        " Preserve numbered steps, code snippets, and technical specificity. "
        "Use markdown formatting (fenced code blocks, numbered lists) as appropriate."
    ),
    "comparison": (
        " Preserve markdown tables, pros/cons lists, and objective tone. "
        "Keep side-by-side comparisons and specific product names intact."
    ),
    "listicle": (
        " Preserve item structure and specific tool/product names. "
        "Keep punchy openings and concrete details for each item."
    ),
    "explainer": (
        " Preserve analogies, ASCII diagrams, and progressive concept building. "
        "Keep technical term definitions and markdown formatting."
    ),
    "case_study": (
        " Preserve the narrative arc (problem → approach → result → lesson). "
        "Keep named entities, metrics, and measurable outcomes."
    ),
}


def _failed_checks(state: SEOPipelineState) -> set[str]:
    if not state.get("seo_score"):
        return set()
    return {c.check for c in state["seo_score"].checks if not c.passed}


def _fix_meta_description(meta: str, primary_keyword: str) -> str:
    """Programmatically trim/pad meta description to hit 150-160 chars."""
    meta = meta.strip()
    if 150 <= len(meta) <= 160:
        return meta
    if len(meta) > 160:
        # Trim at last word boundary before 157 chars, append ellipsis
        truncated = meta[:157]
        last_space = truncated.rfind(" ")
        return (truncated[:last_space] if last_space > 140 else truncated) + "..."
    # Too short — pad by appending keyword-rich context
    suffix = f" Learn everything about {primary_keyword}."
    combined = meta + suffix
    return combined[:160].rsplit(" ", 1)[0] if len(combined) > 160 else combined


async def _fix_title(topic: str, primary_keyword: str, current_title: str) -> str:
    """Ask LLM to rewrite the title so it naturally includes the primary keyword."""
    prompt = (
        f'Rewrite this article title so it naturally includes the exact phrase "{primary_keyword}".\n'
        f"Current title: {current_title}\n"
        f"Topic: {topic}\n"
        "Return only the new title — no quotes, no explanation."
    )
    title: str = await llm_service.call_llm(
        prompt=prompt,
        system="You are an expert SEO copywriter. Titles must be compelling and include the target keyword naturally.",
        response_model=None,
        temperature=0.4,
        max_tokens=100,
    )
    return title.strip().strip('"').strip("'")


def _describe_failures(state: SEOPipelineState) -> str:
    if not state.get("seo_score"):
        return "General quality improvement needed."
    failed = [c for c in state["seo_score"].checks if not c.passed]
    lines = []
    for c in failed:
        lines.append(f"- {c.check}: {c.detail}")
        # Add explicit actionable instruction per check type
        if "keyword_density" in c.check:
            lines.append(
                f"  → ACTION: Naturally work the phrase \"{state['primary_keyword']}\" "
                f"into the text more often. Target 1–3% density across the full article."
            )
        elif "word_count_target" in c.check:
            target = state.get("target_word_count", 0)
            sections = state.get("draft_sections") or []
            current = sum(s.word_count for s in sections)
            lines.append(
                f"  → ACTION: Current total is ~{current} words, target is {target}. "
                f"EXPAND this section with more detail, examples, and explanation. Do not shorten."
            )
        elif "readability" in c.check:
            lines.append(
                "  → ACTION: Use shorter sentences (under 20 words). "
                "Replace complex words with simpler ones. Add bullet points to break up dense paragraphs."
            )
    return "\n".join(lines)


def _build_prompt(
    section: ArticleSection,
    topic: str,
    primary_keyword: str,
    failures: str,
    is_first: bool,
    content_format: str = "explainer",
    required_elements: "list[str] | None" = None,
) -> str:
    intro_note = (
        f'This is the opening section. Ensure the keyword "{primary_keyword}" '
        "appears naturally in the first paragraph.\n"
        if is_first else ""
    )
    elements_note = ""
    if required_elements:
        elements_note = (
            "\nRequired elements to preserve: "
            + ", ".join(required_elements)
            + "\n"
        )
    return f"""Revise the following article section to fix these SEO issues:

FAILED CHECKS:
{failures}

TOPIC: "{topic}"
PRIMARY KEYWORD: "{primary_keyword}"
{intro_note}{elements_note}
CURRENT SECTION ({section.heading} — {section.level.value.upper()}):
{section.content}

Rewrite instructions:
- Fix the failing checks listed above — follow the ACTION items exactly
- {"EXPAND this section — write MORE content, aim for at least " + str(int(section.word_count * 1.3)) + " words" if "word_count_target" in failures else "Maintain approximately the same length (" + str(section.word_count) + " words)"}
- Keep the same heading and section purpose
- Preserve existing markdown formatting (tables, code blocks, lists) — use markdown where appropriate for a {content_format} article
- Do not introduce new factual claims not implied by the original"""


async def revision_agent(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    revision_count = state["revision_count"] + 1
    job_manager.update_status(job_id, JobStatus.REVISING)
    logger.info(
        "[%s] revision_agent: revision %d/%d",
        job_id, revision_count, settings.max_revision_count,
    )

    brief = state.get("content_brief")
    content_format = brief.format if brief else "explainer"
    required_elements = brief.required_elements if brief else []

    if brief and brief.writing_style_notes:
        system = (
            _SYSTEM_BASE
            + f" Writing style (from SERP analysis): {brief.writing_style_notes}"
        )
    else:
        system = _SYSTEM_BASE + _FORMAT_REVISION_SUFFIX.get(content_format, "")

    failed = _failed_checks(state)
    failures = _describe_failures(state)
    sections = state["draft_sections"] or []
    outline: Outline = state["outline"]

    try:
        # --- Fix title if keyword is missing from it ---
        updated_outline = outline
        if "keyword_in_title" in failed:
            kw = state["primary_keyword"]
            if kw.lower() not in outline.title.lower():
                logger.info("[%s] revision_agent: fixing title (missing keyword)", job_id)
                new_title = await _fix_title(state["topic"], kw, outline.title)
                updated_outline = outline.model_copy(update={"title": new_title})
                logger.info("[%s] revision_agent: new title: %s", job_id, new_title)

        # --- Fix meta description length programmatically ---
        if "meta_description_length" in failed:
            fixed_meta = _fix_meta_description(
                updated_outline.meta_description, state["primary_keyword"]
            )
            updated_outline = updated_outline.model_copy(update={"meta_description": fixed_meta})
            logger.info(
                "[%s] revision_agent: meta fixed to %d chars", job_id, len(fixed_meta)
            )

        # --- Rewrite sections that can fix the remaining checks ---
        revised: list[ArticleSection] = []
        for i, section in enumerate(sections):
            should_revise = (
                i == 0  # always revise intro for keyword-in-first-100 issues
                or "keyword_in_h2" in failed
                or "keyword_density" in failed
                or "readability" in failed
                or "word_count_target" in failed
                or "secondary_keywords" in failed
            )
            if not should_revise:
                revised.append(section)
                continue

            logger.info(
                "[%s] revision_agent: revising section '%s'", job_id, section.heading
            )
            prompt = _build_prompt(
                section=section,
                topic=state["topic"],
                primary_keyword=state["primary_keyword"],
                failures=failures,
                is_first=(i == 0),
                content_format=content_format,
                required_elements=required_elements,
            )
            revised_text: str = await llm_service.call_llm(
                prompt=prompt,
                system=system,
                response_model=None,
                temperature=0.6,
                max_tokens=section_max_tokens(section.word_count),
            )
            revised.append(
                ArticleSection(
                    heading=section.heading,
                    level=section.level,
                    content=revised_text,
                    word_count=count_words(revised_text),
                )
            )

        logger.info("[%s] revision_agent: revision %d complete", job_id, revision_count)
        return {
            "outline": updated_outline,
            "draft_sections": revised,
            "revision_count": revision_count,
            "status": JobStatus.REVISING,
            # Invalidate stale assembled article and score from previous round.
            # seo_scorer will rebuild both after re-scoring the revised draft.
            "seo_score": None,
            "article": None,
        }

    except Exception as e:
        logger.exception("[%s] revision_agent failed", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        # Must return revision_count so the routing edge sees it incremented
        # and eventually hits max_revision_count, breaking the loop.
        return {"status": "revising_failed", "error": str(e), "revision_count": revision_count}
