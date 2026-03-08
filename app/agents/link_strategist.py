"""
Node: link_strategist

Generates internal and external link suggestions, then injects them as
markdown hyperlinks directly into the draft section content.

Internal links:  [anchor text](/blog/slug)
External links:  [anchor text](https://example.com/page)

Each anchor text is matched case-insensitively in the section content and
replaced with a markdown link on its first unlinked occurrence only.
Already-linked text (inside existing [](...) spans) is never double-linked.
"""

import logging
import re

from app.models.article import ArticleSection, LinkSet
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service
from app.utils.text_utils import count_words

logger = logging.getLogger(__name__)

# Matches any existing markdown link so we can skip already-linked spans
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")

SYSTEM = (
    "You are an SEO link strategist. "
    "Suggest realistic internal links (to other pages on the same site) and "
    "authoritative external links (to reputable third-party sources). "
    "Anchor text must appear verbatim in the article content — choose phrases "
    "that are already present in the text. "
    "Internal links should use descriptive anchor text and plausible URL slugs. "
    "External links must point to credible, real domains relevant to the topic."
)


def _build_prompt(
    topic: str,
    primary_keyword: str,
    sections: list[ArticleSection],
) -> str:
    section_headings = "\n".join(f"- {s.heading}" for s in sections)
    # Provide full article content (up to 4000 chars) so the LLM can pick
    # anchor text that actually appears verbatim in the text
    article_excerpt = " ".join(s.content for s in sections)[:4000]

    return f"""Generate link suggestions for an article about "{topic}" (primary keyword: "{primary_keyword}").

Article sections:
{section_headings}

Article content (use this to choose anchor text that appears verbatim in the text):
{article_excerpt}

Requirements:
- Suggest at least 3 internal links to related pages on the same site (relative slugs like /blog/related-topic)
- Suggest at least 2 external links to authoritative third-party sources
- CRITICAL: anchor_text must be a phrase that appears VERBATIM in the article content above
- Internal links: anchor_text, suggested_url (relative slug), domain (your site), context (which section)
- External links: anchor_text, url (full https URL), domain, context (which section)
- Anchor text must be natural — 2–5 words, no exact-match keyword stuffing
- External domains: credible sources (official docs, well-known industry sites, academic/government)"""


def _strip_existing_links(text: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of already-linked text to avoid double-linking."""
    return [(m.start(), m.end()) for m in _MD_LINK_RE.finditer(text)]


def _inject_link(content: str, anchor: str, url: str) -> str:
    """Replace the first unlinked occurrence of anchor (case-insensitive) with [anchor](url).

    Skips occurrences that are already inside a markdown link span.
    """
    linked_spans = _strip_existing_links(content)
    pattern = re.compile(re.escape(anchor), re.IGNORECASE)

    for match in pattern.finditer(content):
        start, end = match.start(), match.end()
        # Skip if this match falls inside an existing [](...) link
        inside_existing = any(ls <= start and end <= le for ls, le in linked_spans)
        if inside_existing:
            continue
        # Replace this occurrence only
        original = content[start:end]  # preserve original casing
        return content[:start] + f"[{original}]({url})" + content[end:]

    return content  # anchor not found — leave content unchanged


def _inject_links_into_sections(
    sections: list[ArticleSection],
    links: LinkSet,
) -> list[ArticleSection]:
    """Inject all links from LinkSet into the section content as markdown hyperlinks.

    Strategy:
    - For each link, find the section whose heading most closely matches the
      link's context field, then try injecting there first.
    - If the anchor text isn't in that section, fall back to searching all sections.
    - Each anchor is injected at most once across the entire article.
    """
    # Work on mutable copies of content
    contents = [s.content for s in sections]
    headings_lower = [s.heading.lower() for s in sections]

    def _best_section_index(context: str) -> int:
        """Return the index of the section best matching the context string."""
        ctx = context.lower()
        for i, h in enumerate(headings_lower):
            if any(word in h for word in ctx.split() if len(word) > 3):
                return i
        return 0  # default to first section

    all_links: list[tuple[str, str, str, str]] = []  # (type, anchor, url, context)
    for link in links.internal:
        all_links.append(("internal", link.anchor_text, link.suggested_url, link.context))
    for link in links.external:
        all_links.append(("external", link.anchor_text, link.url, link.context))

    for link_type, anchor, url, context in all_links:
        best_idx = _best_section_index(context)
        # Try preferred section first, then all sections in order
        order = [best_idx] + [i for i in range(len(contents)) if i != best_idx]
        injected = False
        for idx in order:
            new_content = _inject_link(contents[idx], anchor, url)
            if new_content != contents[idx]:
                contents[idx] = new_content
                injected = True
                break
        if not injected:
            logger.debug(
                "link_strategist: could not inject %s link — anchor '%s' not found in any section",
                link_type, anchor,
            )

    return [
        s.model_copy(update={"content": contents[i], "word_count": count_words(contents[i])})
        for i, s in enumerate(sections)
    ]


async def link_strategist(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    logger.info("[%s] link_strategist: generating and injecting links", job_id)

    draft_sections = state.get("draft_sections") or []

    try:
        prompt = _build_prompt(
            topic=state["topic"],
            primary_keyword=state["primary_keyword"],
            sections=draft_sections,
        )
        links: LinkSet = await llm_service.call_llm(
            prompt=prompt,
            system=SYSTEM,
            response_model=LinkSet,
            temperature=0.4,
            max_tokens=2048,
        )

        # Inject links into the actual article content
        updated_sections = _inject_links_into_sections(draft_sections, links)

        injected = sum(
            1 for orig, updated in zip(draft_sections, updated_sections)
            if orig.content != updated.content
        )
        logger.info(
            "[%s] link_strategist: %d internal, %d external links — injected into %d sections",
            job_id, len(links.internal), len(links.external), injected,
        )
        return {
            "links": links,
            "draft_sections": updated_sections,
            "status": JobStatus.DRAFTING,
        }

    except Exception as e:
        logger.exception("[%s] link_strategist failed — continuing with original sections", job_id)
        return {"links": None, "status": JobStatus.DRAFTING, "error": str(e)}
