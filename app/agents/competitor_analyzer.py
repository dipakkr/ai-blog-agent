"""
Node: competitor_analyzer

Fetches and parses the actual HTML of top competitor pages from SERP results.
Sits between serp_analyzer and content_classifier so every downstream node
gets real structural data — heading counts, word counts, content elements —
rather than guessing from snippet text alone.

Failures are non-fatal: if all pages are blocked/JS-rendered, the node records
scraped=0 and the pipeline continues with snippet-only analysis.
"""

import logging

from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.scraper_service import scraper_service

logger = logging.getLogger(__name__)


async def competitor_analyzer(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    serp_data = state.get("serp_data")

    if not serp_data or not serp_data.results:
        logger.warning("[%s] competitor_analyzer: no SERP results to scrape", job_id)
        return {"competitor_insights": None, "status": JobStatus.RESEARCHING}

    logger.info(
        "[%s] competitor_analyzer: scraping top %d competitor pages",
        job_id, min(5, len(serp_data.results)),
    )

    try:
        insights = await scraper_service.scrape_competitors(
            results=serp_data.results,
            primary_keyword=state["primary_keyword"],
            max_pages=5,
        )

        logger.info(
            "[%s] competitor_analyzer: %d/%d scraped — avg %d words, %d common headings, "
            "%d secondary keywords, %d entities extracted",
            job_id,
            insights.pages_scraped,
            insights.pages_attempted,
            insights.avg_word_count,
            len(insights.common_headings),
            len(insights.common_secondary_keywords),
            len(insights.top_entities),
        )

        # Persist as pipeline artifact so the frontend can inspect it
        job_manager.save_pipeline_artifact(job_id, "competitor_insights", {
            "pages_attempted": insights.pages_attempted,
            "pages_scraped": insights.pages_scraped,
            "avg_word_count": insights.avg_word_count,
            "avg_h2_count": insights.avg_h2_count,
            "suggested_section_count": insights.suggested_section_count,
            "common_headings": insights.common_headings,
            "structural_signals": insights.structural_signals,
            "common_secondary_keywords": insights.common_secondary_keywords,
            "top_entities": insights.top_entities,
            "pages": [
                {
                    "url": p.url,
                    "domain": p.domain,
                    "scraped": p.scraped,
                    "word_count": p.word_count,
                    "h2_headings": p.h2_headings,
                    "h3_headings": p.h3_headings,
                    "keyword_density": p.keyword_density,
                    "has_table": p.has_table,
                    "has_numbered_list": p.has_numbered_list,
                    "has_code_block": p.has_code_block,
                    "readability_score": p.readability_score,
                    "top_keywords": p.top_keywords,
                }
                for p in insights.pages
            ],
        })

        return {
            "competitor_insights": insights,
            "status": JobStatus.RESEARCHING,
        }

    except Exception as e:
        # Non-fatal — pipeline continues without competitor data
        logger.exception("[%s] competitor_analyzer failed — continuing without scrape data", job_id)
        return {"competitor_insights": None, "status": JobStatus.RESEARCHING}
