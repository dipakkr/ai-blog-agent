"""
Node: content_classifier

Analyses the topic, primary keyword, and SERP data to determine the optimal
content format, target audience, and structural patterns observed in what's
actually ranking — not keyword pattern matching.

The resulting ContentBrief carries SERP-derived structural intelligence
(structural_patterns, competitive_angle, writing_style_notes) that replaces
the static format_rules dict in outline_gen.
"""

import logging

from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.models.serp import ContentBrief
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are a senior content strategist who reverse-engineers why content ranks. "
    "Given real SERP data, you identify structural patterns, content angles, and "
    "audience signals from what's actually working — not from keyword guessing. "
    "Your analysis directly shapes the outline and writing instructions for a new article."
)


def _build_prompt(state: SEOPipelineState) -> str:
    serp = state.get("serp_data")
    insights = state.get("competitor_insights")

    # SERP titles + snippets (always available)
    competitor_details = "\n".join(
        f"{r.position}. {r.title}\n   Domain: {r.domain}\n   Snippet: {r.snippet}"
        for r in (serp.results[:8] if serp else [])
    )
    paa = "\n".join(f"- {q}" for q in (serp.people_also_ask[:6] if serp else []))

    # Real scraped page data (available when competitor_analyzer succeeded)
    scraped_block = ""
    if insights and insights.pages_scraped > 0:
        page_details = []
        for p in insights.pages:
            if not p.scraped:
                continue
            h2_preview = ", ".join(f'"{h}"' for h in p.h2_headings[:5])
            page_details.append(
                f"  {p.domain}: {p.word_count} words | {len(p.h2_headings)} H2s: [{h2_preview}] | "
                f"table={p.has_table} list={p.has_numbered_list} code={p.has_code_block} "
                f"readability={p.readability_score}"
            )
        scraped_block = f"""
--- SCRAPED COMPETITOR PAGE DATA ({insights.pages_scraped}/{insights.pages_attempted} pages parsed) ---
{chr(10).join(page_details)}

Aggregated signals:
{chr(10).join(f"  - {s}" for s in insights.structural_signals)}

Common H2 headings (appearing in 2+ results):
{chr(10).join(f"  - {h}" for h in insights.common_headings) or "  (none found)"}

Common secondary keywords across pages:
  {", ".join(insights.common_secondary_keywords) or "(none)"}
"""

    # Strong topic-level format hint — overrides ambiguous SERP signals
    import re as _re
    _topic = state["topic"]
    if _re.search(r"\b(vs\.?|versus|compared?|comparison)\b", _topic, _re.I):
        topic_format_hint = "NOTE: The topic contains 'vs/comparison' keywords → FORMAT is almost certainly 'comparison'."
    elif _re.search(r"\b(how\s+to|step.by.step|tutorial|guide)\b", _topic, _re.I):
        topic_format_hint = "NOTE: The topic contains 'how to/guide' keywords → FORMAT is almost certainly 'tutorial'."
    elif _re.search(r"\b(best|top\s+\d+|tools?|apps?|generators?|platforms?|software)\b", _topic, _re.I):
        topic_format_hint = "NOTE: The topic contains 'best/top/tools' keywords → FORMAT is almost certainly 'listicle'."
    else:
        topic_format_hint = ""

    return f"""Analyse the following data for the topic "{state['topic']}" (keyword: "{state['primary_keyword']}").

--- SERP TITLES & SNIPPETS ---
{competitor_details or "(no SERP data available)"}

--- PEOPLE ALSO ASK ---
{paa or "(none)"}
{scraped_block}
{topic_format_hint}
Your task — derive everything from the real data above:

1. FORMAT: What content structure dominates the actual results?
   Use scraped H2 headings and structural signals as primary evidence.
   - Numbered H2s ("Step 1...", "Step 2...") → tutorial
   - Multiple options compared side-by-side, comparison tables → comparison
   - "Top N", "Best X", one H2 per item → listicle
   - Conceptual H2s ("What is...", "How it works", "Why it matters") → explainer
   - Narrative H2s (problem/solution/result) → case_study

2. AUDIENCE: What vocabulary level and domain expertise do the pages assume?
   Use top_keywords and H2 language as evidence, not just domain names.

3. STRUCTURAL PATTERNS: Use the scraped data to state concrete facts.
   Good examples: "4/5 scraped pages have 6-9 H2 sections", "avg word count 1840",
   "3/5 pages use comparison tables", "common opening H2 pattern: 'What is X'".
   Derive at least 5 observations grounded in the actual numbers above.

4. COMPETITIVE ANGLE: What do ALL top results fail to cover?
   Look at what's missing from the common headings and secondary keywords.

5. WRITING STYLE: Describe vocabulary level and sentence structure precisely.
   Base this on readability scores and H2 language patterns, not assumptions.

6. SECTION COUNT: Use avg_h2_count from scraped data as the anchor.
   Suggested: {insights.suggested_section_count if insights else 6} sections (from scraped avg).

7. REQUIRED ELEMENTS: Only include elements you can justify from the scraped data
   (e.g. "has_table=True in 4/5 pages" justifies comparison_table)."""


async def content_classifier(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    logger.info(
        "[%s] content_classifier: analysing SERP structure for '%s'",
        job_id, state["topic"],
    )

    try:
        prompt = _build_prompt(state)
        brief: ContentBrief = await llm_service.call_llm(
            prompt=prompt,
            system=SYSTEM,
            response_model=ContentBrief,
            temperature=0.3,
            max_tokens=1500,
        )
        logger.info(
            "[%s] content_classifier: format=%s audience=%s sections=%d angle='%s'",
            job_id, brief.format, brief.audience,
            brief.suggested_section_count, brief.competitive_angle[:60],
        )
        job_manager.save_pipeline_artifact(job_id, "classification", {
            "format": brief.format,
            "audience": brief.audience,
            "tone": brief.tone,
            "required_elements": brief.required_elements,
            "structural_patterns": brief.structural_patterns,
            "competitive_angle": brief.competitive_angle,
            "writing_style_notes": brief.writing_style_notes,
            "suggested_section_count": brief.suggested_section_count,
            "rationale": brief.rationale,
        })
        return {"content_brief": brief, "status": JobStatus.RESEARCHING}

    except Exception as e:
        logger.exception("[%s] content_classifier failed — continuing without content brief", job_id)
        return {"content_brief": None, "status": JobStatus.RESEARCHING, "error": str(e)}
