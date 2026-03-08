from typing import Literal, Optional

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


class CompetitorPage(BaseModel):
    url: str
    domain: str
    scraped: bool                    # False = fetch failed (blocked/timeout/JS-only)
    word_count: int = 0
    h2_headings: list[str] = []
    h3_headings: list[str] = []
    keyword_density: float = 0.0     # primary keyword occurrences / total words %
    has_table: bool = False
    has_numbered_list: bool = False
    has_code_block: bool = False
    readability_score: float = 0.0   # Flesch Reading Ease
    top_keywords: list[str] = []     # most frequent non-stopword terms


class CompetitorInsights(BaseModel):
    pages_attempted: int
    pages_scraped: int               # successfully parsed
    avg_word_count: int
    avg_h2_count: float
    suggested_section_count: int     # derived from avg_h2_count across scraped pages
    common_headings: list[str]       # headings appearing in 2+ results verbatim/near-verbatim
    structural_signals: list[str]    # e.g. "4/5 pages use numbered lists", "avg 1800 words"
    common_secondary_keywords: list[str]  # keywords frequent across multiple pages
    pages: list[CompetitorPage]


class ContentGap(BaseModel):
    topic: str
    reason: str
    priority: Literal["high", "medium", "low"]


class ContentBrief(BaseModel):
    format: Literal["tutorial", "comparison", "listicle", "explainer", "case_study"]
    audience: Literal["developer", "business", "beginner", "general"]
    required_elements: list[str]  # e.g. ["numbered_steps", "code_snippets", "comparison_table"]
    tone: Literal["technical", "conversational", "authoritative", "beginner_friendly"]
    rationale: str  # one sentence explaining why this format was chosen

    # SERP-derived structural intelligence — replaces static format_rules dict
    structural_patterns: list[str]  # e.g. "7/10 results use numbered H2 steps", "avg 6 H2 sections"
    competitive_angle: str          # what differentiated angle to take vs competitors
    writing_style_notes: str        # vocabulary level, sentence structure derived from snippets
    suggested_section_count: int    # derived from avg competitor section count
