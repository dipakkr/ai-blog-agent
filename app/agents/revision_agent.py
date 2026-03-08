"""
Node: revision_agent

Rewrites sections that caused SEO check failures. Targets only the failing
checks so the rewrite is surgical rather than regenerating the full article.
Updates job status to REVISING and increments revision_count.
"""

import logging

from pydantic import BaseModel

from app.config import settings
from app.models.article import ArticleSection
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service
from app.utils.text_utils import count_words, section_max_tokens

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an expert SEO content editor. "
    "You receive article sections that failed specific SEO checks. "
    "Rewrite them to fix the identified issues while preserving quality, "
    "tone, and factual accuracy. Do not add keyword stuffing."
)


class _RevisedContent(BaseModel):
    content: str


def _describe_failures(state: SEOPipelineState) -> str:
    if not state.get("seo_score"):
        return "General quality improvement needed."
    failed = [c for c in state["seo_score"].checks if not c.passed]
    return "\n".join(f"- {c.check}: {c.detail}" for c in failed)


def _build_prompt(
    section: ArticleSection,
    topic: str,
    primary_keyword: str,
    failures: str,
    is_first: bool,
) -> str:
    intro_note = (
        f'This is the opening section. Ensure the keyword "{primary_keyword}" '
        "appears naturally in the first paragraph.\n"
        if is_first else ""
    )
    return f"""Revise the following article section to fix these SEO issues:

FAILED CHECKS:
{failures}

TOPIC: "{topic}"
PRIMARY KEYWORD: "{primary_keyword}"
{intro_note}
CURRENT SECTION ({section.heading} — {section.level.value.upper()}):
{section.content}

Rewrite instructions:
- Fix the failing checks listed above
- Maintain approximately the same length ({section.word_count} words)
- Keep the same heading and section purpose
- Write flowing prose only — no markdown, no bullet points unless already present
- Do not introduce new factual claims not implied by the original"""


async def revision_agent(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    revision_count = state["revision_count"] + 1
    job_manager.update_status(job_id, JobStatus.REVISING)
    logger.info(
        "[%s] revision_agent: revision %d/%d",
        job_id, revision_count, settings.max_revision_count,
    )

    failures = _describe_failures(state)
    sections = state["draft_sections"] or []

    try:
        # Only sections that are likely to fix failing checks need rewriting.
        # Strategy: always revise the first section (intro keyword issues) and
        # any section whose heading was flagged in keyword/heading checks.
        revised: list[ArticleSection] = []
        for i, section in enumerate(sections):
            should_revise = (
                i == 0  # always revise intro for keyword-in-first-100 issues
                or "keyword_in_h2" in failures  # H2 keyword issue
                or "keyword_density" in failures  # density — rewrite all
                or "readability" in failures  # readability — rewrite all
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
            )
            result: _RevisedContent = await llm_service.call_llm(
                prompt=prompt,
                system=SYSTEM,
                response_model=_RevisedContent,
                temperature=0.6,
                max_tokens=section_max_tokens(section.word_count),
            )
            revised.append(
                ArticleSection(
                    heading=section.heading,
                    level=section.level,
                    content=result.content,
                    word_count=count_words(result.content),
                )
            )

        logger.info("[%s] revision_agent: revision %d complete", job_id, revision_count)
        return {
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
        return {"status": "revising_failed", "error": str(e)}
