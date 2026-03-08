import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import settings
from app.models.article import Article
from app.models.job import JobStatus
from app.models.request import GenerateRequest


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    topic = Column(String, nullable=False)
    primary_keyword = Column(String, nullable=False)
    target_word_count = Column(Integer, nullable=False)
    language = Column(String, nullable=False)
    thread_id = Column(String, nullable=False)  # == job_id, used as LangGraph thread_id
    error = Column(String, nullable=True)
    result = Column(Text, nullable=True)       # JSON-serialised Article
    pipeline_data = Column(Text, nullable=True) # JSON dict — intermediate node outputs
    history = Column(Text, nullable=True)       # JSON array of previous attempt snapshots
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
Base.metadata.create_all(engine)

# Additive migrations — safe to run on every startup
with engine.connect() as _conn:
    for _col, _type in [("pipeline_data", "TEXT"), ("history", "TEXT")]:
        try:
            _conn.execute(__import__("sqlalchemy").text(f"ALTER TABLE jobs ADD COLUMN {_col} {_type}"))
            _conn.commit()
            logger.info("Migration: added column jobs.%s", _col)
        except Exception:
            pass  # column already exists


def _extract_keyword_from_topic(topic: str) -> str:
    """Best-effort extraction of a short primary keyword from a long topic string.

    Strips leading ordinal words ("The 10 best", "Top 5"), trailing year/filler
    phrases ("in 2026", "you should know", "for beginners"), articles, and
    returns the remaining 2–5 word core noun phrase.

    Examples:
        "The 10 best AI video generators in 2026"  → "AI video generators"
        "How to write SEO content for beginners"   → "SEO content"
        "What is machine learning?"                → "machine learning"
    """
    text = topic.strip().rstrip("?!.")

    # Remove leading ranked-list patterns only when a number is involved
    # e.g. "The 10 best", "Top 5", "Best 10" → strip; "Best practices" → keep
    text = re.sub(
        r"^(?:the\s+)?\d+\s+(?:top|best|leading|greatest|worst)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:the\s+)?(?:top|best|leading|greatest|worst)\s+\d+\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Remove leading question/how-to stems ("How to", "What is", "Why does", "When to")
    text = re.sub(
        r"^(?:how\s+to|what\s+(?:is|are|does)|why\s+(?:is|are|does|do)|when\s+to|where\s+to)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Remove trailing year, filler, or audience qualifiers
    text = re.sub(
        r"\s+(?:in\s+\d{4}|for\s+\w+|you\s+should\s+\w+|to\s+\w+|that\s+\w+)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.strip()

    # Cap at 5 words; if still long take the first meaningful noun phrase chunk
    words = text.split()
    if len(words) > 5:
        # Drop leading articles/conjunctions from the remainder
        _SKIP = {"a", "an", "the", "and", "or", "of", "for", "with", "using"}
        words = [w for w in words if w.lower() not in _SKIP][:5]
    keyword = " ".join(words).strip()

    # Final safety: if we accidentally produced an empty string, fall back to topic
    return keyword if keyword else topic


class JobManager:
    def create_job(self, request: GenerateRequest) -> JobRecord:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        keyword = request.primary_keyword or _extract_keyword_from_topic(request.topic)
        job = JobRecord(
            id=job_id,
            status=JobStatus.PENDING,
            topic=request.topic,
            primary_keyword=keyword,
            target_word_count=request.target_word_count,
            language=request.language,
            thread_id=job_id,
            created_at=now,
            updated_at=now,
        )
        with Session(engine, expire_on_commit=False) as session:
            session.add(job)
            session.commit()
        return job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with Session(engine, expire_on_commit=False) as session:
            job = session.get(JobRecord, job_id)
            if job:
                session.expunge(job)
            return job

    def list_jobs(self) -> list[JobRecord]:
        with Session(engine, expire_on_commit=False) as session:
            jobs = (
                session.query(JobRecord)
                .order_by(JobRecord.created_at.desc())
                .all()
            )
            for job in jobs:
                session.expunge(job)
            return jobs

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        error: Optional[str] = None,
    ) -> None:
        with Session(engine) as session:
            job = session.get(JobRecord, job_id)
            if not job:
                logger.warning("update_status called for unknown job_id=%s", job_id)
                return
            job.status = status
            job.updated_at = datetime.now(timezone.utc)
            job.error = error  # None clears a previous error on retry
            session.commit()

    def save_pipeline_artifact(self, job_id: str, node: str, data: Any) -> None:
        """Merge `data` into the pipeline_data JSON blob under the key `node`.

        Called by each pipeline node to persist its intermediate output so the
        frontend can render a live inspection view of what each stage produced.
        """
        with Session(engine) as session:
            job = session.get(JobRecord, job_id)
            if not job:
                logger.warning("save_pipeline_artifact called for unknown job_id=%s", job_id)
                return
            current: dict = json.loads(job.pipeline_data) if job.pipeline_data else {}
            current[node] = data
            job.pipeline_data = json.dumps(current)
            job.updated_at = datetime.now(timezone.utc)
            session.commit()

    def save_to_history(self, job_id: str) -> None:
        """Snapshot the current result/error into the history array before a retry."""
        with Session(engine) as session:
            job = session.get(JobRecord, job_id)
            if not job:
                return
            existing: list = json.loads(job.history) if job.history else []
            entry = {
                "attempt": len(existing) + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": job.status,
                "error": job.error,
                "result": json.loads(job.result) if job.result else None,
            }
            existing.append(entry)
            job.history = json.dumps(existing)
            session.commit()

    def get_history(self, job_id: str) -> list:
        with Session(engine, expire_on_commit=False) as session:
            job = session.get(JobRecord, job_id)
            if not job or not job.history:
                return []
            return json.loads(job.history)

    def save_result(self, job_id: str, article: Article) -> None:
        with Session(engine) as session:
            job = session.get(JobRecord, job_id)
            if not job:
                logger.warning("save_result called for unknown job_id=%s", job_id)
                return
            job.result = article.model_dump_json()
            job.status = JobStatus.COMPLETED
            job.updated_at = datetime.now(timezone.utc)
            session.commit()


job_manager = JobManager()
