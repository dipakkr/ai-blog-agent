"""
Node: outline_generator

Generates a structured article outline from SERP analysis and content gaps.
Updates job status to OUTLINING.
"""

import logging
import re

from app.models.article import Outline, OutlineSection
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an expert SEO content strategist. "
    "Create detailed, well-structured article outlines optimised for both "
    "search engines and human readers. Every outline must include a compelling "
    "title, an SEO meta description (150–160 characters), and a hierarchy of "
    "H2 and H3 sections with clear key points."
)

# Headings that are clearly site navigation, sidebar, or footer — never article sections
_NAV_SECTION_RE = re.compile(
    r"^("
    r"get in touch|contact us?|follow us?|subscribe|sign up|newsletter|"
    r"top posts?|popular posts?|recent posts?|related posts?|you (may|might) also|"
    r"never miss|about us?|our services?|meet the team|leave a (comment|reply)|"
    r"share this|tags?|categories|archives?|search|menu|navigation|"
    r"comments?|pingback|trackback|\d+\s*(comments?|replies|responses)|"
    r"written by|author bio|the final|keep reading|read more|see also|"
    r"sponsored|advertisement|disclosure|affiliate|"
    r"from the (blog|podcast)|listen to|watch (the|our)|"
    r"what (our|customers) (say|think)|testimonials?"
    r")",
    re.IGNORECASE,
)

# Topic-level signals for deterministic format detection
_LISTICLE_SIGNALS = re.compile(
    r"\b(best|top\s+\d+|top\s+\w+|tools?|apps?|generators?|platforms?|"
    r"software|alternatives?|plugins?|extensions?|resources?|examples?)\b",
    re.IGNORECASE,
)
_TUTORIAL_SIGNALS = re.compile(
    r"\b(how\s+to|step.by.step|tutorial|guide|walkthrough|build|create|setup|configure)\b",
    re.IGNORECASE,
)
_COMPARISON_SIGNALS = re.compile(
    r"\b(vs\.?|versus|compared?|comparison|difference|which\s+is\s+better)\b",
    re.IGNORECASE,
)


def _detect_format(topic: str, brief_format: "str | None") -> str:
    """Deterministically override the classifier when topic clearly signals a format.

    The LLM classifier can misread format (e.g. calling a 'best tools' listicle
    an 'explainer'). Topic keywords are a reliable signal and take priority.
    """
    if _COMPARISON_SIGNALS.search(topic):
        return "comparison"
    if _TUTORIAL_SIGNALS.search(topic):
        return "tutorial"
    if _LISTICLE_SIGNALS.search(topic):
        return "listicle"
    return brief_format or "explainer"


def _format_instructions(state: SEOPipelineState, effective_format: str) -> str:
    brief = state.get("content_brief")

    elements = ", ".join(brief.required_elements) if brief else ""
    patterns_block = "\n".join(f"  - {p}" for p in brief.structural_patterns) if brief else ""

    format_section = f"CONTENT FORMAT: {effective_format}\n"
    if brief:
        format_section += (
            f"TARGET AUDIENCE: {brief.audience} — {brief.writing_style_notes}\n"
            f"TONE: {brief.tone.replace('_', ' ')}\n"
        )

    patterns_section = ""
    if patterns_block:
        patterns_section = (
            f"\nSTRUCTURAL PATTERNS FROM TOP-RANKING COMPETITORS:\n{patterns_block}\n"
            f"\nCOMPETITIVE ANGLE (what none of the top results cover well):\n"
            f"  {brief.competitive_angle}\n"
        )

    elements_section = ""
    if elements:
        elements_section = f"\nREQUIRED CONTENT ELEMENTS:\n  {elements}\n"

    return format_section + patterns_section + elements_section


def _build_competitor_block(state: SEOPipelineState, effective_format: str) -> str:
    """Build the competitor heading context block for the outline prompt.

    ONLY uses headings that appear in 2+ competitor pages (common_headings) —
    never raw per-page H2 dumps which contain sidebar/nav/footer noise.
    For listicles, also extracts product/tool names from filtered H2s.
    """
    insights = state.get("competitor_insights")
    if not insights or insights.pages_scraped == 0:
        return ""

    is_listicle = effective_format == "listicle" or _LISTICLE_SIGNALS.search(state["topic"])

    # --- Listicle: collect tool/product names from H2s across all scraped pages ---
    if is_listicle:
        seen: set[str] = set()
        tool_names: list[str] = []
        skip_generic = {
            "introduction", "conclusion", "overview", "summary", "faq",
            "what is", "how to", "pricing", "comparison", "benefits",
            "features", "pros", "cons", "review",
        }
        for p in insights.pages:
            if not p.scraped:
                continue
            for h in p.h2_headings:
                if (
                    not _NAV_SECTION_RE.match(h)
                    and not any(s in h.lower() for s in skip_generic)
                    and len(h) <= 80
                ):
                    key = h.lower().strip()
                    if key not in seen:
                        seen.add(key)
                        tool_names.append(h)

        if tool_names:
            structural_lines = "\n".join(f"  - {insights.structural_signals[i]}"
                                         for i in range(min(3, len(insights.structural_signals))))
            return (
                f"\nCOMPETITOR ANALYSIS ({insights.pages_scraped}/{insights.pages_attempted} pages scraped):\n"
                f"{structural_lines}\n"
                f"\nTOOL/PRODUCT NAMES FOUND IN COMPETITOR H2s "
                f"(use these as your listicle items — pick the most relevant):\n"
                + "\n".join(f"  - {name}" for name in tool_names[:12])
            )

    # --- Non-listicle: only show COMMON headings (2+ pages) — no per-page dumps ---
    clean_common = [h for h in insights.common_headings if not _NAV_SECTION_RE.match(h)]
    structural_summary = "\n".join(f"  - {s}" for s in insights.structural_signals[:5])

    block = (
        f"\nCOMPETITOR ANALYSIS ({insights.pages_scraped}/{insights.pages_attempted} pages scraped):\n"
        f"{structural_summary}\n"
    )
    if clean_common:
        block += (
            "\nHEADINGS THAT APPEAR IN 2+ TOP-RANKING PAGES "
            "(use as structural signal, not copy):\n"
            + "\n".join(f"  - {h}" for h in clean_common[:8])
        )
    return block


def _build_prompt(state: SEOPipelineState, effective_format: str) -> str:
    gaps_text = "\n".join(
        f"- [{g.priority.upper()}] {g.topic}: {g.reason}"
        for g in (state["content_gaps"] or [])
    )
    format_block = _format_instructions(state, effective_format)
    competitor_block = _build_competitor_block(state, effective_format)

    insights = state.get("competitor_insights")
    secondary_kw_block = ""
    if insights and insights.common_secondary_keywords:
        secondary_kw_block = (
            "\nSECONDARY KEYWORDS (from competitor pages — include naturally):\n"
            + ", ".join(insights.common_secondary_keywords)
        )

    # Hard cap: ~150 words minimum per H2 keeps sections substantive
    max_h2_sections = min(15, max(4, state["target_word_count"] // 150))
    # For listicles, each tool gets its own H2 — cap at a number that fits the word count
    if effective_format == "listicle":
        max_h2_sections = min(12, max(4, state["target_word_count"] // 200))

    return f"""Create a comprehensive SEO article outline for:

Topic: "{state['topic']}"
Primary keyword: "{state['primary_keyword']}"
Target word count: {state['target_word_count']} words
Language: {state['language']}

{format_block}
Content gaps to address (prioritised):
{gaps_text}
{competitor_block}
{secondary_kw_block}

Requirements:
- Title must include the primary keyword naturally
- Meta description must be exactly 150–160 characters and include the primary keyword
- SECTION COUNT: Generate AT MOST {max_h2_sections} H2 sections.
  This article is {state['target_word_count']} words — too many sections = too shallow.
- Each section must list 2–4 specific key points to cover
- Sections must be genuine article content — NO navigation, contact, subscription, sidebar, or podcast sections
- Do NOT copy competitor page navigation elements as sections (e.g. "Get in Touch", "Top Posts", "Subscribe")"""


def _filter_nav_sections(sections: list[OutlineSection]) -> list[OutlineSection]:
    """Remove any outline section whose heading matches a known nav/sidebar pattern."""
    cleaned = []
    for s in sections:
        if _NAV_SECTION_RE.match(s.heading):
            logger.warning("outline_generator: dropping nav section '%s'", s.heading)
            continue
        # Recursively clean subsections
        clean_subs = [sub for sub in s.subsections if not _NAV_SECTION_RE.match(sub.heading)]
        cleaned.append(s.model_copy(update={"subsections": clean_subs}))
    return cleaned


async def outline_generator(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    job_manager.update_status(job_id, JobStatus.OUTLINING)

    brief = state.get("content_brief")
    # Deterministic override: topic keywords beat LLM classifier for clear signals
    effective_format = _detect_format(state["topic"], brief.format if brief else None)
    if brief and brief.format != effective_format:
        logger.info(
            "[%s] outline_generator: overriding classifier format '%s' → '%s' (topic signal)",
            job_id, brief.format, effective_format,
        )

    logger.info(
        "[%s] outline_generator: format=%s, generating outline for '%s'",
        job_id, effective_format, state["topic"],
    )

    try:
        prompt = _build_prompt(state, effective_format)
        outline: Outline = await llm_service.call_llm(
            prompt=prompt,
            system=SYSTEM,
            response_model=Outline,
            temperature=0.6,
            max_tokens=4096,
        )

        # --- Post-process: strip nav/sidebar sections the LLM may have hallucinated ---
        before = len(outline.sections)
        clean_sections = _filter_nav_sections(list(outline.sections))
        if len(clean_sections) < before:
            logger.warning(
                "[%s] outline_generator: removed %d nav/sidebar sections from outline",
                job_id, before - len(clean_sections),
            )
            outline = outline.model_copy(update={"sections": clean_sections})

        # --- Enforce keyword in title ---
        kw = state["primary_keyword"].lower()
        if kw not in outline.title.lower():
            outline = outline.model_copy(update={"title": f"{state['primary_keyword']}: {outline.title}"})
            logger.info("[%s] outline_generator: keyword prepended to title", job_id)

        # --- Enforce meta description length (150–160 chars) ---
        meta = outline.meta_description.strip()
        if not (150 <= len(meta) <= 160):
            if len(meta) > 160:
                truncated = meta[:157]
                last_space = truncated.rfind(" ")
                meta = (truncated[:last_space] if last_space > 140 else truncated) + "..."
            else:
                suffix = f" A complete guide to {state['primary_keyword']}."
                meta = (meta + suffix)[:160].rsplit(" ", 1)[0]
            outline = outline.model_copy(update={"meta_description": meta})

        # --- Enforce keyword in at least one H2 heading ---
        h2_headings = [s.heading for s in outline.sections if s.level.value == "h2"]
        if h2_headings and not any(kw in h.lower() for h in h2_headings):
            first = outline.sections[0]
            patched = first.model_copy(update={"heading": f"{state['primary_keyword']}: {first.heading}"})
            outline = outline.model_copy(update={"sections": [patched] + list(outline.sections[1:])})

        logger.info(
            "[%s] outline_generator: '%s' | format=%s | %d sections",
            job_id, outline.title, effective_format, len(outline.sections),
        )

        def _section_to_dict(s) -> dict:
            return {
                "heading": s.heading,
                "level": s.level.value,
                "key_points": s.key_points,
                "subsections": [_section_to_dict(sub) for sub in s.subsections],
            }

        job_manager.save_pipeline_artifact(job_id, "outline", {
            "title": outline.title,
            "meta_description": outline.meta_description,
            "secondary_keywords": outline.secondary_keywords,
            "format": effective_format,
            "sections": [_section_to_dict(s) for s in outline.sections],
        })
        return {"outline": outline, "status": JobStatus.OUTLINING}

    except Exception as e:
        logger.exception("[%s] outline_generator failed", job_id)
        return {"status": "outlining_failed", "error": str(e)}
