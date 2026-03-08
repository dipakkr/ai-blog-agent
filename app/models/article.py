from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class HeadingLevel(str, Enum):
    H1 = "h1"
    H2 = "h2"
    H3 = "h3"


class OutlineSection(BaseModel):
    heading: str
    level: HeadingLevel
    key_points: list[str]
    subsections: list["OutlineSection"] = []


OutlineSection.model_rebuild()


class Outline(BaseModel):
    title: str
    meta_description: str
    sections: list[OutlineSection]
    primary_keyword: str
    secondary_keywords: list[str]


class ArticleSection(BaseModel):
    heading: str
    level: HeadingLevel
    content: str
    word_count: int = Field(ge=0)


class InternalLink(BaseModel):
    anchor_text: str
    suggested_url: str
    domain: Optional[str] = None
    context: str


class ExternalLink(BaseModel):
    anchor_text: str
    url: str
    domain: str
    context: str


class LinkSet(BaseModel):
    internal: list[InternalLink]
    external: list[ExternalLink]


class FAQItem(BaseModel):
    question: str
    answer: str


class SEOCheckResult(BaseModel):
    check: str
    passed: bool
    points_earned: int
    points_possible: int
    detail: str


class SEOScore(BaseModel):
    total: float = Field(ge=0.0, le=100.0)  # 0–100
    checks: list[SEOCheckResult]
    passed: bool  # total >= threshold


class SecondaryKeywordUsage(BaseModel):
    keyword: str
    found: bool
    count: int


class KeywordAnalysis(BaseModel):
    primary_keyword: str
    primary_density: float  # percentage, e.g. 1.74
    primary_in_title: bool
    primary_in_intro: bool  # first 100 words
    primary_in_h2_headings: list[str]  # H2 headings that contain the keyword
    secondary_keywords: list[SecondaryKeywordUsage]


class SEOMetadata(BaseModel):
    title: str
    meta_description: str
    primary_keyword: str
    secondary_keywords: list[str]
    slug: str


class Article(BaseModel):
    metadata: SEOMetadata
    sections: list[ArticleSection]
    links: LinkSet
    faq: list[FAQItem]
    word_count: int = Field(ge=0)
    seo_score: Optional[SEOScore] = None
    keyword_analysis: Optional[KeywordAnalysis] = None
