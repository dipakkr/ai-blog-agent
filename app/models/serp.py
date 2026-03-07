from typing import Literal

from pydantic import BaseModel


class SERPResult(BaseModel):
    position: int
    title: str
    url: str
    snippet: str
    domain: str


class TopicTheme(BaseModel):
    theme: str
    frequency: int
    sources: list[str]


class SERPData(BaseModel):
    query: str
    results: list[SERPResult]
    people_also_ask: list[str]
    themes: list[TopicTheme]


class ContentGap(BaseModel):
    topic: str
    reason: str
    priority: Literal["high", "medium", "low"]
