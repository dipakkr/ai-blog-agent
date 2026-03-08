import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.config import settings
from app.models.article import Article
from app.models.job import AttemptRecord, JobDetailResponse, JobResponse, JobStatus
from app.models.request import GenerateRequest
from app.queue import enqueue_pipeline
from app.services.job_manager import JobRecord, job_manager

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI SEO Content Generation Platform",
    description="Generates SEO-optimised articles using a LangGraph agent pipeline.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.post("/generate", response_model=JobResponse, status_code=202)
async def generate_article(request: GenerateRequest) -> JobResponse:
    """Create a new article generation job and enqueue it for processing.

    Jobs are dispatched to a Redis/RQ worker when Redis is available, or run
    as an in-process asyncio task when Redis is not configured (dev fallback).
    Returns immediately with the job_id so the client can poll /jobs/{id}.
    """
    job = job_manager.create_job(request)
    await enqueue_pipeline(job.id, job.topic, job.primary_keyword, job.target_word_count, job.language)
    return JobResponse(job_id=job.id, status=JobStatus(job.status))


@app.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str) -> JobDetailResponse:
    """Get status and result for a specific job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _record_to_response(job)


@app.post("/jobs/{job_id}/retry", response_model=JobResponse, status_code=202)
async def retry_job(job_id: str) -> JobResponse:
    """Resume a failed job from its last LangGraph checkpoint.

    Only FAILED jobs can be retried. The pipeline resumes from the last
    successfully completed node (thread_id == job_id in the checkpoint DB).
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status != JobStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is '{job.status}' — only FAILED jobs can be retried",
        )

    job_manager.save_to_history(job_id)
    job_manager.update_status(job_id, JobStatus.PENDING, error=None)
    await enqueue_pipeline(job.id, job.topic, job.primary_keyword, job.target_word_count, job.language)
    logger.info("Job %s re-enqueued for retry", job_id)
    return JobResponse(job_id=job.id, status=JobStatus.PENDING)


@app.get("/jobs/{job_id}/history", response_model=list[AttemptRecord])
async def get_job_history(job_id: str) -> list[AttemptRecord]:
    """Return all previous attempt snapshots for a job (populated on each retry)."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    raw = job_manager.get_history(job_id)
    result = []
    for entry in raw:
        article = None
        if entry.get("result"):
            try:
                article = Article.model_validate(entry["result"])
            except (ValidationError, ValueError):
                pass
        result.append(AttemptRecord(
            attempt=entry["attempt"],
            timestamp=entry["timestamp"],
            status=entry["status"],
            error=entry.get("error"),
            result=article,
        ))
    return result


@app.get("/jobs/{job_id}/pipeline")
async def get_pipeline_data(job_id: str) -> dict:
    """Return intermediate pipeline artifacts for a job.

    Each key corresponds to a pipeline node that has completed:
    - serp: raw SERP results, themes, People Also Ask
    - classification: detected content format, audience, required elements
    - gaps: content gaps identified vs competitors
    - outline: article structure with sections and key points
    - draft: written sections with word counts and content
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if not job.pipeline_data:
        return {}
    return json.loads(job.pipeline_data)


@app.get("/jobs", response_model=list[JobDetailResponse])
async def list_jobs() -> list[JobDetailResponse]:
    """List all jobs ordered by creation time (newest first)."""
    return [_record_to_response(j) for j in job_manager.list_jobs()]
