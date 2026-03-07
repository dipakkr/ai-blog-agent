import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import ValidationError

from app.config import settings
from app.models.article import Article
from app.models.job import JobDetailResponse, JobResponse, JobStatus
from app.models.request import GenerateRequest
from app.services.job_manager import JobRecord, job_manager

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI SEO Content Generation Platform",
    description="Generates SEO-optimised articles using a LangGraph agent pipeline.",
    version="0.1.0",
)


def _record_to_response(job: JobRecord) -> JobDetailResponse:
    result: Article | None = None
    if job.result:
        try:
            result = Article.model_validate_json(job.result)
        except (ValidationError, ValueError):
            logger.exception("Failed to deserialise result for job %s", job.id)
    return JobDetailResponse(
        job_id=job.id,
        status=JobStatus(job.status),
        topic=job.topic,
        primary_keyword=job.primary_keyword,
        target_word_count=job.target_word_count,
        language=job.language,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
        result=result,
    )


async def run_pipeline(
    job_id: str,
    topic: str,
    primary_keyword: str,
    target_word_count: int,
    language: str,
) -> None:
    """BackgroundTask entry point. Invokes the LangGraph pipeline for a job.

    Wired up in Phase 4 — app/agents/pipeline.py.
    """
    try:
        # from app.agents.pipeline import run_seo_pipeline
        # await run_seo_pipeline(job_id, topic, primary_keyword, target_word_count, language)
        logger.info("Pipeline stub called for job %s — wire up in Phase 4", job_id)
    except Exception as e:
        logger.exception("Pipeline failed for job %s", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))


@app.post("/generate", response_model=JobResponse, status_code=202)
async def generate_article(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    """Create a new article generation job and kick off the pipeline."""
    job = job_manager.create_job(request)
    background_tasks.add_task(
        run_pipeline,
        job.id,
        job.topic,
        job.primary_keyword,
        job.target_word_count,
        job.language,
    )
    return JobResponse(job_id=job.id, status=JobStatus(job.status))


@app.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str) -> JobDetailResponse:
    """Get status and result for a specific job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _record_to_response(job)


@app.get("/jobs", response_model=list[JobDetailResponse])
async def list_jobs() -> list[JobDetailResponse]:
    """List all jobs ordered by creation time (newest first)."""
    return [_record_to_response(j) for j in job_manager.list_jobs()]
