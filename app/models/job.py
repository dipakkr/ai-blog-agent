from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from app.models.article import Article


class JobStatus(str, Enum):
    PENDING = "pending"
    RESEARCHING = "researching"
    OUTLINING = "outlining"
    DRAFTING = "drafting"
    SCORING = "scoring"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobDetailResponse(BaseModel):
    job_id: str
    status: JobStatus
    topic: str
    primary_keyword: str
    target_word_count: int
    language: str
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None
    result: Optional[Article] = None


class AttemptRecord(BaseModel):
    attempt: int
    timestamp: datetime
    status: str
    error: Optional[str] = None
    result: Optional[Article] = None
