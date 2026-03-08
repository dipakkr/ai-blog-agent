"""
Node: outline_generator

Generates a structured article outline from SERP analysis and content gaps.
Updates job status to OUTLINING.
"""

import logging

from app.models.article import Outline
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


def _build_prompt(state: SEOPipelineState) -> str:
    gaps_text = "\n".join(
        f"- [{g.priority.upper()}] {g.topic}: {g.reason}"
        for g in (state["content_gaps"] or [])
    )
    themes_text = "\n".join(
        f"- {t.theme}" for t in (state["serp_data"].themes if state["serp_data"] else [])
    )
    return f"""Create a comprehensive SEO article outline for:

Topic: "{state['topic']}"
Primary keyword: "{state['primary_keyword']}"
Target word count: {state['target_word_count']} words
Language: {state['language']}

Content gaps to address (prioritised):
{gaps_text}

Competitor themes already covered (differentiate from these):
{themes_text}

Requirements:
- Title must include the primary keyword naturally
- Meta description must be exactly 150–160 characters and include the primary keyword
- Include 4–6 H2 sections with 1–3 H3 subsections each where appropriate
- Each section must list 2–4 specific key points to cover
- Include secondary keywords that support the primary keyword
- Structure should guide a reader from problem → understanding → solution → action"""


async def outline_generator(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    job_manager.update_status(job_id, JobStatus.OUTLINING)
    logger.info("[%s] outline_generator: generating outline for '%s'", job_id, state["topic"])

    try:
        prompt = _build_prompt(state)
        outline: Outline = await llm_service.call_llm(
            prompt=prompt,
            system=SYSTEM,
            response_model=Outline,
            temperature=0.6,
            max_tokens=4096,
        )
        logger.info(
            "[%s] outline_generator: '%s' with %d sections",
            job_id,
            outline.title,
            len(outline.sections),
        )
        return {"outline": outline, "status": JobStatus.OUTLINING}
    except Exception as e:
        logger.exception("[%s] outline_generator failed", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "outlining_failed", "error": str(e)}
