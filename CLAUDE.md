# AI SEO Content Generation Platform

FastAPI backend that generates SEO-optimized articles using a LangGraph agent pipeline. Takes a topic, analyzes top SERP results, identifies content gaps, generates a structured outline, writes the article section-by-section, scores it against SEO criteria, and conditionally revises until quality threshold is met. Jobs are resumable — if the process crashes mid-pipeline, it picks up from the last completed step.

## Commands

```bash
uvicorn app.main:app --reload          # Start dev server (port 8000)
pytest                                  # Run all tests
pytest tests/test_seo_scorer.py -v      # Run specific test file
pytest --cov=app                        # Run with coverage
```

## Architecture

###  Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python** | FastAPI + Pydantic = exactly what JD asks for |
| Framework | **FastAPI** | Async, typed, production-ready — matches their stack |
| Agent Framework | **LangGraph** | Stateful workflows, conditional routing, checkpointing |
| LLM | **Claude API** (primary) + **OpenAI fallback** | Shows multi-model thinking |
| Data Models | **Pydantic v2** | Explicitly asked for structured data models |
| Database | **SQLite + SQLAlchemy** | Job persistence without infra overhead |
| SERP API | **SerpAPI** (free tier) | Real data > mocked data |
| Testing | **Pytest** | SEO constraint validation |


### Core Flow

```
POST /generate → Job Manager (SQLite) → LangGraph Pipeline → Response

Pipeline nodes (sequential, with one conditional loop):
  START → serp_analyzer → gap_finder → outline_generator
        → article_writer → link_strategist → faq_generator
        → seo_scorer →[score < 75]→ revision_agent → seo_scorer (loop, max 3x)
                     →[score >= 75]→ END
```

###  Architecture Flow

```
┌──────────────────────────────────────────────────┐
│                   FastAPI Server                 │
│  POST /generate  GET /jobs/{id}  GET /jobs       │
│  POST /generate returns job_id immediately;      │
│  pipeline runs via FastAPI BackgroundTasks       │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│              Job Manager (SQLite)                │
│  States: pending → researching → outlining →     │
│          drafting → scoring → revising →         │
│          completed / failed                      │
│  Job records: SQLAlchemy ORM on jobs table       │
│  Checkpointing: LangGraph SqliteSaver (separate) │
│  (Resumable from any checkpoint)                 │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│           LangGraph Agent Pipeline               │
│        (sequential — one node at a time)         │
│                                                  │
│  ┌─────────────┐                                 │
│  │ serp_analyzer│                                │
│  └──────┬──────┘                                 │
│         ▼                                        │
│  ┌─────────────┐                                 │
│  │ gap_finder  │                                 │
│  └──────┬──────┘                                 │
│         ▼                                        │
│  ┌──────────────────┐                            │
│  │ outline_generator│                            │
│  └──────┬───────────┘                            │
│         ▼                                        │
│  ┌──────────────┐                                │
│  │article_writer│                                │
│  └──────┬───────┘                                │
│         ▼                                        │
│  ┌────────────────┐                              │
│  │ link_strategist│                              │
│  └──────┬─────────┘                              │
│         ▼                                        │
│  ┌───────────────┐                               │
│  │ faq_generator │                               │
│  └──────┬────────┘                               │
│         ▼                                        │
│  ┌────────────┐   score < 75   ┌──────────────┐  │
│  │ seo_scorer │───────────────▶│revision_agent│  │
│  └────────────┘◀───────────────└──────────────┘  │
│         │        loop max 3x                     │
│         │ score >= 75                            │
│         ▼                                        │
│        END                                       │
│                                                  │
│  Each node persists state → crash recovery ✓     │
└──────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **LangGraph over plain functions** — Conditional revision loop, built-in SQLite checkpointing for crash recovery, node-level testability
2. **Section-by-section writing** — Each H2 section is generated independently with outline + SERP context. Stays within token limits, easier to revise individual sections
3. **Real SERP data via SerpAPI** with mock fallback — Graceful degradation if API is down or rate-limited
4. **Multi-model support** — LLM calls go through `services/llm_service.py` abstraction. Currently Claude (primary) + OpenAI (fallback). Never call LLM APIs directly from nodes

### State Shape (single source of truth)

All nodes read from and write to `SEOPipelineState`. See `app/models/state.py` for the full TypedDict. Key fields:

- `topic`, `target_word_count`, `language` — input
- `serp_data` — filled by serp_analyzer
- `content_gaps` — filled by gap_finder  
- `outline` — filled by outline_generator
- `draft_sections` — list of sections, filled by article_writer
- `links` — internal + external, filled by link_strategist
- `faq` — filled by faq_generator
- `seo_score` — filled by seo_scorer, drives revision decision
- `revision_count` — tracks loop iterations (cap at 3)
- `status` — current pipeline stage, synced to job manager

### Checkpointing / Resumability

LangGraph's `SqliteSaver` persists state after every node. Each job gets a unique `thread_id`. To resume a crashed job, re-invoke with the same `thread_id` — it picks up from the last completed node.

## Project Structure

```
app/
├── main.py                 # FastAPI endpoints
├── config.py               # Settings via pydantic-settings
├── models/                 # Pydantic models — THE contract
│   ├── state.py            # SEOPipelineState (LangGraph state)
│   ├── request.py          # API input models
│   ├── article.py          # Article, SEO metadata, headings
│   ├── serp.py             # SERPResult, ThemeAnalysis
│   └── job.py              # Job status, checkpoint info
├── agents/
│   ├── pipeline.py         # LangGraph graph definition
│   ├── serp_analyzer.py    # Fetch + analyze top 10 SERP results
│   ├── gap_analyzer.py     # Identify content gaps from SERP themes
│   ├── outline_gen.py      # Build heading hierarchy from gaps
│   ├── article_writer.py   # Write article section by section
│   ├── link_strategist.py  # Internal + external link suggestions
│   ├── faq_generator.py    # FAQ from "People Also Ask" patterns
│   ├── seo_scorer.py       # Programmatic SEO validation
│   └── revision_agent.py   # Rewrite weak sections based on score
├── services/
│   ├── serp_service.py     # SerpAPI integration + mock fallback
│   ├── llm_service.py      # Multi-model abstraction (Claude/OpenAI)
│   └── job_manager.py      # SQLite job persistence + status tracking
└── utils/
    ├── seo_utils.py         # Keyword density, Flesch-Kincaid, heading checks
    └── text_utils.py        # Token counting, text cleaning
```

## Code Style

- **Pydantic v2 BaseModel** for all data models. No loose dicts for structured data. Exception: `SEOPipelineState` uses `TypedDict` (LangGraph requires it, not BaseModel)
- **Async everywhere** — FastAPI endpoints and httpx for HTTP calls, not requests
- Every agent node is a plain function: takes `SEOPipelineState`, returns `dict` with only the fields it updates
- Type hints on all functions. Use `Literal` for conditional edge return types
- Imports: stdlib → third-party → local, separated by blank lines
- Error handling: every node wraps external calls in try/except and sets `status` to `*_failed` on error

## SEO Scorer Criteria

The scorer in `agents/seo_scorer.py` checks these programmatically (not via LLM):

- Primary keyword in title tag
- Primary keyword in first 100 words
- Primary keyword in at least one H2
- Keyword density between 1–3%
- Meta description 150–160 characters
- Proper heading hierarchy (H1 → H2 → H3, no skips)
- At least 3 internal link suggestions
- At least 2 external references
- Flesch-Kincaid readability score > 60

Threshold for passing: overall score >= 75/100. Below triggers revision loop.

## Gotchas

- SerpAPI free tier: 100 searches/month. Use mock fallback in tests and when rate-limited
- LLM token limits: long articles (3000+ words) must be generated section-by-section, never in one prompt
- Revision loop is capped at 3 iterations via `revision_count` — always check this to prevent infinite loops
- SQLite checkpointer is single-writer. Fine for dev/demo. Production would use Postgres
- The `seo_scorer` must be deterministic (no LLM calls) — pure Python validation so tests are reliable

## DO NOTs

- Do NOT call LLM APIs directly in agent nodes. Always go through `services/llm_service.py`
- Do NOT use `requests` library. Use `httpx` with async
- Do NOT mock SERP data in the main pipeline. Use real SerpAPI with mock as fallback only
- Do NOT generate the full article in a single LLM call. Always section-by-section
- Do NOT store API keys in code. Use `.env` + `pydantic-settings`
- Do NOT add LLM calls to the SEO scorer. It must stay deterministic for testability