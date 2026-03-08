"""
Node: outline_generator

Generates a structured article outline from the content_brief strategy contract
and content gaps. Consumes pre-computed fields (search_intent, has_subcategories,
recommended_tools, suggested_section_count) instead of re-deriving them.
Updates job status to OUTLINING.
"""

import logging
import re

from app.models.article import Outline, OutlineSection
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service
from app.utils.seo_utils import keyword_fuzzy_match
from app.utils.serp_utils import (
    clean_competitor_headings,
    extract_tool_names,
    recommend_section_count,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — restructured per feedback
# ---------------------------------------------------------------------------

SYSTEM = (
    "You are an expert SEO content strategist. Create detailed, "
    "well-structured article outlines optimised for both search engines "
    "and human readers.\n\n"
    "Output format:\n"
    "- Title (include primary keyword naturally — variations and plurals are fine)\n"
    "- Meta description (~155 characters, include primary keyword)\n"
    "- Introduction key points (2–3 bullets; keyword must appear in first 100 words)\n"
    "- H2/H3 hierarchy with 2–4 key points per section\n"
    "- Conclusion with a CTA or recommendation\n\n"
    "Rules:\n"
    "- Only genuine article sections — NO navigation, sidebar, subscribe, "
    "FAQ, editorial standards, or boilerplate sections\n"
    "- Match section count to word count (~200–250 words per H2)\n"
    "- For listicles: use H2 per item if the list is flat (e.g. 'n8n alternatives'). "
    "Use H2 as category with H3 per item ONLY if natural categories exist "
    "(e.g. 'Best AI Tools' could group by Writing, Image, Video)\n"
    "- Weave content gaps into relevant sections — do NOT create separate "
    "sections for each gap\n"
    "- Tone: authoritative but accessible, unless specified otherwise"
)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Headings that are clearly site navigation, sidebar, or footer
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
    r"^\d+\s+|"  # numeric prefix: "8 AI Agents", "10 Ways", "5 Tools"
    r"\b(best|top\s+\d+|top\s+\w+|tools?|apps?|generators?|platforms?|"
    r"software|alternatives?|plugins?|extensions?|resources?|examples?|"
    r"ways?|tips?|tricks?|strategies?|ideas?|hacks?)\b",
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
_TOPIC_NUMBER_RE = re.compile(r"^(\d+)\s+")

# Detects "alternatives" topics → flat listicle, no sub-categories
_FLAT_LISTICLE_RE = re.compile(
    r"\b(alternatives?|replacements?|substitutes?|competitors?|options?|picks?)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_format(topic: str, brief_format: "str | None") -> str:
    """Deterministically override the classifier when topic clearly signals a format."""
    if _COMPARISON_SIGNALS.search(topic):
        return "comparison"
    if _TUTORIAL_SIGNALS.search(topic):
        return "tutorial"
    if _LISTICLE_SIGNALS.search(topic):
        return "listicle"
    return brief_format or "explainer"


def _is_flat_listicle(topic: str) -> bool:
    """True when listicle items are all the same type (no natural sub-categories).

    'Best n8n Alternatives' → flat (H2 per item).
    'Best AI Tools for Marketing' → could be categorised (H2 = category, H3 = tool).
    Used as fallback when content_brief.has_subcategories is not available.
    """
    return bool(_FLAT_LISTICLE_RE.search(topic))


def _format_instructions(state: SEOPipelineState, effective_format: str) -> str:
    brief = state.get("content_brief")

    elements = ", ".join(brief.required_elements) if brief else ""
    patterns_block = "\n".join(f"  - {p}" for p in brief.structural_patterns) if brief else ""

    format_section = f"CONTENT FORMAT: {effective_format}\n"
    if brief:
        intent = brief.search_intent if brief.search_intent else "informational"
        format_section += (
            f"SEARCH INTENT: {intent}\n"
            f"TARGET AUDIENCE: {brief.audience} — {brief.writing_style_notes}\n"
            f"TONE: {brief.tone.replace('_', ' ')}\n"
        )
        # Intent-specific guidance
        if intent == "commercial_investigation":
            format_section += (
                "INTENT NOTE: Readers are comparing options before buying. "
                "Include pros/cons, pricing context, and clear recommendations.\n"
            )
        elif intent == "transactional":
            format_section += (
                "INTENT NOTE: Readers are ready to act. "
                "Include clear CTAs, pricing, and setup/onboarding details.\n"
            )
    else:
        format_section += "TONE: authoritative but accessible\n"

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

    Consumes the strategy contract from content_brief where available:
    - brief.recommended_tools → tool/product names (pre-extracted, pre-filtered)
    - brief.has_subcategories → flat vs categorised listicle structure
    Falls back to raw competitor_insights when brief is unavailable.
    """
    insights = state.get("competitor_insights")
    brief = state.get("content_brief")

    if not insights or insights.pages_scraped == 0:
        return ""

    target_wc = state["target_word_count"]
    is_listicle = effective_format == "listicle" or _LISTICLE_SIGNALS.search(state["topic"])

    # Competitor word count context
    avg_wc = insights.avg_word_count if hasattr(insights, "avg_word_count") else 0
    wc_note = ""
    if avg_wc and abs(avg_wc - target_wc) > target_wc * 0.3:
        if target_wc < avg_wc:
            wc_note = (
                f"\nNOTE: Competitors average {avg_wc} words but our target is {target_wc} words. "
                f"Write a MORE FOCUSED, CONCISE piece — do not try to match competitor length.\n"
            )
        else:
            wc_note = (
                f"\nNOTE: Competitors average {avg_wc} words but our target is {target_wc} words. "
                f"We aim for more comprehensive coverage than competitors.\n"
            )

    # --- Listicle: use strategy contract for tools and subcategory structure ---
    if is_listicle:
        # Prefer brief.recommended_tools (pre-extracted in content_classifier)
        entities = list(brief.recommended_tools) if brief and brief.recommended_tools else []
        # Fallback: extract from raw insights
        if not entities:
            entities = extract_tool_names(insights)

        if entities:
            structural_lines = "\n".join(
                f"  - {insights.structural_signals[i]}"
                for i in range(min(3, len(insights.structural_signals)))
            )

            # Use brief.has_subcategories if available, else fall back to topic heuristic
            has_subcats = brief.has_subcategories if brief else not _is_flat_listicle(state["topic"])
            if not has_subcats:
                structure_guidance = (
                    "LISTICLE STRUCTURE — FLAT LIST (all items are the same type):\n"
                    "  H2 = EACH INDIVIDUAL ITEM (one H2 per tool/product/alternative)\n"
                    "  Do NOT group into categories — the items are all in the same category."
                )
            else:
                structure_guidance = (
                    "LISTICLE STRUCTURE — CATEGORISED (items naturally group):\n"
                    "  H2 = category name, H3 = individual item within that category.\n"
                    "  Use 2-4 categories max. Each category must have 2+ items."
                )

            return (
                f"\nCOMPETITOR ANALYSIS ({insights.pages_scraped}/{insights.pages_attempted} pages scraped):\n"
                f"{structural_lines}\n"
                f"{wc_note}"
                f"\n{structure_guidance}\n"
                f"\nVALIDATED TOOLS/PRODUCTS FROM COMPETITORS (named products only):\n"
                + "\n".join(f"  - {name}" for name in entities[:15])
            )

    # --- Non-listicle: only show COMMON headings (2+ pages) ---
    clean_common = clean_competitor_headings(insights.common_headings)
    structural_summary = "\n".join(f"  - {s}" for s in insights.structural_signals[:5])

    block = (
        f"\nCOMPETITOR ANALYSIS ({insights.pages_scraped}/{insights.pages_attempted} pages scraped):\n"
        f"{structural_summary}\n"
        f"{wc_note}"
    )
    if clean_common:
        block += (
            "\nHEADINGS THAT APPEAR IN 2+ TOP-RANKING PAGES "
            "(use as structural signal, not copy):\n"
            + "\n".join(f"  - {h}" for h in clean_common[:8])
        )
    return block


def _build_prompt(state: SEOPipelineState, effective_format: str) -> str:
    brief = state.get("content_brief")

    # Only HIGH and MEDIUM priority gaps
    all_gaps = state["content_gaps"] or []
    relevant_gaps = [g for g in all_gaps if g.priority in ("high", "medium")]
    if not relevant_gaps:
        relevant_gaps = all_gaps[:4]

    gaps_text = "\n".join(
        f"- [{g.priority.upper()}] {g.topic}: {g.reason}"
        for g in relevant_gaps
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

    target_wc = state["target_word_count"]

    # Use strategy contract section count if available, else compute
    topic_num_match = _TOPIC_NUMBER_RE.match(state["topic"])
    exact_item_count = int(topic_num_match.group(1)) if topic_num_match else None
    avg_h2 = insights.avg_h2_count if insights else 0

    if brief and brief.suggested_section_count:
        rec_sections = brief.suggested_section_count
        _, section_math = recommend_section_count(
            target_wc, avg_h2, effective_format, exact_item_count,
        )
    else:
        rec_sections, section_math = recommend_section_count(
            target_wc, avg_h2, effective_format, exact_item_count,
        )

    if exact_item_count:
        section_count_instruction = (
            f"SECTION COUNT: The topic promises exactly {exact_item_count} items. "
            f"Generate EXACTLY {exact_item_count} H2 sections — one per item. "
            f"Do NOT add intro/conclusion as H2 sections.\n"
            f"Math: {section_math}"
        )
        listicle_item_note = (
            f"\nCRITICAL: This is a '{exact_item_count}-item' listicle. "
            f"Every H2 must be a specific named item (tool, agent, strategy, etc.). "
            f"Do NOT generate generic H2s like 'Introduction', 'Conclusion', 'How to Choose'."
        )
    else:
        words_per_section = target_wc // max(1, rec_sections)
        section_count_instruction = (
            f"SECTION COUNT: Generate {rec_sections} H2 sections "
            f"(~{words_per_section} words each to be substantive).\n"
            f"Math: {section_math}"
        )
        listicle_item_note = ""

    # Gap instruction: weave into sections, don't create standalone gap sections
    gap_instruction = ""
    if gaps_text:
        gap_instruction = (
            f"\nContent gaps to address (weave into relevant sections, do NOT create separate sections per gap):\n"
            f"{gaps_text}\n"
        )

    # Edge case: short articles
    short_article_note = ""
    if target_wc < 800:
        short_article_note = (
            "\nNOTE: This is a short article (<800 words). Keep sections concise. "
            "3-4 H2 sections max. Skip intro/conclusion H2s — use the title and "
            "a brief opening paragraph instead.\n"
        )

    # Edge case: minimal competitor data
    sparse_data_note = ""
    if insights and insights.pages_scraped <= 1:
        sparse_data_note = (
            "\nNOTE: Only 1 competitor page was successfully scraped. "
            "Rely more on topic expertise and PAA questions than competitor structure.\n"
        )

    return f"""Create a comprehensive SEO article outline for:

Topic: "{state['topic']}"
Primary keyword: "{state['primary_keyword']}"
Target word count: {target_wc} words
Language: {state['language']}

{format_block}{gap_instruction}{competitor_block}
{secondary_kw_block}
{listicle_item_note}{short_article_note}{sparse_data_note}

Requirements:
- Title must include the primary keyword naturally (variations/plurals are fine)
- Meta description: ~155 characters, include primary keyword (we validate length programmatically)
- {section_count_instruction}
- Each section must list 2–4 specific key points to cover
- INTRODUCTION: Include 2–3 key points. The primary keyword MUST appear in the first 100 words. Hook the reader with a specific fact, question, or bold claim.
- CONCLUSION: Include a summary + clear recommendation or CTA. Do NOT title it generically.
- Sections must be genuine article content — NO navigation, contact, subscription, sidebar, FAQ, or editorial boilerplate sections
- Do NOT copy competitor page navigation elements as sections"""


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

        # --- Check keyword presence in title (fuzzy — handles plural/variations) ---
        kw = state["primary_keyword"].lower()
        if not keyword_fuzzy_match(outline.title, kw):
            logger.warning(
                "[%s] outline_generator: keyword '%s' weakly present in title '%s'",
                job_id, kw, outline.title,
            )

        # --- Enforce meta description length (150–160 chars) ---
        meta = outline.meta_description.strip()
        if not (140 <= len(meta) <= 165):
            if len(meta) > 165:
                truncated = meta[:157]
                last_space = truncated.rfind(" ")
                meta = (truncated[:last_space] if last_space > 140 else truncated) + "..."
            elif len(meta) < 140:
                suffix = f" A complete guide to {state['primary_keyword']}."
                meta = (meta + suffix)[:160].rsplit(" ", 1)[0]
            outline = outline.model_copy(update={"meta_description": meta})

        # --- Check keyword presence in H2 headings (fuzzy) ---
        h2_headings = [s.heading for s in outline.sections if s.level.value == "h2"]
        if h2_headings and not any(keyword_fuzzy_match(h, kw) for h in h2_headings):
            logger.warning(
                "[%s] outline_generator: keyword '%s' not found in any H2 heading",
                job_id, kw,
            )

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
