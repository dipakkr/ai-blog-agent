"""
Node: article_writer

Writes the article section-by-section. Each H2/H3 section is a separate LLM
call with the full outline + SERP context provided for coherence.
Updates job status to DRAFTING.
"""

import logging

from pydantic import BaseModel

from app.models.article import ArticleSection, HeadingLevel, OutlineSection
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service
from app.utils.text_utils import count_words, section_max_tokens

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an expert content writer specialising in SEO-optimised articles. "
    "Write engaging, authoritative, and readable content. "
    "Integrate the primary keyword naturally — never keyword-stuff. "
    "Each section should flow logically from the previous one."
)


class _SectionContent(BaseModel):
    content: str  # full prose for the section, markdown-free plain text


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
    outline_summary: str,
    serp_context: str,
    is_first: bool,
) -> str:
    key_points = "\n".join(f"  - {p}" for p in section.key_points)
    intro_note = (
        "This is the OPENING section — the first paragraph must include "
        f'the primary keyword "{primary_keyword}" naturally.\n'
        if is_first
        else ""
    )
    return f"""Write the following section for an article about "{topic}".

Section heading: {section.heading} ({section.level.value.upper()})
Target length: ~{target_words} words
Primary keyword: "{primary_keyword}"
{intro_note}
Key points to cover:
{key_points}

Article outline (for context and coherence):
{outline_summary}

Competitor context (angles already covered — differentiate where possible):
{serp_context}

Write flowing prose only. Do not include the heading itself. Do not use markdown."""


async def article_writer(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    job_manager.update_status(job_id, JobStatus.DRAFTING)
    logger.info("[%s] article_writer: starting section-by-section generation", job_id)

    outline = state["outline"]
    serp_data = state["serp_data"]
    primary_keyword = state["primary_keyword"]
    target_word_count = state["target_word_count"]

    flat_sections = _flatten_sections(outline.sections)
    words_per_section = max(150, target_word_count // len(flat_sections))

    outline_summary = f"Title: {outline.title}\nSections: " + ", ".join(
        s.heading for s in flat_sections
    )
    serp_context = "\n".join(
        f"- {r.title}: {r.snippet}" for r in (serp_data.results[:5] if serp_data else [])
    )

    try:
        draft_sections: list[ArticleSection] = []
        for i, section in enumerate(flat_sections):
            logger.info(
                "[%s] article_writer: writing section %d/%d — %s",
                job_id, i + 1, len(flat_sections), section.heading,
            )
            prompt = _build_section_prompt(
                section=section,
                topic=state["topic"],
                primary_keyword=primary_keyword,
                target_words=words_per_section,
                outline_summary=outline_summary,
                serp_context=serp_context,
                is_first=(i == 0),
            )
            result: _SectionContent = await llm_service.call_llm(
                prompt=prompt,
                system=SYSTEM,
                response_model=_SectionContent,
                temperature=0.7,
                max_tokens=section_max_tokens(words_per_section),
            )
            draft_sections.append(
                ArticleSection(
                    heading=section.heading,
                    level=section.level,
                    content=result.content,
                    word_count=count_words(result.content),
                )
            )

        total_words = sum(s.word_count for s in draft_sections)
        logger.info(
            "[%s] article_writer: completed %d sections, ~%d words",
            job_id, len(draft_sections), total_words,
        )
        return {"draft_sections": draft_sections, "status": JobStatus.DRAFTING}

    except Exception as e:
        logger.exception("[%s] article_writer failed", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "drafting_failed", "error": str(e)}
