import asyncio
import logging
import re
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models.serp import SERPData, SERPResult, TopicTheme

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"

# Retry config
_MAX_ATTEMPTS = 3
_BASE_DELAY = 1.0  # seconds; doubles each attempt (1s → 2s → 4s)

# HTTP status codes worth retrying
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


class SERPService:
    async def search(self, query: str) -> SERPData:
        """Fetch top 10 SERP results for query.

        Retries up to 3 times with exponential backoff on transient errors
        (timeouts, connection drops, 429 rate-limits, 5xx server errors).
        Non-retryable errors (e.g. 401 bad key, 400 bad request) raise immediately.

        Raises:
            RuntimeError: SERPAPI_KEY is not configured.
            httpx.HTTPStatusError: Non-retryable API error (4xx).
            httpx.HTTPStatusError / httpx.TimeoutException: All retries exhausted.
        """
        if not settings.serpapi_key:
            raise RuntimeError(
                "SERPAPI_KEY is not configured. Add it to .env to run the pipeline. "
                "Use serp_service.mock_search() in tests."
            )
        return await self._search_with_retry(query)

    async def _search_with_retry(self, query: str) -> SERPData:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await self._fetch(query)
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                if attempt < _MAX_ATTEMPTS:
                    delay = _BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "SerpAPI attempt %d/%d failed (%s) — retrying in %.1fs",
                        attempt,
                        _MAX_ATTEMPTS,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "SerpAPI failed after %d attempts — last error: %s",
                        _MAX_ATTEMPTS,
                        exc,
                    )
        raise last_exc  # type: ignore[misc]

    async def _fetch(self, query: str) -> SERPData:
        params = {
            "q": query,
            "api_key": settings.serpapi_key,
            "engine": "google",
            "num": 10,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(SERPAPI_URL, params=params)
            response.raise_for_status()
            data = response.json()

        results = [
            SERPResult(
                position=r.get("position", i + 1),
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
                domain=_extract_domain(r.get("link", "")),
            )
            for i, r in enumerate(data.get("organic_results", [])[:10])
        ]

        people_also_ask = [
            item.get("question", "")
            for item in data.get("related_questions", [])
            if item.get("question")
        ]

        return SERPData(
            query=query,
            results=results,
            people_also_ask=people_also_ask,
            themes=_extract_themes(results),
        )

    async def mock_search(self, query: str) -> SERPData:
        """Return realistic mock SERP data. Use only in tests and local dev."""
        slug = query.lower().replace(" ", "-")
        title = query.title()

        entries = [
            ("The Complete Guide to",   "2025 Edition",              "neilpatel.com"),
            ("How to Master",           "Step-by-Step Tutorial",     "backlinko.com"),
            ("Top 10 Tips for",         "Expert Advice",             "ahrefs.com"),
            ("Ultimate Guide:",         "Everything You Need",       "semrush.com"),
            ("Best Practices for",      "What the Pros Do",          "moz.com"),
            ("Getting Started with",    "Beginner's Handbook",       "hubspot.com"),
            ("Advanced Strategies for", "Pro-Level Techniques",      "searchenginejournal.com"),
            ("Why",                     "Matters More Than Ever",    "searchengineland.com"),
            ("Common Mistakes in",      "And How to Fix Them",       "wordstream.com"),
            ("The Future of",           "Trends & Predictions 2025", "contentmarketinginstitute.com"),
        ]

        results = [
            SERPResult(
                position=i + 1,
                title=f"{prefix} {title} — {suffix}",
                url=f"https://{domain}/blog/{slug}",
                snippet=(
                    f"A comprehensive resource on {query}. "
                    f"Covers key concepts, proven strategies, and actionable tips "
                    f"to help you get results faster."
                ),
                domain=domain,
            )
            for i, (prefix, suffix, domain) in enumerate(entries)
        ]

        people_also_ask = [
            f"What is {query}?",
            f"How do I get started with {query}?",
            f"What are the benefits of {query}?",
            f"What are the most common mistakes in {query}?",
            f"How long does it take to see results with {query}?",
        ]

        themes = [
            TopicTheme(
                theme="Best practices and proven strategies",
                frequency=7,
                sources=["neilpatel.com", "backlinko.com", "ahrefs.com"],
            ),
            TopicTheme(
                theme="Beginner guides and getting started",
                frequency=5,
                sources=["hubspot.com", "moz.com", "semrush.com"],
            ),
            TopicTheme(
                theme="Tools and software recommendations",
                frequency=4,
                sources=["ahrefs.com", "semrush.com", "moz.com"],
            ),
            TopicTheme(
                theme="Common mistakes to avoid",
                frequency=3,
                sources=["backlinko.com", "searchengineland.com"],
            ),
            TopicTheme(
                theme="Advanced techniques and optimisation",
                frequency=3,
                sources=["searchenginejournal.com", "wordstream.com"],
            ),
        ]

        return SERPData(
            query=query,
            results=results,
            people_also_ask=people_also_ask,
            themes=themes,
        )


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return ""


def _extract_themes(results: list[SERPResult]) -> list[TopicTheme]:
    """Detect content angles that dominate the SERP for the given query.

    Rather than generic keyword buckets, each pattern targets a real content
    angle that the gap-analyzer can reason about when looking for what's missing.
    """
    angle_patterns: list[tuple[str, str]] = [
        (r"\b(top|best|leading|greatest)\s+\d+\b|\blist\b",
         "Ranked / curated lists"),
        (r"\b(step.by.step|how.to|tutorial|walkthrough|guide|instructions)\b",
         "Step-by-step tutorials and how-to guides"),
        (r"\b(comparison|vs\.?|versus|compared(?:\sto)?|alternatives?|difference)\b",
         "Comparisons and alternatives"),
        (r"\b(beginner|starter|introduction|getting.started|basics|101|newbie)\b",
         "Beginner and introductory content"),
        (r"\b(review|reviewed|tested|hands.on|tried|rated|rating|verdict)\b",
         "Reviews and hands-on testing"),
        (r"\b(pric(?:e|ing|es)|cost|cheap|affordable|free\s+plan|paid|budget)\b",
         "Pricing and cost comparisons"),
        (r"\b(advanced|expert|professional|enterprise|in.depth|deep.dive|technical)\b",
         "Advanced and expert-level content"),
        (r"\b(trend|future|2024|2025|2026|latest|new|update|upcoming|modern)\b",
         "Trends and up-to-date coverage"),
        (r"\b(example|case.study|real.world|use.case|success.story|scenario)\b",
         "Real-world examples and case studies"),
        (r"\b(mistake|error|pitfall|avoid|wrong|problem|fix|issue|troubleshoot)\b",
         "Common mistakes and troubleshooting"),
    ]

    themes: list[TopicTheme] = []
    for pattern, theme_name in angle_patterns:
        matching_sources: list[str] = []
        for result in results:
            text = f"{result.title} {result.snippet}".lower()
            if re.search(pattern, text) and result.domain not in matching_sources:
                matching_sources.append(result.domain)
        if matching_sources:
            themes.append(TopicTheme(
                theme=theme_name,
                frequency=len(matching_sources),
                sources=matching_sources,
            ))

    themes.sort(key=lambda t: -t.frequency)
    return themes


serp_service = SERPService()
