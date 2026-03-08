"""
Job queue abstraction.

Primary backend: Redis Queue (RQ) for durable, worker-process job execution.
Fallback: in-process asyncio task (FastAPI BackgroundTasks behaviour) when
Redis is unavailable — preserves dev-mode usability without requiring Redis.

Usage
-----
    from app.queue import enqueue_pipeline

    enqueue_pipeline(job_id, topic, primary_keyword, target_word_count, language)

The caller never touches Redis or RQ directly.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _get_rq_queue():
    """Return an RQ Queue, or None if Redis is unavailable."""
    try:
        from redis import Redis
        from redis.exceptions import ConnectionError as RedisConnectionError
        from rq import Queue

        from app.config import settings

        conn = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        conn.ping()  # fail fast if Redis is down
        return Queue("seo_pipeline", connection=conn)
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — falling back to in-process execution", exc)
        return None


# Module-level queue singleton (None when Redis is down)
_queue = _get_rq_queue()


# ---------------------------------------------------------------------------
# Worker-side entry point (called by `rq worker` in a subprocess)
# ---------------------------------------------------------------------------

def run_pipeline_sync(
    job_id: str,
    topic: str,
    primary_keyword: str,
    target_word_count: int,
    language: str,
) -> None:
    """Synchronous wrapper executed by the RQ worker process.

    RQ workers are synchronous; we wrap the async pipeline with asyncio.run().
    """
    from app.agents.pipeline import run_seo_pipeline
    from app.models.job import JobStatus
    from app.services.job_manager import job_manager

    try:
        asyncio.run(
            run_seo_pipeline(job_id, topic, primary_keyword, target_word_count, language)
        )
    except Exception as e:
        logger.exception("Pipeline failed for job %s", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def enqueue_pipeline(
    job_id: str,
    topic: str,
    primary_keyword: str,
    target_word_count: int,
    language: str,
) -> str:
    """Enqueue a pipeline job.

    Returns "queued" if dispatched to Redis/RQ, "inline" if fallback was used.
    Must be called from an async context (FastAPI handler) so that the inline
    fallback can safely schedule a coroutine on the running event loop.
    """
    if _queue is not None:
        _queue.enqueue(
            run_pipeline_sync,
            job_id,
            topic,
            primary_keyword,
            target_word_count,
            language,
            job_timeout=1800,  # 30 min max per job
        )
        logger.info("Job %s enqueued to Redis queue", job_id)
        return "queued"

    # Fallback: schedule as a background coroutine on the running event loop.
    # asyncio.create_task() requires an active event loop (guaranteed in an async
    # FastAPI handler) — avoids the get_event_loop() deprecation in Python 3.10+.
    logger.info("Job %s running inline (no Redis)", job_id)
    asyncio.create_task(_run_inline(job_id, topic, primary_keyword, target_word_count, language))
    return "inline"


async def _run_inline(
    job_id: str,
    topic: str,
    primary_keyword: str,
    target_word_count: int,
    language: str,
) -> None:
    from app.agents.pipeline import run_seo_pipeline
    from app.models.job import JobStatus
    from app.services.job_manager import job_manager

    try:
        await run_seo_pipeline(job_id, topic, primary_keyword, target_word_count, language)
    except Exception as e:
        logger.exception("Inline pipeline failed for job %s", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
