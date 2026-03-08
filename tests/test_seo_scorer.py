"""
Tests for the seo_scorer node.

Validates each scoring check with mock draft sections, outline, and links.

Run:
    pytest tests/test_seo_scorer.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.agents.seo_scorer import _run_checks, seo_scorer, PASS_THRESHOLD
from app.models.article import (
    ArticleSection,
    ExternalLink,
    HeadingLevel,
    InternalLink,
    LinkSet,
    Outline,
    OutlineSection,
)


def _make_outline(
    title: str = "Best CI/CD Tools for Python Projects",
    meta: str = "x" * 155,  # 155 chars — within 150-160 range
    primary_keyword: str = "ci/cd tools",
    secondary_keywords: list[str] | None = None,
) -> Outline:
    return Outline(
        title=title,
        meta_description=meta,
        primary_keyword=primary_keyword,
        secondary_keywords=secondary_keywords or ["python ci", "continuous integration"],
        sections=[
            OutlineSection(
                heading="Introduction to CI/CD Tools",
                level=HeadingLevel.H2,
                key_points=["overview"],
            ),
            OutlineSection(
                heading="Top CI/CD Tools Compared",
                level=HeadingLevel.H2,
                key_points=["comparison"],
            ),
        ],
    )


def _make_sections(
    keyword: str = "ci/cd tools",
    word_count: int = 1500,
    include_keyword_in_h2: bool = True,
) -> list[ArticleSection]:
    # Build body text with keyword appearing for ~2% density
    body_words = ["word"] * (word_count - 20)
    # Insert keyword every ~50 words for reasonable density
    kw_words = keyword.split()
    insertions = max(1, word_count // 50)
    for i in range(insertions):
        pos = min(i * 50, len(body_words) - 1)
        body_words[pos] = keyword
    body = " ".join(body_words)
    # Ensure keyword is in first 100 words
    intro = f"The best {keyword} available today help teams. " + " ".join(body_words[:200])
    rest = " ".join(body_words[200:])
    h2_heading = f"Top {keyword.title()} Compared" if include_keyword_in_h2 else "Top Options Compared"
    return [
        ArticleSection(
            heading="Introduction",
            level=HeadingLevel.H2,
            content=intro,
            word_count=len(intro.split()),
        ),
        ArticleSection(
            heading=h2_heading,
            level=HeadingLevel.H2,
            content=rest,
            word_count=len(rest.split()),
        ),
    ]


def _make_links(internal_count: int = 3, external_count: int = 2) -> LinkSet:
    return LinkSet(
        internal=[
            InternalLink(
                anchor_text=f"link {i}",
                suggested_url=f"/page-{i}",
                domain="example.com",
                context="context",
            )
            for i in range(internal_count)
        ],
        external=[
            ExternalLink(
                anchor_text=f"ext {i}",
                url=f"https://ext{i}.com",
                domain=f"ext{i}.com",
                context="context",
            )
            for i in range(external_count)
        ],
    )


def _make_state(**overrides) -> dict:
    """Build a minimal state dict for seo_scorer."""
    state = {
        "job_id": "test-job",
        "topic": "CI/CD Tools for Python",
        "primary_keyword": "ci/cd tools",
        "target_word_count": 1500,
        "language": "en",
        "serp_data": None,
        "competitor_insights": None,  # entity_coverage defaults to pass when None
        "content_brief": None,
        "content_gaps": None,
        "outline": _make_outline(),
        "draft_sections": _make_sections(),
        "links": _make_links(),
        "faq": [],
        "seo_score": None,
        "article": None,
        "revision_count": 0,
        "status": "scoring",
        "error": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Individual check tests
# ---------------------------------------------------------------------------

class TestKeywordInTitle:
    def test_passes_when_keyword_in_title(self):
        state = _make_state()
        results = _run_checks(state)
        title_check = next(c for c in results if c.check == "keyword_in_title")
        assert title_check.passed

    def test_fails_when_keyword_missing_from_title(self):
        outline = _make_outline(title="Best Deployment Pipelines")
        state = _make_state(outline=outline)
        results = _run_checks(state)
        title_check = next(c for c in results if c.check == "keyword_in_title")
        assert not title_check.passed
        assert title_check.points_earned == 0


class TestKeywordInFirst100:
    def test_passes_with_keyword_in_intro(self):
        state = _make_state()
        results = _run_checks(state)
        check = next(c for c in results if c.check == "keyword_in_first_100")
        assert check.passed

    def test_fails_when_keyword_not_in_intro(self):
        sections = [
            ArticleSection(
                heading="Intro",
                level=HeadingLevel.H2,
                content=" ".join(["filler"] * 200),
                word_count=200,
            ),
        ]
        state = _make_state(draft_sections=sections)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "keyword_in_first_100")
        assert not check.passed


class TestKeywordInH2:
    def test_passes_with_keyword_in_heading(self):
        state = _make_state()
        results = _run_checks(state)
        check = next(c for c in results if c.check == "keyword_in_h2")
        assert check.passed

    def test_fails_without_keyword_in_heading(self):
        sections = _make_sections(include_keyword_in_h2=False)
        state = _make_state(draft_sections=sections)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "keyword_in_h2")
        assert not check.passed


class TestMetaDescriptionLength:
    def test_passes_at_155_chars(self):
        state = _make_state()
        results = _run_checks(state)
        check = next(c for c in results if c.check == "meta_description_length")
        assert check.passed

    def test_fails_when_too_short(self):
        outline = _make_outline(meta="Too short meta")
        state = _make_state(outline=outline)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "meta_description_length")
        assert not check.passed

    def test_fails_when_too_long(self):
        outline = _make_outline(meta="x" * 200)
        state = _make_state(outline=outline)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "meta_description_length")
        assert not check.passed


class TestHeadingHierarchy:
    def test_passes_with_valid_hierarchy(self):
        state = _make_state()
        results = _run_checks(state)
        check = next(c for c in results if c.check == "heading_hierarchy")
        assert check.passed

    def test_fails_with_h3_before_h2(self):
        sections = [
            ArticleSection(heading="Sub", level=HeadingLevel.H3, content="text", word_count=1),
            ArticleSection(heading="Main", level=HeadingLevel.H2, content="text", word_count=1),
        ]
        state = _make_state(draft_sections=sections)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "heading_hierarchy")
        assert not check.passed


class TestInternalLinks:
    def test_passes_with_3_links(self):
        state = _make_state()
        results = _run_checks(state)
        check = next(c for c in results if c.check == "internal_links_min_3")
        assert check.passed

    def test_fails_with_fewer_than_3(self):
        links = _make_links(internal_count=2)
        state = _make_state(links=links)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "internal_links_min_3")
        assert not check.passed


class TestExternalLinks:
    def test_passes_with_2_links(self):
        state = _make_state()
        results = _run_checks(state)
        check = next(c for c in results if c.check == "external_links_min_2")
        assert check.passed

    def test_fails_with_fewer_than_2(self):
        links = _make_links(external_count=1)
        state = _make_state(links=links)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "external_links_min_2")
        assert not check.passed


class TestWordCountTarget:
    def test_passes_within_15_percent(self):
        state = _make_state(target_word_count=1500)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "word_count_target")
        assert check.points_earned >= 5  # at least partial

    def test_full_points_within_15_percent(self):
        # Sections have roughly known word count; set target to match
        sections = _make_sections(word_count=500)
        total = sum(s.word_count for s in sections)
        state = _make_state(draft_sections=sections, target_word_count=total)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "word_count_target")
        assert check.points_earned == 10

    def test_zero_points_when_far_off(self):
        state = _make_state(target_word_count=50000)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "word_count_target")
        assert check.points_earned == 0


class TestSecondaryKeywords:
    def test_passes_when_all_present(self):
        outline = _make_outline(secondary_keywords=["word"])
        state = _make_state(outline=outline)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "secondary_keywords")
        assert check.passed

    def test_fails_when_missing(self):
        outline = _make_outline(secondary_keywords=["xyznonexistent123"])
        state = _make_state(outline=outline)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "secondary_keywords")
        assert not check.passed


class TestEntityCoverage:
    def test_passes_with_no_entity_data(self):
        """No competitor_insights → full points (can't penalise missing scrape)."""
        state = _make_state(competitor_insights=None)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "entity_coverage")
        assert check.passed
        assert check.points_earned == 5

    def test_passes_when_entities_covered(self):
        from app.models.serp import CompetitorInsights, CompetitorPage
        insights = CompetitorInsights(
            pages_attempted=5, pages_scraped=3,
            avg_word_count=1500, avg_h2_count=5.0,
            suggested_section_count=5,
            common_headings=[], structural_signals=[],
            common_secondary_keywords=[],
            top_entities=["word", "ci/cd tools"],  # both appear in body text
            pages=[],
        )
        state = _make_state(competitor_insights=insights)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "entity_coverage")
        assert check.passed

    def test_fails_when_entities_missing(self):
        from app.models.serp import CompetitorInsights
        insights = CompetitorInsights(
            pages_attempted=5, pages_scraped=3,
            avg_word_count=1500, avg_h2_count=5.0,
            suggested_section_count=5,
            common_headings=[], structural_signals=[],
            common_secondary_keywords=[],
            top_entities=["xyzunknowntool1", "xyzunknowntool2", "xyzunknowntool3"],
            pages=[],
        )
        state = _make_state(competitor_insights=insights)
        results = _run_checks(state)
        check = next(c for c in results if c.check == "entity_coverage")
        assert not check.passed


# ---------------------------------------------------------------------------
# Full scorer node test
# ---------------------------------------------------------------------------

class TestSeoScorerNode:
    def test_total_is_sum_of_check_points(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        score = result["seo_score"]
        assert score.total == sum(c.points_earned for c in score.checks)

    def test_all_checks_total_100(self):
        """All check point_possible values sum to 100."""
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        total_possible = sum(c.points_possible for c in result["seo_score"].checks)
        assert total_possible == 100

    def test_passes_when_above_threshold(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        # With good defaults, should pass
        if result["seo_score"].total >= PASS_THRESHOLD:
            assert result["seo_score"].passed
        else:
            assert not result["seo_score"].passed

    def test_article_assembled(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        assert result["article"] is not None
        assert result["article"].metadata.primary_keyword == "ci/cd tools"


# ---------------------------------------------------------------------------
# Keyword analysis tests
# ---------------------------------------------------------------------------

class TestKeywordAnalysis:
    def test_keyword_analysis_populated(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        ka = result["article"].keyword_analysis
        assert ka is not None
        assert ka.primary_keyword == "ci/cd tools"

    def test_primary_density_is_float(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        ka = result["article"].keyword_analysis
        assert isinstance(ka.primary_density, float)
        assert ka.primary_density >= 0.0

    def test_primary_in_title_detected(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        ka = result["article"].keyword_analysis
        assert ka.primary_in_title is True

    def test_primary_in_title_false_when_missing(self):
        outline = _make_outline(title="Best Deployment Pipelines")
        state = _make_state(outline=outline)
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        ka = result["article"].keyword_analysis
        assert ka.primary_in_title is False

    def test_primary_in_intro_detected(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        ka = result["article"].keyword_analysis
        assert ka.primary_in_intro is True

    def test_h2_headings_with_keyword_listed(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        ka = result["article"].keyword_analysis
        assert isinstance(ka.primary_in_h2_headings, list)
        assert any("Ci/Cd Tools" in h for h in ka.primary_in_h2_headings)

    def test_secondary_keywords_usage(self):
        state = _make_state()
        with patch("app.agents.seo_scorer.job_manager"):
            result = seo_scorer(state)
        ka = result["article"].keyword_analysis
        assert len(ka.secondary_keywords) == 2  # "python ci", "continuous integration"
        for sk in ka.secondary_keywords:
            assert hasattr(sk, "keyword")
            assert hasattr(sk, "found")
            assert hasattr(sk, "count")
            assert isinstance(sk.count, int)
