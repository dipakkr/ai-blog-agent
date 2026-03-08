import re

import textstat

from app.models.article import ArticleSection, HeadingLevel

# Words too common to be meaningful keyword signals
_STOP_WORDS = frozenset({
    "a", "an", "the", "for", "in", "on", "at", "to", "of", "with", "by",
    "is", "are", "and", "or", "that", "this", "it", "its", "your", "my",
    "be", "been", "was", "were", "do", "does", "did", "has", "have", "had",
    "not", "but", "so", "if", "as", "from", "about", "into", "than",
})


def _keyword_core_words(keyword: str) -> list[str]:
    """Extract meaningful words from a keyword phrase, dropping stop words."""
    return [w for w in keyword.lower().split() if w not in _STOP_WORDS and len(w) > 1]


def _word_present(word: str, text_lower: str) -> bool:
    """Check if word appears in text, allowing plural/suffix forms.

    Uses word-boundary start so 'agent' matches 'agents' but not 'reagent'.
    """
    return bool(re.search(r"\b" + re.escape(word), text_lower))


def keyword_fuzzy_match(text: str, keyword: str, threshold: float = 0.75) -> bool:
    """Check if the core words of the keyword appear in text.

    Handles singular/plural naturally ('agent' matches 'agents').
    Returns True if >= threshold fraction of core keyword words are found.
    Used for title, heading, and intro checks where exact phrase match is
    too strict and causes keyword stuffing.
    """
    core = _keyword_core_words(keyword)
    if not core:
        return keyword.lower() in text.lower()
    text_lower = text.lower()
    found = sum(1 for w in core if _word_present(w, text_lower))
    return found / len(core) >= threshold


def keyword_density(text: str, keyword: str) -> float:
    """Return keyword density as a percentage, counting plural variations.

    Builds a regex where each keyword word allows an optional 's' suffix,
    so 'ai agent for content creation' also matches 'ai agents for content
    creation'. This prevents the article writer from forcing exact-match
    repetition to hit density targets.
    """
    if not text or not keyword:
        return 0.0
    total_words = len(text.split())
    if total_words == 0:
        return 0.0
    words = keyword.lower().split()
    pattern = r"\b" + r"\s+".join(re.escape(w) + r"s?" for w in words) + r"\b"
    count = len(re.findall(pattern, text.lower()))
    keyword_words = len(words)
    return round((count * keyword_words / total_words) * 100, 2)


def keyword_in_first_n_words(text: str, keyword: str, n: int = 100) -> bool:
    """Return True if keyword (or close variation) appears in the first n words."""
    first_n = " ".join(text.split()[:n])
    return keyword_fuzzy_match(first_n, keyword)


def keyword_in_headings(sections: list[ArticleSection], keyword: str) -> bool:
    """Return True if keyword (or close variation) appears in at least one H2."""
    return any(
        s.level == HeadingLevel.H2 and keyword_fuzzy_match(s.heading, keyword)
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
