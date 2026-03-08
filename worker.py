"""
RQ worker entry point.

Run with:
    rq worker seo_pipeline --url redis://localhost:6379/0

Or via the helper script:
    python worker.py
"""

import logging

from redis import Redis
from rq import Worker

from app.config import settings

logging.basicConfig(level=settings.log_level)

if __name__ == "__main__":
    conn = Redis.from_url(settings.redis_url)
    worker = Worker(queues=["seo_pipeline"], connection=conn)
    worker.work(with_scheduler=True)
