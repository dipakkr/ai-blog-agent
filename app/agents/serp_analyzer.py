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
    logger.info("[%s] serp_analyzer: fetching SERP for '%s'", job_id, state["topic"])

    try:
        serp_data = await serp_service.search(state["topic"])
        logger.info(
            "[%s] serp_analyzer: got %d results, %d PAA questions",
            job_id,
            len(serp_data.results),
            len(serp_data.people_also_ask),
        )
        return {"serp_data": serp_data, "status": JobStatus.RESEARCHING}
    except Exception as e:
        logger.exception("[%s] serp_analyzer failed", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "researching_failed", "error": str(e)}
