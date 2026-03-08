"""
Node: seo_scorer

Programmatic SEO validation — no LLM calls. Deterministic and fully testable.
Assembles the final Article object, scores it against 11 criteria, and stores
both in state. Score < 75 triggers the revision loop; >= 75 → END.
Updates job status to SCORING.
"""

import logging

import re

from app.models.article import (
    Article,
    KeywordAnalysis,
    LinkSet,
    SEOCheckResult,
    SEOMetadata,
    SEOScore,
    SecondaryKeywordUsage,
)
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.utils.seo_utils import (
    flesch_reading_ease,
    heading_hierarchy_valid,
    keyword_density,
    keyword_in_first_n_words,
    keyword_in_headings,
    meta_description_length_ok,
)
from app.utils.text_utils import clean_text, count_words, slugify

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 75.0

# (check_name, points_possible)
_CHECKS = [
    ("keyword_in_title",        12),
    ("keyword_in_first_100",    12),
    ("keyword_in_h2",           10),
    ("keyword_density_1_3pct",  12),
    ("meta_description_length",  8),
    ("heading_hierarchy",        8),
    ("internal_links_min_3",     8),
    ("external_links_min_2",     8),
    ("readability_flesch_60",    5),
    ("word_count_target",       10),
    ("secondary_keywords",       7),
]


def _run_checks(state: SEOPipelineState) -> list[SEOCheckResult]:
    outline = state["outline"]
    sections = state["draft_sections"] or []
    links = state["links"]
    kw = state["primary_keyword"].lower()

    full_text = clean_text(" ".join(s.content for s in sections))
    title = outline.title
    meta = outline.meta_description

    density = keyword_density(full_text, kw)
    fre = flesch_reading_ease(full_text)

    results: list[SEOCheckResult] = []

    def check(name: str, passed: bool, possible: int, detail: str) -> SEOCheckResult:
        return SEOCheckResult(
            check=name,
            passed=passed,
            points_earned=possible if passed else 0,
            points_possible=possible,
            detail=detail,
        )

    # 1. Primary keyword in title
    kw_in_title = kw in title.lower()
    results.append(check(
        "keyword_in_title", kw_in_title, 12,
        f"Title: '{title}'" if kw_in_title else f"Keyword '{kw}' not found in title: '{title}'",
    ))

    # 2. Primary keyword in first 100 words
    kw_in_intro = keyword_in_first_n_words(full_text, kw, 100)
    results.append(check(
        "keyword_in_first_100", kw_in_intro, 12,
        "Keyword found in opening." if kw_in_intro else "Keyword missing from first 100 words.",
    ))

    # 3. Primary keyword in at least one H2
    kw_in_h2 = keyword_in_headings(sections, kw)
    results.append(check(
        "keyword_in_h2", kw_in_h2, 10,
        "Keyword present in an H2 heading." if kw_in_h2
        else f"Keyword '{kw}' not found in any H2 heading.",
    ))

    # 4. Keyword density 1–3%
    density_ok = 1.0 <= density <= 3.0
    results.append(check(
        "keyword_density_1_3pct", density_ok, 12,
        f"Density: {density:.2f}% {'(OK)' if density_ok else '— target 1–3%'}",
    ))

    # 5. Meta description 150–160 characters
    meta_ok = meta_description_length_ok(meta)
    results.append(check(
        "meta_description_length", meta_ok, 8,
        f"Meta: {len(meta)} chars {'(OK)' if meta_ok else '— target 150–160'}",
    ))

    # 6. Heading hierarchy (no H3 before H2)
    hierarchy_ok = heading_hierarchy_valid(sections)
    results.append(check(
        "heading_hierarchy", hierarchy_ok, 8,
        "Heading hierarchy valid." if hierarchy_ok else "H3 appears before H2 — invalid hierarchy.",
    ))

    # 7. At least 3 internal links
    internal_ok = len(links.internal) >= 3 if links else False
    internal_count = len(links.internal) if links else 0
    results.append(check(
        "internal_links_min_3", internal_ok, 8,
        f"{internal_count} internal link(s) {'(OK)' if internal_ok else '— need at least 3'}",
    ))

    # 8. At least 2 external links
    external_ok = len(links.external) >= 2 if links else False
    external_count = len(links.external) if links else 0
    results.append(check(
        "external_links_min_2", external_ok, 8,
        f"{external_count} external link(s) {'(OK)' if external_ok else '— need at least 2'}",
    ))

    # 9. Flesch Reading Ease > 60
    readable = fre > 60.0
    results.append(check(
        "readability_flesch_60", readable, 5,
        f"Flesch score: {fre:.1f} {'(OK)' if readable else '— target > 60 (simpler language)'}",
    ))

    # 10. Word count vs target
    total_words = count_words(full_text)
    target = state.get("target_word_count", 0)
    if target > 0:
        ratio = total_words / target
        if 0.85 <= ratio <= 1.15:
            wc_points = 10
            wc_detail = f"{total_words} words vs {target} target — within ±15% (OK)"
        elif 0.70 <= ratio <= 1.30:
            wc_points = 5
            wc_detail = f"{total_words} words vs {target} target — within ±30% (partial)"
        else:
            wc_points = 0
            wc_detail = f"{total_words} words vs {target} target — outside ±30%"
    else:
        wc_points = 10
        wc_detail = "No target word count specified."
    results.append(SEOCheckResult(
        check="word_count_target",
        passed=wc_points == 10,
        points_earned=wc_points,
        points_possible=10,
        detail=wc_detail,
    ))

    # 11. Secondary keywords present in body (proportional credit)
    secondary_kws = state.get("outline", None)
    sec_kw_list = secondary_kws.secondary_keywords if secondary_kws else []
    if sec_kw_list:
        found = sum(1 for sk in sec_kw_list if sk.lower() in full_text.lower())
        missing = [sk for sk in sec_kw_list if sk.lower() not in full_text.lower()]
        ratio = found / len(sec_kw_list)
        sec_points = round(7 * ratio)
        passed_sec = ratio >= 0.8  # pass if ≥80% of secondary keywords present
        results.append(SEOCheckResult(
            check="secondary_keywords",
            passed=passed_sec,
            points_earned=sec_points,
            points_possible=7,
            detail=(
                f"{found}/{len(sec_kw_list)} secondary keywords found (OK)"
                if passed_sec
                else f"{found}/{len(sec_kw_list)} secondary keywords found — missing: {missing}"
            ),
        ))
    else:
        results.append(check(
            "secondary_keywords", True, 7,
            "No secondary keywords defined.",
        ))

    return results


def _build_keyword_analysis(state: SEOPipelineState) -> KeywordAnalysis:
    """Build a keyword usage report from the draft sections."""
    sections = state["draft_sections"] or []
    kw = state["primary_keyword"].lower()
    outline = state["outline"]

    full_text = clean_text(" ".join(s.content for s in sections))
    density = keyword_density(full_text, kw)
    in_title = kw in outline.title.lower()
    in_intro = keyword_in_first_n_words(full_text, kw, 100)

    # Which H2 headings contain the primary keyword
    h2_with_kw = [
        s.heading for s in sections
        if s.level.value == "h2" and kw in s.heading.lower()
    ]

    # Secondary keyword usage
    sec_kw_list = outline.secondary_keywords if outline else []
    secondary_usage = []
    for sk in sec_kw_list:
        occurrences = len(re.findall(re.escape(sk.lower()), full_text.lower()))
        secondary_usage.append(SecondaryKeywordUsage(
            keyword=sk,
            found=occurrences > 0,
            count=occurrences,
        ))

    return KeywordAnalysis(
        primary_keyword=state["primary_keyword"],
        primary_density=density,
        primary_in_title=in_title,
        primary_in_intro=in_intro,
        primary_in_h2_headings=h2_with_kw,
        secondary_keywords=secondary_usage,
    )


def _assemble_article(state: SEOPipelineState, seo_score: SEOScore) -> Article:
    outline = state["outline"]
    return Article(
        metadata=SEOMetadata(
            title=outline.title,
            meta_description=outline.meta_description,
            primary_keyword=state["primary_keyword"],
            secondary_keywords=outline.secondary_keywords,
            slug=slugify(outline.title),
        ),
        sections=state["draft_sections"] or [],
        links=state["links"] or LinkSet(internal=[], external=[]),
        faq=state["faq"] or [],
        word_count=sum(s.word_count for s in (state["draft_sections"] or [])),
        seo_score=seo_score,
        keyword_analysis=_build_keyword_analysis(state),
    )


def seo_scorer(state: SEOPipelineState) -> dict:
    """Synchronous — pure Python, no IO."""
    job_id = state["job_id"]
    job_manager.update_status(job_id, JobStatus.SCORING)
    logger.info("[%s] seo_scorer: running checks (revision %d)", job_id, state["revision_count"])

    try:
        check_results = _run_checks(state)
        total = sum(c.points_earned for c in check_results)
        passed = total >= PASS_THRESHOLD

        seo_score = SEOScore(total=total, checks=check_results, passed=passed)
        article = _assemble_article(state, seo_score)

        failed = [c.check for c in check_results if not c.passed]
        logger.info(
            "[%s] seo_scorer: score=%.0f/100 %s | failed: %s",
            job_id, total, "PASS" if passed else "FAIL",
            failed or "none",
        )
        return {
            "seo_score": seo_score,
            "article": article,
            "status": JobStatus.SCORING,
        }
    except Exception as e:
        logger.exception("[%s] seo_scorer failed", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "scoring_failed", "error": str(e)}
