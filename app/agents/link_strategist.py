"""
Node: link_strategist

Suggests internal and external links based on the article content and topic.
Runs as part of the DRAFTING phase.
"""

import logging

from app.models.article import ArticleSection, LinkSet
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an SEO link strategist. "
    "Suggest realistic internal links (to other pages on the same site) and "
    "authoritative external links (to reputable third-party sources). "
    "Internal links should use descriptive anchor text and plausible URL slugs. "
    "External links must point to credible domains relevant to the topic."
)


def _build_prompt(
    topic: str,
    primary_keyword: str,
    sections: list[ArticleSection],
) -> str:
    section_headings = "\n".join(f"- {s.heading}" for s in sections)
    # Provide first 300 words of the article as context
    article_excerpt = " ".join(
        s.content for s in sections
    )[:1200]

    return f"""Generate link suggestions for an article about "{topic}" (primary keyword: "{primary_keyword}").

Article sections:
{section_headings}

Article excerpt (first ~300 words):
{article_excerpt}

Requirements:
- Suggest at least 3 internal links to related pages on the same site (use relative URL slugs like /blog/related-topic)
- Suggest at least 2 external links to authoritative third-party sources
- Internal links must have fields: anchor_text, suggested_url (relative slug e.g. /blog/topic), domain (your site), context
- External links must have fields: anchor_text, url (full https URL), domain, context
- Anchor text must be natural — avoid exact-match keyword stuffing
- External domains should be credible (e.g. academic, government, well-known industry sites)"""


async def link_strategist(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    logger.info("[%s] link_strategist: generating link suggestions", job_id)

    try:
        prompt = _build_prompt(
            topic=state["topic"],
            primary_keyword=state["primary_keyword"],
            sections=state["draft_sections"] or [],
        )
        links: LinkSet = await llm_service.call_llm(
            prompt=prompt,
            system=SYSTEM,
            response_model=LinkSet,
            temperature=0.4,
            max_tokens=2048,
        )
        logger.info(
            "[%s] link_strategist: %d internal, %d external links",
            job_id, len(links.internal), len(links.external),
        )
        return {"links": links, "status": JobStatus.DRAFTING}

    except Exception as e:
        logger.exception("[%s] link_strategist failed", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "drafting_failed", "error": str(e)}
