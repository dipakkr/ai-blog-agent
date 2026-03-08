"""
LangGraph pipeline wiring.

Defines the StateGraph with 8 nodes, conditional edge from seo_scorer,
and a SqliteSaver checkpointer. Exposes run_seo_pipeline() which is called
from app/main.py as a BackgroundTask.
"""

import logging

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from app.agents.article_writer import article_writer
from app.agents.competitor_analyzer import competitor_analyzer
from app.agents.content_classifier import content_classifier
from app.agents.faq_generator import faq_generator
from app.agents.gap_analyzer import gap_analyzer
from app.agents.link_strategist import link_strategist
from app.agents.outline_gen import outline_generator
from app.agents.revision_agent import revision_agent
from app.agents.seo_scorer import seo_scorer
from app.agents.serp_analyzer import serp_analyzer
from app.config import settings
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conditional routing after seo_scorer
# ---------------------------------------------------------------------------

def _route_after_scoring(state: SEOPipelineState) -> str:
    """Return next node name after seo_scorer runs.

    - If score passes (>= threshold) → END
    - If revision limit reached      → END  (best effort result kept)
    - Otherwise                      → revision_agent
    """
    seo_score = state.get("seo_score")
    if seo_score and seo_score.passed:
        return END  # type: ignore[return-value]

    if state["revision_count"] >= settings.max_revision_count:
        logger.warning(
            "[%s] Max revisions (%d) reached — accepting score %.0f",
            state["job_id"],
            settings.max_revision_count,
            seo_score.total if seo_score else 0,
        )
        return END  # type: ignore[return-value]

    return "revision_agent"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    graph = StateGraph(SEOPipelineState)

    # Register nodes
    graph.add_node("serp_analyzer",       serp_analyzer)
    graph.add_node("competitor_analyzer", competitor_analyzer)
    graph.add_node("content_classifier",  content_classifier)
    graph.add_node("gap_analyzer",        gap_analyzer)
    graph.add_node("outline_generator",  outline_generator)
    graph.add_node("article_writer",     article_writer)
    graph.add_node("link_strategist",    link_strategist)
    graph.add_node("faq_generator",      faq_generator)
    graph.add_node("seo_scorer",         seo_scorer)
    graph.add_node("revision_agent",     revision_agent)

    # Linear edges
    graph.set_entry_point("serp_analyzer")
    graph.add_edge("serp_analyzer",       "competitor_analyzer")
    graph.add_edge("competitor_analyzer", "content_classifier")
    graph.add_edge("content_classifier", "gap_analyzer")
    graph.add_edge("gap_analyzer",       "outline_generator")
    graph.add_edge("outline_generator", "article_writer")
    graph.add_edge("article_writer",   "link_strategist")
    graph.add_edge("link_strategist",  "faq_generator")
    graph.add_edge("faq_generator",    "seo_scorer")

    # Conditional: after scoring, either revise or finish
    graph.add_conditional_edges(
        "seo_scorer",
        _route_after_scoring,
        {"revision_agent": "revision_agent", END: END},
    )

    # After revision, re-score
    graph.add_edge("revision_agent", "seo_scorer")

    return graph


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_seo_pipeline(
    job_id: str,
    topic: str,
    primary_keyword: str,
    target_word_count: int,
    language: str,
) -> None:
    """Run the full SEO pipeline for a job.

    Uses AsyncSqliteSaver for persistent LangGraph checkpointing. State is saved
    after each node, so if the server restarts mid-run the graph can resume from
    the last completed node (thread_id == job_id).
    """
    initial_state: SEOPipelineState = {
        "job_id": job_id,
        "topic": topic,
        "primary_keyword": primary_keyword,
        "target_word_count": target_word_count,
        "language": language,
        # Pipeline fields — all None/empty at start
        "serp_data": None,
        "competitor_insights": None,
        "content_brief": None,
        "content_gaps": None,
        "outline": None,
        "draft_sections": None,
        "links": None,
        "faq": None,
        "seo_score": None,
        "article": None,
        # Control fields
        "revision_count": 0,
        "status": JobStatus.PENDING,
        "error": None,
    }

    graph = _build_graph()

    async with aiosqlite.connect(settings.langgraph_db_path) as conn:
        checkpointer = AsyncSqliteSaver(conn)
        compiled = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": job_id}}

        logger.info("[%s] Pipeline starting", job_id)
        final_state: SEOPipelineState = await compiled.ainvoke(initial_state, config=config)

    # Persist result — but distinguish between a real completed article and a
    # hollow one produced after node failures (e.g. article_writer errored,
    # seo_scorer assembled an article from empty/partial sections).
    article = final_state.get("article")
    seo_score = final_state.get("seo_score")
    score_total = seo_score.total if seo_score else 0

    has_content = (
        article is not None
        and article.sections
        and article.word_count > 0
    )
    passed = seo_score is not None and seo_score.passed

    if has_content and passed:
        job_manager.save_result(job_id, article)
        logger.info("[%s] Pipeline completed — article saved (%d words, score %.0f)",
                    job_id, article.word_count, score_total)
    elif has_content:
        # Article exists but did not pass SEO threshold — save so user can see
        # the partial result, then mark FAILED so it's retryable.
        job_manager.save_result(job_id, article)  # sets status=COMPLETED momentarily
        error_msg = (
            f"Article quality too low (score {score_total:.0f}/{settings.seo_score_threshold:.0f})"
            f" after {final_state['revision_count']} revision(s)"
        )
        job_manager.update_status(job_id, JobStatus.FAILED, error=error_msg)
        logger.warning("[%s] Pipeline finished with low score %.0f — marked FAILED with partial result",
                       job_id, score_total)
    else:
        error = final_state.get("error") or "Pipeline finished without producing an article"
        job_manager.update_status(job_id, JobStatus.FAILED, error=error)
        logger.error("[%s] Pipeline finished without article: %s", job_id, error)
