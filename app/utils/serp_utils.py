"""
Pre-processing utilities for SERP/competitor data.

These are deterministic code functions — no LLM calls. They clean, extract,
and compute values that the content_classifier and outline_generator consume.
"""

import re
from typing import Optional, Tuple

from app.models.serp import CompetitorInsights

# ---------------------------------------------------------------------------
# Heading cleaner — removes nav/sidebar/footer/UI artifacts from scraped H2s
# ---------------------------------------------------------------------------

_NAV_HEADING_RE = re.compile(
    r"^("
    r"get in touch|contact us?|follow us?|subscribe|sign up|newsletter|"
    r"top posts?|popular posts?|recent posts?|related posts?|you (may|might) also|"
    r"never miss|about us?|our services?|meet the team|leave a (comment|reply)|"
    r"share this|tags?|categories|archives?|search|menu|navigation|"
    r"comments?|pingback|trackback|\d+\s*(comments?|replies|responses)|"
    r"written by|author bio|the final|keep reading|read more|see also|"
    r"sponsored|advertisement|disclosure|affiliate|"
    r"from the (blog|podcast)|listen to|watch (the|our)|"
    r"what (our|customers) (say|think)|testimonials?"
    r")",
    re.IGNORECASE,
)

_UI_ARTIFACT_RE = re.compile(
    r"^("
    r"score:?\s*\d|"
    r"(standout|key)\s+(strength|feature|benefit)|"
    r"trade.?off|"
    r"pros?\s*(and|&)\s*cons?|"
    r"pricing|plans?\s*(and|&)|"
    r"(our|editor).*(pick|choice|rating|score|verdict)|"
    r"rating|review|verdict|"
    r"(read|full)\s*(review|more)|"
    r"visit\s*(site|website)|"
    r"view\s*(deal|offer)|"
    r"\d+(\.\d+)?\s*/\s*\d+|"
    r"(starting|from)\s*\$|"
    r"free\s*(plan|tier|trial)"
    r")",
    re.IGNORECASE,
)


def clean_competitor_headings(headings: list[str]) -> list[str]:
    """Remove nav, sidebar, footer, and UI artifact headings from scraped data.

    Returns only genuine content headings suitable for structural analysis.
    """
    cleaned = []
    for h in headings:
        h_stripped = h.strip()
        if len(h_stripped) <= 2:
            continue
        if h_stripped.replace(".", "").replace(",", "").isdigit():
            continue
        if _NAV_HEADING_RE.match(h_stripped):
            continue
        if _UI_ARTIFACT_RE.match(h_stripped):
            continue
        if len(h_stripped) > 80:  # overly long headings are usually scraped noise
            continue
        cleaned.append(h_stripped)
    return cleaned


# ---------------------------------------------------------------------------
# Tool/product name extraction — deterministic, from competitor data
# ---------------------------------------------------------------------------

_GENERIC_HEADINGS = frozenset({
    "introduction", "conclusion", "overview", "summary", "faq",
    "what is", "how to", "pricing", "comparison", "benefits",
    "features", "pros", "cons", "review", "final thoughts",
    "key takeaways", "getting started", "quick overview",
})


def extract_tool_names(insights: CompetitorInsights) -> list[str]:
    """Extract unique tool/product/brand names from competitor data.

    Uses top_entities first (from entity extraction), then falls back to
    scanning H2 headings for specific named items. Returns deduplicated list.
    """
    # Start with pre-extracted entities (already ranked by frequency)
    entities = list(insights.top_entities or [])

    # Supplement from H2 headings if entities are sparse
    if len(entities) < 5:
        seen_lower: set[str] = {e.lower() for e in entities}
        for page in insights.pages:
            if not page.scraped:
                continue
            for h in page.h2_headings:
                h_clean = h.strip()
                h_lower = h_clean.lower()
                if (
                    h_lower not in seen_lower
                    and not any(g in h_lower for g in _GENERIC_HEADINGS)
                    and not _NAV_HEADING_RE.match(h_clean)
                    and not _UI_ARTIFACT_RE.match(h_clean)
                    and 3 <= len(h_clean) <= 60
                ):
                    seen_lower.add(h_lower)
                    entities.append(h_clean)

    # Final cleanup
    return [
        e for e in entities
        if len(e) > 2
        and not _UI_ARTIFACT_RE.match(e.strip())
        and not e.strip().replace(".", "").replace(",", "").isdigit()
    ]


# ---------------------------------------------------------------------------
# Section count recommendation — explicit math, not LLM guessing
# ---------------------------------------------------------------------------

def recommend_section_count(
    target_word_count: int,
    avg_competitor_h2: float,
    content_format: str,
    topic_item_count: Optional[int] = None,
) -> Tuple[int, str]:
    """Compute recommended H2 section count with explicit reasoning.

    Returns (count, rationale_string) so the outline prompt can show its math.

    Rules:
    - If topic specifies an exact number (e.g. "8 AI Agents"), use that.
    - Otherwise, target ~200-250 words per H2 section.
    - Anchor to competitor avg but don't exceed what our word budget supports.
    - Tutorials: fewer, longer sections (250-300 words each).
    - Listicles: one H2 per item, may be shorter (~150-200 words each).
    """
    if topic_item_count:
        return (
            topic_item_count,
            f"Topic promises exactly {topic_item_count} items → {topic_item_count} H2 sections.",
        )

    # Words-per-section targets by format
    if content_format == "tutorial":
        words_per_section = 275
    elif content_format == "listicle":
        words_per_section = 175
    elif content_format == "comparison":
        words_per_section = 225
    else:
        words_per_section = 225

    # Calculate from word budget
    budget_sections = max(3, target_word_count // words_per_section)

    # Anchor to competitor avg if available
    if avg_competitor_h2 > 0:
        competitor_sections = round(avg_competitor_h2)
        # Blend: 60% budget, 40% competitor
        blended = round(0.6 * budget_sections + 0.4 * competitor_sections)
        count = max(3, min(15, blended))
        rationale = (
            f"{target_word_count} words ÷ {words_per_section} words/section = {budget_sections} sections. "
            f"Competitor avg: {avg_competitor_h2:.1f} H2s. "
            f"Blended recommendation: {count} sections."
        )
    else:
        count = max(3, min(15, budget_sections))
        rationale = (
            f"{target_word_count} words ÷ {words_per_section} words/section = {count} sections."
        )

    return (count, rationale)


# ---------------------------------------------------------------------------
# Search intent detection — deterministic from topic + SERP signals
# ---------------------------------------------------------------------------

_TRANSACTIONAL_RE = re.compile(
    r"\b(buy|purchase|pricing|discount|coupon|deal|cheap|order|subscribe)\b",
    re.IGNORECASE,
)
_NAVIGATIONAL_RE = re.compile(
    r"\b(login|sign\s*in|official|download|homepage)\b",
    re.IGNORECASE,
)
_COMMERCIAL_RE = re.compile(
    r"\b(best|top|vs\.?|versus|review|comparison|alternative|compared?)\b",
    re.IGNORECASE,
)


def detect_search_intent(topic: str) -> str:
    """Classify search intent from topic text.

    Returns one of: informational, commercial_investigation, transactional, navigational.
    """
    if _TRANSACTIONAL_RE.search(topic):
        return "transactional"
    if _NAVIGATIONAL_RE.search(topic):
        return "navigational"
    if _COMMERCIAL_RE.search(topic):
        return "commercial_investigation"
    return "informational"
