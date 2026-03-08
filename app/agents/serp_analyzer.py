"""
Node: serp_analyzer

Fetches top SERP results for the topic and stores them in state.
Updates job status to RESEARCHING.
"""

import logging

from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.serp_service import serp_service

logger = logging.getLogger(__name__)


async def serp_analyzer(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    job_manager.update_status(job_id, JobStatus.RESEARCHING)
    # Search using topic — it reflects actual user search intent and returns the
    # competing pages we need to beat. e.g. "8 AI Agents for Content Creation"
    # returns listicle competitors, while just "ai agent for content creation"
    # returns generic explainer pages.
    search_query = state["topic"]
    logger.info("[%s] serp_analyzer: fetching SERP for '%s'", job_id, search_query)

    try:
        serp_data = await serp_service.search(search_query)
        logger.info(
            "[%s] serp_analyzer: got %d results, %d PAA questions",
            job_id,
            len(serp_data.results),
            len(serp_data.people_also_ask),
        )
        job_manager.save_pipeline_artifact(job_id, "serp", {
            "query": serp_data.query,
            "results": [
                {"position": r.position, "title": r.title, "url": r.url,
                 "domain": r.domain, "snippet": r.snippet}
                for r in serp_data.results
            ],
            "people_also_ask": serp_data.people_also_ask,
            "themes": [
                {"theme": t.theme, "frequency": t.frequency, "sources": t.sources}
                for t in serp_data.themes
            ],
        })
        return {"serp_data": serp_data, "status": JobStatus.RESEARCHING}
    except Exception as e:
        logger.exception("[%s] serp_analyzer failed", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "researching_failed", "error": str(e)}
