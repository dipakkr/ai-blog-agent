import re


def count_words(text: str) -> int:
    """Count words in text, stripping HTML tags first."""
    clean = re.sub(r"<[^>]+>", " ", text)
    return len(clean.split())


def clean_text(text: str) -> str:
    """Strip HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def estimate_tokens(text: str) -> int:
    """Rough token estimate — 1 token ≈ 4 characters."""
    return max(1, len(text) // 4)


def section_max_tokens(target_words: int) -> int:
    """Convert a target word count to a safe max_tokens budget for LLM calls."""
    # ~1.5 tokens per word, plus 20 % headroom
    return min(8192, max(1024, int(target_words * 1.5 * 1.2)))
