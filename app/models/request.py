from typing import Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    target_word_count: int = Field(default=1500, ge=500, le=10000)
    language: str = Field(default="en", max_length=10)
    primary_keyword: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Primary keyword to target. Defaults to topic if not provided.",
    )
