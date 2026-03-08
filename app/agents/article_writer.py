"""
Node: article_writer

Writes the article section-by-section. Each H2/H3 section is a separate LLM
call with the full outline + SERP context provided for coherence.
Updates job status to DRAFTING.
"""

import logging

from app.models.article import ArticleSection, HeadingLevel, OutlineSection
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service
from app.utils.text_utils import count_words, section_max_tokens

logger = logging.getLogger(__name__)

_SYSTEM_BASE = (
    "You are an expert content writer specialising in SEO-optimised articles. "
    "Write engaging, authoritative, and readable content. "
    "Integrate the primary keyword naturally — never keyword-stuff. "
    "Each section should flow logically from the previous one. "
    "Vary sentence length and structure — mix short punchy sentences with longer explanatory ones. "
    "Use specific examples, data points, and named tools/products — never vague placeholders. "
    "Write with a clear point of view — take positions and make recommendations. "
    "Avoid filler phrases like 'In today's world', 'It's important to note', or 'As we all know'. "
    "Open sections with a hook — a surprising fact, a question, or a bold claim."
)

_FORMAT_SYSTEM_SUFFIX = {
    "tutorial": (
        " You are writing a step-by-step technical tutorial. "
        "Use numbered lists for sequential steps. "
        "Include real tool names and concrete examples (not vague placeholders). "
        "Add ASCII architecture diagrams where they aid understanding. "
        "Include code snippets in markdown fences when showing implementation. "
        "Be specific — name actual technologies, providers, and APIs."
    ),
    "comparison": (
        " You are writing a comparison article. "
        "Be objective and data-driven. "
        "Use markdown tables to compare features side-by-side. "
        "Name real products with honest pros and cons. "
        "End sections with a clear recommendation for specific use cases."
    ),
    "listicle": (
        " You are writing a listicle. "
        "Each item needs a punchy opening sentence, concrete details, and a verdict. "
        "Name real tools and include specific reasons why each made the list. "
        "Avoid vague descriptions — be specific about what makes each item useful."
    ),
    "explainer": (
        " You are writing an explainer article. "
        "Use analogies to make abstract concepts concrete. "
        "Include ASCII diagrams to visualise architecture or flows. "
        "Define technical terms when first introduced. "
        "Build understanding progressively — simple to complex."
    ),
    "case_study": (
        " You are writing a case study. "
        "Ground every claim in a real or realistic scenario with named entities. "
        "Include metrics and measurable outcomes. "
        "Tell a narrative: problem → approach → result → lesson."
    ),
}


def _flatten_sections(sections: list[OutlineSection]) -> list[OutlineSection]:
    """Flatten nested outline into a sequential list (H2 → H3 → H3 → H2 …)."""
    flat: list[OutlineSection] = []
    for section in sections:
        flat.append(section)
        flat.extend(section.subsections)
    return flat


def _build_section_prompt(
    section: OutlineSection,
    topic: str,
    primary_keyword: str,
    target_words: int,
    total_target_words: int,
    outline_summary: str,
    serp_context: str,
    is_first: bool,
    content_format: str,
    required_elements: list[str],
    content_gaps: str = "",
) -> str:
    key_points = "\n".join(f"  - {p}" for p in section.key_points)
    intro_note = (
        "This is the OPENING section — the first paragraph must include "
        f'the primary keyword "{primary_keyword}" naturally.\n'
        if is_first
        else ""
    )

    # Format-specific element hints for this section
    element_hints = {
        "numbered_steps": "Use a numbered list for any sequential process described.",
        "code_snippets": "Include a code snippet in a markdown fenced block (```language) if it illustrates the concept.",
        "architecture_diagram": "Include an ASCII diagram if visualising a system or flow.",
        "comparison_table": "Include a markdown table to compare options side-by-side.",
        "tool_list": "Name specific real tools with brief descriptions.",
        "prerequisites_section": "List concrete prerequisites the reader needs before starting.",
        "real_examples": "Ground the content in a concrete real-world example with named tools or companies.",
        "pros_cons_list": "Include explicit pros and cons as bullet lists.",
        "metrics_data": "Include specific numbers, benchmarks, or performance data.",
    }
    applicable_hints = [
        f"- {element_hints[el]}"
        for el in required_elements
        if el in element_hints
    ]
    elements_block = (
        "\nContent requirements for this section:\n" + "\n".join(applicable_hints)
        if applicable_hints else ""
    )

    _format_notes = {
        "tutorial": "If this section describes a process, use numbered steps. Name real tools, APIs, and providers.",
        "comparison": "Use a markdown table if comparing options. Be objective — state pros and cons explicitly.",
        "listicle": "Each item needs a bold name, one-line description, and a clear reason it's on the list.",
        "explainer": "Use an analogy or ASCII diagram if it clarifies the concept. Define terms on first use.",
        "case_study": "Ground this in a concrete scenario with named entities and measurable outcomes.",
    }
    format_note = f"\nFormat guidance: {_format_notes[content_format]}" if content_format in _format_notes else ""

    gaps_block = f"\nContent gaps to address (topics competitors miss — weave in where relevant):\n{content_gaps}" if content_gaps else ""

    min_words = int(target_words * 0.85)
    max_words = int(target_words * 1.15)

    return f"""Write the following section for an article about "{topic}".

Section heading: {section.heading} ({section.level.value.upper()})
WORD COUNT: Write between {min_words}–{max_words} words for this section.
  - The full article target is {total_target_words} words across all sections.
  - Your per-section budget is {target_words} words — do not exceed {max_words} words.
  - Stop writing when you reach {max_words} words even if you could say more.
Primary keyword: "{primary_keyword}"
{intro_note}{format_note}
Key points to cover — address EACH one concisely:
{key_points}
{elements_block}

Article outline (for context and coherence):
{outline_summary}

Competitor context (angles already covered — differentiate where possible):
{serp_context}
{gaps_block}

Do not include the heading itself in your response.
Use markdown formatting where appropriate (numbered lists, code blocks, tables).
Be specific — use real tool names, concrete examples, and precise language."""


async def article_writer(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    job_manager.update_status(job_id, JobStatus.DRAFTING)
    logger.info("[%s] article_writer: starting section-by-section generation", job_id)

    outline = state["outline"]
    serp_data = state["serp_data"]
    primary_keyword = state["primary_keyword"]
    target_word_count = state["target_word_count"]
    brief = state.get("content_brief")
    content_format = brief.format if brief else "explainer"
    required_elements = brief.required_elements if brief else []

    # Build system prompt — prefer SERP-derived style notes over static suffix
    word_count_directive = (
        f" The full article target is {target_word_count} words total across all sections. "
        "Each section prompt specifies a word range — stay within it. "
        "Do not pad or repeat yourself to hit a count. Do not exceed the maximum. "
        "Write focused, specific content."
    )
    if brief and brief.writing_style_notes:
        system = (
            _SYSTEM_BASE
            + word_count_directive
            + f"\n\nWRITING STYLE (derived from what's ranking for this topic): {brief.writing_style_notes}"
            + f"\nCOMPETITIVE ANGLE: {brief.competitive_angle}"
        )
    else:
        system = _SYSTEM_BASE + word_count_directive + _FORMAT_SYSTEM_SUFFIX.get(content_format, "")

    flat_sections = _flatten_sections(outline.sections)
    # Distribute the total word budget evenly across all actual sections.
    # H2 sections are written at full budget; H3 subsections at 60% (they're narrower).
    # We do NOT use suggested_section_count here — that's a structural hint for the
    # outline, not a word-budget denominator. Using it caused under-allocation when
    # the actual flat section count differed.
    h2_count = sum(1 for s in flat_sections if s.level.value == "h2")
    h3_count = len(flat_sections) - h2_count
    # Weight: each H2 counts as 1.0, each H3 as 0.6 → budget is proportional to depth
    total_weight = max(1, h2_count * 1.0 + h3_count * 0.6)
    words_per_h2 = max(120, int(target_word_count / total_weight))
    words_per_h3 = max(80, int(target_word_count * 0.6 / total_weight))

    outline_summary = f"Title: {outline.title}\nSections: " + ", ".join(
        s.heading for s in flat_sections
    )

    # Build enriched SERP context with titles, themes, and PAA questions
    serp_parts: list[str] = []
    if serp_data:
        serp_parts.append("Competitor pages:")
        serp_parts.extend(
            f"- {r.title}: {r.snippet}" for r in serp_data.results[:5]
        )
        if serp_data.themes:
            serp_parts.append("\nCommon themes:")
            serp_parts.extend(
                f"- {t.theme} (seen in {t.frequency} results)" for t in serp_data.themes
            )
        if serp_data.people_also_ask:
            serp_parts.append("\nQuestions people ask:")
            serp_parts.extend(f"- {q}" for q in serp_data.people_also_ask)
    serp_context = "\n".join(serp_parts)

    # Build content gaps context
    content_gaps = state.get("content_gaps") or []
    gaps_context = "\n".join(
        f"- [{g.priority.upper()}] {g.topic}: {g.reason}"
        for g in content_gaps
    )

    draft_sections: list[ArticleSection] = []
    try:
        for i, section in enumerate(flat_sections):
            is_h2 = section.level.value == "h2"
            section_target = words_per_h2 if is_h2 else words_per_h3
            logger.info(
                "[%s] article_writer: writing section %d/%d — %s (~%d words)",
                job_id, i + 1, len(flat_sections), section.heading, section_target,
            )
            prompt = _build_section_prompt(
                section=section,
                topic=state["topic"],
                primary_keyword=primary_keyword,
                target_words=section_target,
                total_target_words=target_word_count,
                outline_summary=outline_summary,
                serp_context=serp_context,
                is_first=(i == 0),
                content_format=content_format,
                required_elements=required_elements,
                content_gaps=gaps_context,
            )
            section_text: str = await llm_service.call_llm(
                prompt=prompt,
                system=system,
                response_model=None,
                temperature=0.7,
                max_tokens=section_max_tokens(section_target),
            )
            draft_sections.append(
                ArticleSection(
                    heading=section.heading,
                    level=section.level,
                    content=section_text,
                    word_count=count_words(section_text),
                )
            )

        total_words = sum(s.word_count for s in draft_sections)
        logger.info(
            "[%s] article_writer: completed %d sections, ~%d words",
            job_id, len(draft_sections), total_words,
        )
        job_manager.save_pipeline_artifact(job_id, "draft", {
            "total_words": total_words,
            "content_format": content_format,
            "sections": [
                {"heading": s.heading, "level": s.level.value,
                 "word_count": s.word_count, "content": s.content}
                for s in draft_sections
            ],
        })
        return {"draft_sections": draft_sections, "status": JobStatus.DRAFTING}

    except Exception as e:
        logger.exception("[%s] article_writer failed on section %d", job_id, len(draft_sections) + 1)
        if draft_sections:
            # Return partial sections so downstream nodes have something to work with
            logger.info(
                "[%s] article_writer: returning %d partial sections",
                job_id, len(draft_sections),
            )
            return {"draft_sections": draft_sections, "status": JobStatus.DRAFTING}
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "drafting_failed", "error": str(e)}
