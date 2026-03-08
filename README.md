# AI SEO Content Generation Platform

FastAPI backend that generates SEO-optimized articles using a LangGraph agent pipeline. Takes a topic, analyzes top SERP results, scrapes competitor pages, identifies content gaps, classifies content format, generates a structured outline, writes the article section-by-section, injects links, scores it against SEO criteria, and conditionally revises until quality threshold is met.

## Pipeline Architecture

```
POST /generate → Job Manager (SQLite) → Redis Queue → LangGraph Pipeline → Article JSON

Pipeline nodes (10 nodes, sequential with one conditional loop):

  START → serp_analyzer → competitor_analyzer → content_classifier → gap_finder
        → outline_generator → article_writer → link_strategist → faq_generator
        → seo_scorer →[score < 75]→ revision_agent → seo_scorer (loop, max 3x)
                     →[score >= 75]→ END
```

Each node persists state via LangGraph's SQLite checkpointing. If the process crashes mid-pipeline, it resumes from the last completed node.

### What Each Node Does

| Node | Purpose |
|------|---------|
| `serp_analyzer` | Fetches top SERP results for the topic via SerpAPI |
| `competitor_analyzer` | Scrapes competitor pages for headings, word counts, structure |
| `content_classifier` | Detects optimal format (listicle/tutorial/comparison/explainer), search intent, subcategory structure |
| `gap_analyzer` | Identifies specific content gaps competitors miss |
| `outline_generator` | Builds H2/H3 hierarchy consuming the strategy contract from classifier |
| `article_writer` | Writes article section-by-section (single-shot for ≤2500 words, multi-shot for longer) |
| `link_strategist` | Generates and injects internal/external links as markdown hyperlinks into content |
| `faq_generator` | Creates FAQ from People Also Ask data |
| `seo_scorer` | Deterministic SEO validation (no LLM) across 11 criteria |
| `revision_agent` | Rewrites weak sections based on scorer feedback |

### Key Design Decisions

- **Strategy contract** — `content_classifier` outputs a structured `ContentBrief` with search intent, subcategory detection, section count math, and pre-extracted tool names. `outline_generator` consumes this directly instead of re-deriving from raw SERP data.
- **Deterministic pre-processing** — Tool name extraction, section count calculation, search intent detection, and heading cleanup are code functions (`utils/serp_utils.py`), not LLM tasks.
- **Deterministic scoring** — `seo_scorer` uses pure Python checks (no LLM calls) across 11 criteria totaling 100 points
- **Checkpoint recovery** — Failed jobs resume from last completed node via `/jobs/{id}/retry`
- **Section-by-section writing** — Stays within token limits, enables targeted revision of weak sections
- **Multi-model support** — Claude (primary) with OpenAI fallback, abstracted behind `services/llm_service.py`

### SEO Scoring (11 Checks, 100 Points)

| Check | Points | Criteria |
|-------|--------|----------|
| Keyword in title | 12 | Primary keyword appears in article title (fuzzy match) |
| Keyword in first 100 words | 12 | Primary keyword in opening paragraph |
| Keyword in H2 | 10 | Primary keyword in at least one H2 heading |
| Keyword density 1-3% | 12 | Keyword density within optimal range (counts plurals) |
| Meta description length | 8 | 150-160 characters |
| Heading hierarchy | 8 | Valid H1 → H2 → H3 structure, no skips |
| Internal links ≥ 3 | 8 | At least 3 internal link suggestions |
| External links ≥ 2 | 8 | At least 2 external references |
| Readability (Flesch > 60) | 5 | Flesch Reading Ease score above 60 |
| Word count vs target | 10 | Within ±15% of target (full), ±30% (partial) |
| Secondary keywords | 7 | All secondary keywords present in body |

Threshold: **75/100** to pass. Below triggers revision loop (max 3 iterations).

## Setup & Running

### Requirements

- Python 3.9+
- Redis (for job queue; falls back to in-process execution if unavailable)
- API keys: Anthropic (required), OpenAI (fallback), SerpAPI (optional, has mock fallback)

### Installation

```bash
git clone <repo-url> && cd aiseo-backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key (primary LLM) |
| `OPENAI_API_KEY` | No | — | OpenAI key (fallback LLM) |
| `SERPAPI_KEY` | No | — | SerpAPI key (falls back to mock data if missing) |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection URL |
| `DATABASE_URL` | No | `sqlite:///./jobs.db` | SQLAlchemy DB URL for job persistence |
| `LANGGRAPH_DB_PATH` | No | `./checkpoints.db` | SQLite path for LangGraph checkpoints |
| `PRIMARY_LLM` | No | `claude-sonnet-4-6` | Primary model for all LLM calls |
| `FALLBACK_LLM` | No | `gpt-4o-mini` | Fallback model when primary fails |
| `SEO_SCORE_THRESHOLD` | No | `75.0` | Minimum SEO score to pass (0-100) |
| `MAX_REVISION_COUNT` | No | `3` | Max revision loop iterations |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG` to see all LLM prompts/responses) |

### Start the Service

```bash
# 1. Start Redis (optional — falls back to in-process async tasks without it)
brew install redis && brew services start redis        # macOS
# sudo apt install redis-server && sudo systemctl start redis  # Linux
# docker run -d -p 6379:6379 redis:alpine                     # Docker

# 2. Start the API server
uvicorn app.main:app --reload --port 8000

# 3. Start the RQ worker (picks jobs from Redis queue)
rq worker seo_pipeline --worker-class rq.SimpleWorker  # macOS
# rq worker seo_pipeline --with-scheduler              # Linux

# 4. Frontend (optional)
cd frontend && npm install && npm run dev
```

### Running Tests

```bash
python3 -m pytest tests/ -v              # All tests
python3 -m pytest tests/test_seo_scorer.py -v  # Specific file
python3 -m pytest --cov=app tests/       # With coverage
```

## API Routes

### `POST /generate`

Create a new article generation job. Returns immediately with `job_id`.

**Request body:**

```json
{
  "topic": "The 7 Best n8n Alternatives in 2025",
  "primary_keyword": "n8n alternatives",
  "target_word_count": 1500,
  "language": "en"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `topic` | string | Yes | — | Article topic (3-500 chars) |
| `primary_keyword` | string | No | topic | SEO target keyword |
| `target_word_count` | int | No | 1500 | Target length (500-10000) |
| `language` | string | No | `"en"` | Content language |

**Response** (202):

```json
{
  "job_id": "a20f2ef7-3018-47ae-bba1-fc9253287795",
  "status": "pending"
}
```

---

### `GET /jobs/{job_id}`

Get job status and result. When status is `completed`, the `result` field contains the full article.

**Response** (200):

```json
{
  "job_id": "a20f2ef7",
  "status": "completed",
  "topic": "The 7 Best n8n Alternatives in 2025",
  "primary_keyword": "n8n alternatives",
  "target_word_count": 1500,
  "language": "en",
  "created_at": "2025-03-08T10:00:00",
  "updated_at": "2025-03-08T10:05:00",
  "error": null,
  "result": {
    "metadata": {
      "title": "The 7 Best n8n Alternatives in 2025",
      "meta_description": "...",
      "primary_keyword": "n8n alternatives",
      "secondary_keywords": ["workflow automation", "zapier alternative"],
      "slug": "best-n8n-alternatives"
    },
    "sections": [
      {
        "heading": "Make (Integromat)",
        "level": "h2",
        "content": "...",
        "word_count": 200
      }
    ],
    "links": {
      "internal": [{"anchor_text": "...", "suggested_url": "/blog/...", "context": "..."}],
      "external": [{"anchor_text": "...", "url": "https://...", "domain": "...", "context": "..."}]
    },
    "faq": [{"question": "...", "answer": "..."}],
    "word_count": 1500,
    "seo_score": {"total": 82.0, "checks": [...], "passed": true},
    "keyword_analysis": {"primary_keyword": "n8n alternatives", "primary_density": 1.8, ...}
  }
}
```

**Job status progression:** `pending` → `researching` → `outlining` → `drafting` → `scoring` → `revising` (if needed) → `completed` / `failed`

---

### `GET /jobs`

List all jobs ordered by creation time (newest first).

**Response** (200): Array of `JobDetailResponse` objects (same shape as `GET /jobs/{job_id}`).

---

### `POST /jobs/{job_id}/retry`

Resume a failed job from its last LangGraph checkpoint. Only `failed` jobs can be retried.

**Response** (202):

```json
{
  "job_id": "a20f2ef7",
  "status": "pending"
}
```

**Errors:**
- `404` — Job not found
- `409` — Job is not in `failed` status

---

### `GET /jobs/{job_id}/history`

Return all previous attempt snapshots for a job (populated on each retry).

**Response** (200):

```json
[
  {
    "attempt": 1,
    "timestamp": "2025-03-08T10:05:00",
    "status": "failed",
    "error": "Article quality too low (score 62/75) after 3 revision(s)",
    "result": null
  }
]
```

---

### `GET /jobs/{job_id}/pipeline`

Return intermediate pipeline artifacts for debugging. Each key corresponds to a completed pipeline node.

**Response** (200):

```json
{
  "serp": {
    "query": "The 7 Best n8n Alternatives in 2025",
    "results": [{"position": 1, "title": "...", "url": "...", "domain": "...", "snippet": "..."}],
    "people_also_ask": ["Is there a free alternative to n8n?", "..."],
    "themes": [{"theme": "workflow automation", "frequency": 5, "sources": ["..."]}]
  },
  "classification": {
    "format": "listicle",
    "search_intent": "commercial_investigation",
    "has_subcategories": false,
    "audience": "developer",
    "suggested_section_count": 7,
    "recommended_tools": ["Make", "Zapier", "Apache Airflow", "..."],
    "competitive_angle": "..."
  },
  "gaps": [
    {"topic": "Self-hosting comparison", "reason": "No competitor compares hosting options", "priority": "high"}
  ],
  "outline": {
    "title": "...",
    "meta_description": "...",
    "sections": [{"heading": "...", "level": "h2", "key_points": ["..."]}]
  },
  "draft": {
    "sections": [{"heading": "...", "content": "...", "word_count": 200}]
  }
}
```

## Project Structure

```
app/
├── main.py                 # FastAPI endpoints (6 routes)
├── config.py               # Settings via pydantic-settings
├── queue.py                # Redis/RQ job queue with in-process fallback
├── models/                 # Pydantic models
│   ├── state.py            # SEOPipelineState (LangGraph state)
│   ├── request.py          # API input models
│   ├── article.py          # Article, SEO metadata, headings, links
│   ├── serp.py             # SERPResult, ContentBrief, CompetitorInsights
│   └── job.py              # Job status, response models
├── agents/                 # LangGraph pipeline nodes
│   ├── pipeline.py         # Graph definition + run_seo_pipeline()
│   ├── serp_analyzer.py    # Fetch + analyze top SERP results
│   ├── competitor_analyzer.py # Scrape competitor pages for structure
│   ├── content_classifier.py # Detect format, intent, subcategories (strategy contract)
│   ├── gap_analyzer.py     # Identify content gaps from SERP + scraped data
│   ├── outline_gen.py      # Build heading hierarchy from strategy contract
│   ├── article_writer.py   # Write article section by section
│   ├── link_strategist.py  # Generate + inject links into content
│   ├── faq_generator.py    # FAQ from "People Also Ask" patterns
│   ├── seo_scorer.py       # Programmatic SEO validation (11 checks)
│   └── revision_agent.py   # Rewrite weak sections based on score
├── services/
│   ├── serp_service.py     # SerpAPI integration + mock fallback
│   ├── llm_service.py      # Multi-model abstraction (Claude/OpenAI)
│   └── job_manager.py      # SQLite job persistence + status tracking
└── utils/
    ├── seo_utils.py        # Keyword density, Flesch-Kincaid, heading checks
    ├── serp_utils.py       # Deterministic SERP pre-processing (heading cleanup, tool extraction, section count math)
    └── text_utils.py       # Token counting, text cleaning, slugify
tests/
├── test_seo_scorer.py      # Unit tests for all 11 scoring checks
├── test_api.py             # Integration tests for API endpoints
└── test_services.py        # LLM service and SERP service tests
```
