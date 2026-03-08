"""
Competitor page scraper.

Fetches and parses the HTML of competitor URLs from SERP data to extract
real structural signals: heading hierarchy, word count, keyword density,
content elements (tables, numbered lists, code blocks), and top keywords.

Design decisions:
- Static HTML only — no JS rendering. Pages that require JS return empty
  body text and are marked scraped=False.
- 12s timeout per page. Slow pages are skipped, not retried.
- Concurrency capped at 5 simultaneous fetches to avoid hammering servers.
- Failures (403, 429, timeout, empty body) are caught and recorded as
  scraped=False so the pipeline degrades gracefully rather than failing.
"""

import asyncio
import logging
import re
from collections import Counter
from typing import Optional

import httpx
import textstat
from bs4 import BeautifulSoup

from app.models.serp import CompetitorInsights, CompetitorPage, SERPResult

logger = logging.getLogger(__name__)

_TIMEOUT = 12.0
_MAX_CONCURRENT = 5
_MIN_BODY_WORDS = 100  # pages with fewer words are treated as JS-rendered / paywalled

# Headings that are clearly navigation/sidebar/footer elements — not article content.
# Matched against the start of the heading text (case-insensitive).
_NAV_HEADING_RE = re.compile(
    r"^("
    r"get in touch|contact us?|follow us?|subscribe|sign up|newsletter|"
    r"top posts?|popular posts?|recent posts?|related posts?|you (may |might )?also|"
    r"never miss|about us?|our services?|meet the team|leave a (comment|reply)|"
    r"share this|tags?|categories|archives?|search|menu|navigation|"
    r"comments?|pingback|trackback|\d+\s*(comments?|replies|response)|"
    r"written by|author|bio|the final|keep reading|read more|see also|"
    r"sponsored|advertisement|disclosure|affiliate"
    r")",
    re.IGNORECASE,
)

# Browser-like User-Agent to reduce bot blocking
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Common English stopwords to exclude from keyword frequency
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "was", "are", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "dare",
    "this", "that", "these", "those", "it", "its", "they", "their", "them",
    "we", "our", "you", "your", "he", "she", "his", "her", "i", "my",
    "not", "no", "so", "if", "as", "up", "out", "about", "into", "than",
    "then", "when", "where", "who", "which", "what", "how", "all", "each",
    "more", "most", "also", "just", "like", "use", "used", "using", "get",
    "one", "two", "three", "new", "make", "way", "s", "t", "re", "ll",
}


def _find_content_area(soup: BeautifulSoup) -> BeautifulSoup:
    """Return the main article content element, falling back to the full soup.

    Most CMS pages wrap the article body in <article>, <main>, or a well-known
    class. Isolating this before extracting headings prevents sidebar widgets,
    newsletter sign-ups, and footer navigation from polluting the H2 list.
    """
    # Ordered by specificity — most reliable selectors first
    for selector in [
        "article",
        "main",
        "[role='main']",
        ".post-content",
        ".entry-content",
        ".article-content",
        ".article-body",
        ".post-body",
        ".content-area",
        "#content",
        "#main-content",
        "#article-body",
    ]:
        element = soup.select_one(selector)
        if element:
            return element  # type: ignore[return-value]
    return soup


def _clean_text(soup: BeautifulSoup) -> str:
    """Remove script/style/nav/footer then return visible text."""
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                     "form", "noscript", "iframe", "svg"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def _extract_headings(soup: BeautifulSoup, tag: str) -> list[str]:
    """Extract headings, filtering out navigation/sidebar noise."""
    raw = [h.get_text(strip=True) for h in soup.find_all(tag) if h.get_text(strip=True)]
    # Remove known nav/sidebar/footer heading patterns
    filtered = [h for h in raw if not _NAV_HEADING_RE.match(h)]
    # Also drop very long headings (>100 chars) — likely pulled from body copy, not headings
    filtered = [h for h in filtered if len(h) <= 100]
    return filtered


def _top_keywords(text: str, n: int = 15) -> list[str]:
    """Return top-N frequent non-stopword tokens (≥4 chars)."""
    tokens = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
    filtered = [t for t in tokens if t not in _STOPWORDS]
    return [word for word, _ in Counter(filtered).most_common(n)]


def _keyword_density(text: str, keyword: str) -> float:
    words = text.lower().split()
    if not words:
        return 0.0
    kw = keyword.lower()
    count = sum(1 for w in words if kw in w)
    return round((count / len(words)) * 100, 2)


def _parse_page(url: str, domain: str, html: str, primary_keyword: str) -> CompetitorPage:
    soup = BeautifulSoup(html, "lxml")
    body_text = _clean_text(soup)  # strips nav/footer/aside in-place on soup
    word_count = len(body_text.split())

    if word_count < _MIN_BODY_WORDS:
        # Likely JS-rendered, paywalled, or redirect landing page
        return CompetitorPage(url=url, domain=domain, scraped=False)

    # Extract headings from the isolated article content area only — prevents
    # sidebar widgets ("Top Posts", "Get in Touch", "Never Miss an Update")
    # from polluting the H2 list.
    content_area = _find_content_area(soup)
    h2 = _extract_headings(content_area, "h2")
    h3 = _extract_headings(content_area, "h3")

    has_table = bool(content_area.find("table"))
    has_numbered_list = bool(content_area.find("ol"))
    has_code_block = bool(content_area.find(["code", "pre"]))

    try:
        readability = textstat.flesch_reading_ease(body_text)
    except Exception:
        readability = 0.0

    return CompetitorPage(
        url=url,
        domain=domain,
        scraped=True,
        word_count=word_count,
        h2_headings=h2,
        h3_headings=h3,
        keyword_density=_keyword_density(body_text, primary_keyword),
        has_table=has_table,
        has_numbered_list=has_numbered_list,
        has_code_block=has_code_block,
        readability_score=round(readability, 1),
        top_keywords=_top_keywords(body_text),
    )


async def _fetch_page(
    client: httpx.AsyncClient,
    result: SERPResult,
    primary_keyword: str,
) -> CompetitorPage:
    try:
        response = await client.get(result.url, follow_redirects=True)
        response.raise_for_status()
        return _parse_page(result.url, result.domain, response.text, primary_keyword)
    except Exception as exc:
        logger.debug("Scraper: failed to fetch %s — %s", result.url, exc)
        return CompetitorPage(url=result.url, domain=result.domain, scraped=False)


def _aggregate(pages: list[CompetitorPage], primary_keyword: str) -> CompetitorInsights:
    scraped = [p for p in pages if p.scraped]
    n = len(scraped)

    if n == 0:
        return CompetitorInsights(
            pages_attempted=len(pages),
            pages_scraped=0,
            avg_word_count=0,
            avg_h2_count=0,
            suggested_section_count=6,
            common_headings=[],
            structural_signals=["No pages could be scraped — using SERP snippets only"],
            common_secondary_keywords=[],
            pages=pages,
        )

    avg_word_count = int(sum(p.word_count for p in scraped) / n)
    avg_h2 = sum(len(p.h2_headings) for p in scraped) / n
    suggested_sections = max(4, min(10, round(avg_h2)))

    # Headings appearing in 2+ results (case-insensitive, first 60 chars)
    heading_counter: Counter = Counter()
    for p in scraped:
        for h in p.h2_headings:
            heading_counter[h.lower()[:60]] += 1
    common_headings = [h for h, count in heading_counter.most_common(10) if count >= 2]

    # Cross-page keyword frequency
    all_keywords: list[str] = []
    for p in scraped:
        all_keywords.extend(p.top_keywords)
    keyword_counter: Counter = Counter(all_keywords)
    # exclude the primary keyword itself from secondary suggestions
    pk_lower = primary_keyword.lower()
    common_secondary = [
        kw for kw, _ in keyword_counter.most_common(20)
        if pk_lower not in kw and len(kw) > 3
    ][:10]

    # Structural signals derived from real page data
    signals: list[str] = [
        f"{n}/{len(pages)} competitor pages successfully scraped",
        f"Average word count: {avg_word_count} words",
        f"Average H2 sections: {avg_h2:.1f} per page",
    ]
    table_count = sum(1 for p in scraped if p.has_table)
    list_count = sum(1 for p in scraped if p.has_numbered_list)
    code_count = sum(1 for p in scraped if p.has_code_block)
    if table_count:
        signals.append(f"{table_count}/{n} pages use comparison tables")
    if list_count:
        signals.append(f"{list_count}/{n} pages use numbered lists")
    if code_count:
        signals.append(f"{code_count}/{n} pages include code blocks")

    avg_readability = sum(p.readability_score for p in scraped) / n
    signals.append(f"Average Flesch readability: {avg_readability:.0f}/100")

    # Word count range signal
    wc_values = [p.word_count for p in scraped]
    signals.append(f"Word count range: {min(wc_values)}–{max(wc_values)} words")

    return CompetitorInsights(
        pages_attempted=len(pages),
        pages_scraped=n,
        avg_word_count=avg_word_count,
        avg_h2_count=round(avg_h2, 1),
        suggested_section_count=suggested_sections,
        common_headings=common_headings,
        structural_signals=signals,
        common_secondary_keywords=common_secondary,
        pages=pages,
    )


class ScraperService:
    async def scrape_competitors(
        self,
        results: list[SERPResult],
        primary_keyword: str,
        max_pages: int = 5,
    ) -> CompetitorInsights:
        """Fetch and parse up to `max_pages` competitor URLs concurrently.

        Returns CompetitorInsights with aggregated structural patterns.
        Always succeeds — individual page failures are recorded as scraped=False.
        """
        targets = results[:max_pages]
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _bounded_fetch(result: SERPResult) -> CompetitorPage:
            async with semaphore:
                return await _fetch_page(client, result, primary_keyword)

        async with httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT) as client:
            pages = await asyncio.gather(*[_bounded_fetch(r) for r in targets])

        insights = _aggregate(list(pages), primary_keyword)
        scraped_count = sum(1 for p in pages if p.scraped)
        logger.info(
            "Scraper: %d/%d pages parsed — avg %d words, avg %.1f H2s",
            scraped_count, len(targets),
            insights.avg_word_count, insights.avg_h2_count,
        )
        return insights


scraper_service = ScraperService()
