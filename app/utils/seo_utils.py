import re

import textstat

from app.models.article import ArticleSection, HeadingLevel


def keyword_density(text: str, keyword: str) -> float:
    """Return keyword density as a percentage of total words.

    Multi-word keywords are counted as phrase occurrences.
    """
    if not text or not keyword:
        return 0.0
    total_words = len(text.split())
    if total_words == 0:
        return 0.0
    count = len(re.findall(re.escape(keyword.lower()), text.lower()))
    keyword_words = len(keyword.split())
    return round((count * keyword_words / total_words) * 100, 2)


def keyword_in_first_n_words(text: str, keyword: str, n: int = 100) -> bool:
    """Return True if keyword appears in the first n words of text."""
    first_n = " ".join(text.split()[:n]).lower()
    return keyword.lower() in first_n


def keyword_in_headings(sections: list[ArticleSection], keyword: str) -> bool:
    """Return True if keyword appears in at least one H2 heading."""
    kw = keyword.lower()
    return any(
        s.level == HeadingLevel.H2 and kw in s.heading.lower()
        for s in sections
    )


def heading_hierarchy_valid(sections: list[ArticleSection]) -> bool:
    """Return True if heading hierarchy is valid.

    Rules (title is the implicit H1):
    - No H1 should appear in the sections list (title owns H1)
    - No H3 before any H2
    """
    seen_h2 = False
    for section in sections:
        if section.level == HeadingLevel.H1:
            return False  # H1 belongs to the title, not sections
        if section.level == HeadingLevel.H3 and not seen_h2:
            return False
        if section.level == HeadingLevel.H2:
            seen_h2 = True
    return True


def flesch_reading_ease(text: str) -> float:
    """Return the Flesch Reading Ease score (0–100, higher = more readable)."""
    return textstat.flesch_reading_ease(text)


def meta_description_length_ok(meta: str) -> bool:
    """Return True if meta description is 150–160 characters."""
    return 150 <= len(meta) <= 160
