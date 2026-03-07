from typing import Optional, TypedDict

from app.models.article import Article, ArticleSection, FAQItem, LinkSet, Outline, SEOScore
from app.models.serp import ContentGap, SERPData


class SEOPipelineState(TypedDict):
    # --- Input fields (set at job creation, never mutated) ---
    job_id: str
    topic: str
    primary_keyword: str
    target_word_count: int
    language: str

    # --- Pipeline fields (filled node by node) ---
    serp_data: Optional[SERPData]
    content_gaps: Optional[list[ContentGap]]
    outline: Optional[Outline]
    draft_sections: Optional[list[ArticleSection]]
    links: Optional[LinkSet]
    faq: Optional[list[FAQItem]]
    seo_score: Optional[SEOScore]

    # --- Assembled output ---
    article: Optional[Article]   # populated after final scoring; passed to job_manager.save_result

    # --- Control fields ---
    revision_count: int          # incremented by revision_agent, capped at max_revision_count
    status: str                  # mirrors JobStatus, synced to job manager after each node
    error: Optional[str]         # set on node failure
