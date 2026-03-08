# AI SEO Content Generation Platform

FastAPI backend that generates SEO-optimized articles using a LangGraph agent pipeline. Takes a topic, analyzes top SERP results, identifies content gaps, classifies content format, generates a structured outline, writes the article section-by-section, scores it against SEO criteria, and conditionally revises until quality threshold is met.

## Pipeline Architecture

```
POST /generate → Job Manager (SQLite) → LangGraph Pipeline → Article JSON

Pipeline nodes (10 nodes, sequential with one conditional loop):

  START → serp_analyzer → content_classifier → gap_finder → outline_generator
        → article_writer → link_strategist → faq_generator
        → seo_scorer →[score < 75]→ revision_agent → seo_scorer (loop, max 3x)
                     →[score >= 75]→ END
```

Each node persists state via LangGraph's SQLite checkpointing. If the process crashes mid-pipeline, it resumes from the last completed node.

### Key Design Decisions

- **Format-aware generation** — `content_classifier` detects the optimal format (tutorial, comparison, listicle, explainer, case study) and tailors all downstream nodes
- **Enriched SERP context** — article_writer receives competitor pages, PAA questions, themes, and content gaps — not just titles
- **Deterministic scoring** — `seo_scorer` uses pure Python checks (no LLM calls) across 11 criteria totaling 100 points
- **Checkpoint retry** — failed jobs resume from last completed node via `/jobs/{id}/retry`
- **Section-by-section writing** — stays within token limits, enables targeted revision of weak sections

## Setup

### Requirements

- Python 3.9+
- API keys: Anthropic (required), OpenAI (fallback), SerpAPI (optional, has mock fallback)

### Installation

```bash
git clone <repo-url> && cd aiseo-backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys:
#   ANTHROPIC_API_KEY=sk-ant-...
#   OPENAI_API_KEY=sk-...        (optional, fallback)
#   SERPAPI_KEY=...               (optional, mock fallback available)
```

### Run

```bash
# Backend (port 8000)
uvicorn app.main:app --reload

# Frontend (port 3000)
cd frontend && npm install && npm run dev

# Tests
python3 -m pytest tests/ -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/generate` | Create a new article generation job (returns 202 with job_id) |
| `GET` | `/jobs/{job_id}` | Get job status and result |
| `POST` | `/jobs/{job_id}/retry` | Resume a failed job from last checkpoint |
| `GET` | `/jobs/{job_id}/pipeline` | Get intermediate pipeline artifacts |
| `GET` | `/jobs` | List all jobs (newest first) |

## Example Usage

### Create a job

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Best CI/CD Tools for Python Projects",
    "target_word_count": 2000,
    "primary_keyword": "ci/cd tools"
  }'
# → {"job_id": "abc123", "status": "pending"}
```

### Check job status

```bash
curl http://localhost:8000/jobs/abc123
```

### View pipeline artifacts (intermediate results)

```bash
curl http://localhost:8000/jobs/abc123/pipeline
```

### Retry a failed job

```bash
curl -X POST http://localhost:8000/jobs/abc123/retry
```

## SEO Scoring (11 Checks, 100 Points)

| Check | Points | Criteria |
|-------|--------|----------|
| Keyword in title | 12 | Primary keyword appears in article title |
| Keyword in first 100 words | 12 | Primary keyword in opening paragraph |
| Keyword in H2 | 10 | Primary keyword in at least one H2 heading |
| Keyword density 1-3% | 12 | Keyword density within optimal range |
| Meta description length | 8 | 150-160 characters |
| Heading hierarchy | 8 | Valid H1→H2→H3 structure, no skips |
| Internal links ≥3 | 8 | At least 3 internal link suggestions |
| External links ≥2 | 8 | At least 2 external references |
| Readability (Flesch >60) | 5 | Flesch Reading Ease score above 60 |
| Word count vs target | 10 | Within ±15% of target (full), ±30% (partial) |
| Secondary keywords | 7 | All secondary keywords present in body |

Threshold: **75/100** to pass. Below triggers revision loop (max 3 iterations).

## Project Structure

```
app/
├── main.py                 # FastAPI endpoints
├── config.py               # Settings via pydantic-settings
├── models/                 # Pydantic models
│   ├── state.py            # SEOPipelineState (LangGraph state)
│   ├── request.py          # API input models
│   ├── article.py          # Article, SEO metadata, headings
│   ├── serp.py             # SERPResult, ThemeAnalysis, ContentBrief
│   └── job.py              # Job status, checkpoint info
├── agents/                 # LangGraph pipeline nodes
│   ├── pipeline.py         # Graph definition
│   ├── serp_analyzer.py    # Fetch + analyze top 10 SERP results
│   ├── content_classifier.py # Detect optimal content format
│   ├── gap_analyzer.py     # Identify content gaps from SERP themes
│   ├── outline_gen.py      # Build heading hierarchy from gaps
│   ├── article_writer.py   # Write article section by section
│   ├── link_strategist.py  # Internal + external link suggestions
│   ├── faq_generator.py    # FAQ from "People Also Ask" patterns
│   ├── seo_scorer.py       # Programmatic SEO validation (11 checks)
│   └── revision_agent.py   # Rewrite weak sections based on score
├── services/
│   ├── serp_service.py     # SerpAPI integration + mock fallback
│   ├── llm_service.py      # Multi-model abstraction (Claude/OpenAI)
│   └── job_manager.py      # SQLite job persistence + status tracking
└── utils/
    ├── seo_utils.py        # Keyword density, Flesch-Kincaid, heading checks
    └── text_utils.py       # Token counting, text cleaning
tests/
├── test_seo_scorer.py      # Unit tests for all 11 scoring checks
├── test_api.py             # Integration tests for API endpoints
└── test_services.py        # LLM service and SERP service tests
```
