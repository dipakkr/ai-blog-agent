import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

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
    result = Column(Text, nullable=True)  # JSON-serialised Article
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
Base.metadata.create_all(engine)


class JobManager:
    def create_job(self, request: GenerateRequest) -> JobRecord:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        job = JobRecord(
            id=job_id,
            status=JobStatus.PENDING,
            topic=request.topic,
            primary_keyword=request.primary_keyword or request.topic,
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
            if error is not None:
                job.error = error
            session.commit()

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
