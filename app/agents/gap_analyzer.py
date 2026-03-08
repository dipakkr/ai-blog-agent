"""
Node: gap_analyzer

Analyses SERP data to identify content gaps — topics and angles not well
covered by current top-ranking pages.
"""

import logging

from pydantic import BaseModel

from app.models.job import JobStatus
from app.models.serp import ContentGap, SERPData  # noqa: F401 (SERPData used in type hint)
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an expert SEO content strategist. "
    "Your job is to analyse SERP data and identify genuine content gaps — "
    "topics, angles, or questions that existing top-ranking pages fail to address well."
)


class _GapList(BaseModel):
    gaps: list[ContentGap]


def _build_prompt(topic: str, serp_data: SERPData, content_brief: "ContentBrief | None" = None) -> str:
    results_summary = "\n".join(
        f"{r.position}. [{r.domain}] {r.title}\n   {r.snippet}"
        for r in serp_data.results[:8]
    )
    themes_summary = "\n".join(
        f"- {t.theme} (seen in {t.frequency} results)"
        for t in serp_data.themes
    )
    brief_context = ""
    if content_brief:
        brief_context = f"""
Content format: {content_brief.format}
Target audience: {content_brief.audience}
Tone: {content_brief.tone}

Tailor gap analysis to this format — e.g., a tutorial needs "missing prerequisite steps" or "missing troubleshooting" gaps, a comparison needs "missing criteria" or "missing alternatives" gaps.
"""
    return f"""Topic: "{topic}"
{brief_context}
Top SERP results:
{results_summary}

Themes already well covered:
{themes_summary}

Identify 5–8 content gaps: topics, angles, or subtopics that:
1. Are NOT adequately covered by the existing top results
2. Would genuinely help the target audience
3. Represent real search intent not yet satisfied

For each gap, assess its priority (high / medium / low) based on likely search demand."""


async def gap_analyzer(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    logger.info("[%s] gap_analyzer: identifying content gaps", job_id)

    try:
        prompt = _build_prompt(state["topic"], state["serp_data"], state.get("content_brief"))
        result: _GapList = await llm_service.call_llm(
            prompt=prompt,
            system=SYSTEM,
            response_model=_GapList,
            temperature=0.5,
            max_tokens=2048,
        )
        logger.info("[%s] gap_analyzer: found %d gaps", job_id, len(result.gaps))
        job_manager.save_pipeline_artifact(job_id, "gaps", [
            {"topic": g.topic, "reason": g.reason, "priority": g.priority}
            for g in result.gaps
        ])
        return {"content_gaps": result.gaps, "status": JobStatus.RESEARCHING}
    except Exception as e:
        logger.exception("[%s] gap_analyzer failed — continuing with no gaps", job_id)
        return {"content_gaps": [], "status": JobStatus.RESEARCHING, "error": str(e)}
