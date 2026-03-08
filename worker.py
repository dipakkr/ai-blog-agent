"""
RQ worker entry point.

Run with:
    python worker.py

Or directly via rq CLI (Linux/CI only):
    rq worker seo_pipeline --url redis://localhost:6379/0

macOS note: RQ's default Worker forks a child process per job, which crashes on
macOS due to Objective-C runtime restrictions on fork(). SimpleWorker runs jobs
in the same process (no fork) and is the correct choice for macOS development.
On Linux (production), the regular Worker is used for better isolation.
"""

import logging
import sys

from redis import Redis
from rq import Worker
from rq.worker import SimpleWorker

from app.config import settings

logging.basicConfig(level=settings.log_level)

if __name__ == "__main__":
    conn = Redis.from_url(settings.redis_url)

    WorkerClass = SimpleWorker if sys.platform == "darwin" else Worker
    worker = WorkerClass(queues=["seo_pipeline"], connection=conn)
    worker.work(with_scheduler=True)
