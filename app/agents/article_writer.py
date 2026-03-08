"""
Node: article_writer

Two generation strategies depending on article length:

  ≤2500 words → single-shot: one LLM call generates the full article. The complete
                outline skeleton (all H2/H3 headings + key points) is embedded upfront
                so the LLM sees the entire structure before writing — no context
                isolation, no hallucinated filler, no repeated talking points.

  >2500 words → multi-shot: each section is a separate LLM call, but always with
                the full skeleton AND a rolling window of already-written content to
                prevent repetition and maintain coherence.

Updates job status to DRAFTING.
"""

import logging
import re

from app.models.article import ArticleSection, HeadingLevel, OutlineSection
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service
from app.utils.text_utils import count_words, section_max_tokens

logger = logging.getLogger(__name__)

_SYSTEM_BASE = (
    "You are an expert content writer specialising in SEO-optimised articles. "
    "Write engaging, authoritative, and readable content. "
    "Integrate the primary keyword naturally — never keyword-stuff. "
    "Each section should flow logically from the previous one. "
    "Vary sentence length and structure — mix short punchy sentences with longer explanatory ones. "
    "Use specific examples, data points, and named tools/products — never vague placeholders. "
    "Write with a clear point of view — take positions and make recommendations. "
    "Avoid filler phrases like 'In today's world', 'It's important to note', or 'As we all know'. "
    "Open sections with a hook — a surprising fact, a question, or a bold claim."
)

_FORMAT_SYSTEM_SUFFIX = {
    "tutorial": (
        " You are writing a step-by-step technical tutorial. "
        "Use numbered lists for sequential steps. "
        "Include real tool names and concrete examples (not vague placeholders). "
        "Add ASCII architecture diagrams where they aid understanding. "
        "Include code snippets in markdown fences when showing implementation. "
        "Be specific — name actual technologies, providers, and APIs."
    ),
    "comparison": (
        " You are writing a comparison article. "
        "Be objective and data-driven. "
        "Use markdown tables to compare features side-by-side. "
        "Name real products with honest pros and cons. "
        "End sections with a clear recommendation for specific use cases."
    ),
    "listicle": (
        " You are writing a listicle. "
        "Each item needs a punchy opening sentence, concrete details, and a verdict. "
        "Name real tools and include specific reasons why each made the list. "
        "Avoid vague descriptions — be specific about what makes each item useful."
    ),
    "explainer": (
        " You are writing an explainer article. "
        "Use analogies to make abstract concepts concrete. "
        "Include ASCII diagrams to visualise architecture or flows. "
        "Define technical terms when first introduced. "
        "Build understanding progressively — simple to complex."
    ),
    "case_study": (
        " You are writing a case study. "
        "Ground every claim in a real or realistic scenario with named entities. "
        "Include metrics and measurable outcomes. "
        "Tell a narrative: problem → approach → result → lesson."
    ),
}


def _strip_duplicate_heading(content: str, heading: str) -> str:
    """Strip leading bold/plain/markdown heading text that duplicates the section heading.

    LLMs often repeat the heading in the content body in various forms:
    - **Heading** (bold)
    - ## Heading (markdown heading)
    - Plain heading text on its own line
    This causes it to render twice in the frontend.
    """
    patterns = [
        # ## Heading or ### Heading at the very start
        re.compile(r"^#{1,3}\s*" + re.escape(heading) + r"\s*\n?", re.IGNORECASE),
        # **Heading** or __Heading__ at start
        re.compile(r"^\*\*\s*" + re.escape(heading) + r"\s*\*\*\s*", re.IGNORECASE),
        re.compile(r"^__\s*" + re.escape(heading) + r"\s*__\s*", re.IGNORECASE),
        # Plain heading text on its own line at start
        re.compile(r"^" + re.escape(heading) + r"\s*\n", re.IGNORECASE),
    ]
    for p in patterns:
        content = p.sub("", content, count=1)
    return content.strip()


# Boilerplate headings LLMs hallucinate from website footer/nav training data.
# Used to filter out entire sections AND to truncate appended boilerplate in content.
_BOILERPLATE_HEADING_RE = re.compile(
    r"^("
    r"common mistakes|frequently asked|our editorial|editorial standards|"
    r"reviewed for accuracy|about the author|share this|related (posts|articles)|"
    r"leave a (comment|reply)|disclaimer|disclosure|"
    r"ai[- ]powered marketing is here"
    r")\b",
    re.IGNORECASE,
)

_BOILERPLATE_IN_CONTENT_RE = re.compile(
    r"^#{1,3}\s*("
    r"common mistakes|frequently asked|our editorial|editorial standards|"
    r"reviewed for accuracy|about the author|share this|related (posts|articles)|"
    r"leave a (comment|reply)|disclaimer|disclosure|"
    r"ai[- ]powered marketing is here"
    r")\b",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_boilerplate(text: str) -> str:
    """Truncate text at the first hallucinated boilerplate heading.

    Used for multi-shot section content where the LLM appends footer-like
    subsections (### Common Mistakes, ### FAQ, etc.) to the section body.
    """
    match = _BOILERPLATE_IN_CONTENT_RE.search(text)
    if match:
        text = text[:match.start()].rstrip()
    return text


def _is_boilerplate_section(heading: str) -> bool:
    """Check if a section heading matches a known boilerplate pattern."""
    return bool(_BOILERPLATE_HEADING_RE.match(heading.strip()))


def _parse_markdown_sections(markdown: str) -> list[ArticleSection]:
    """Split single-shot markdown into ArticleSection objects.

    Cleaning pipeline:
    1. Skip # (H1) headings — title is in metadata. Content under H1 → intro.
    2. Strip duplicate heading text (bold/## heading) from section content.
    3. Strip hallucinated boilerplate from each section's content.
    4. Deduplicate consecutive sections with the same heading (LLM outputs heading twice).
    """
    heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(markdown))

    raw_sections: list[ArticleSection] = []
    intro_parts: list[str] = []

    # Content before the first heading → intro
    if matches and matches[0].start() > 0:
        intro_parts.append(markdown[: matches[0].start()].strip())

    for idx, match in enumerate(matches):
        hashes = match.group(1)
        heading = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()

        # Skip H1 — title is stored separately in metadata. Treat its content as intro.
        if len(hashes) == 1:
            if content:
                intro_parts.append(content)
            continue

        # Strip leading bold/## text that duplicates the heading
        content = _strip_duplicate_heading(content, heading)
        # Strip boilerplate appended to this section's content
        content = _strip_boilerplate(content)

        level = HeadingLevel.H2 if len(hashes) == 2 else HeadingLevel.H3
        raw_sections.append(ArticleSection(
            heading=heading,
            level=level,
            content=content,
            word_count=count_words(content),
        ))

    # Step 3: filter out boilerplate sections (FAQ, Editorial Standards, etc.)
    raw_sections = [s for s in raw_sections if not _is_boilerplate_section(s.heading)]

    # Step 4: deduplicate consecutive sections with the same heading.
    # The LLM sometimes outputs "## Heading\n\n## Heading\nContent" which creates
    # two sections — one empty, one with content. Merge them.
    sections: list[ArticleSection] = []
    for s in raw_sections:
        if (
            sections
            and sections[-1].heading.lower() == s.heading.lower()
            and sections[-1].word_count < 10
        ):
            # Previous section is empty/near-empty duplicate — replace it
            sections[-1] = s
        else:
            sections.append(s)

    # Prepend collected intro text as the first section
    if intro_parts:
        intro_text = "\n\n".join(p for p in intro_parts if p)
        if intro_text:
            sections.insert(0, ArticleSection(
                heading="Introduction",
                level=HeadingLevel.H2,
                content=intro_text,
                word_count=count_words(intro_text),
            ))

    if not sections:
        sections.append(ArticleSection(
            heading="Article",
            level=HeadingLevel.H2,
            content=markdown,
            word_count=count_words(markdown),
        ))

    return sections



def _flatten_sections(sections: list[OutlineSection]) -> list[OutlineSection]:
    """Flatten nested outline into a sequential list (H2 → H3 → H3 → H2 …)."""
    flat: list[OutlineSection] = []
    for section in sections:
        flat.append(section)
        flat.extend(section.subsections)
    return flat



_SINGLE_SHOT_WORD_LIMIT = 2500  # articles at or below this use one LLM call


def _build_outline_skeleton(flat_sections: list[OutlineSection]) -> str:
    """Render the full outline as a readable skeleton with headings + key points."""
    lines: list[str] = []
    for s in flat_sections:
        prefix = "##" if s.level.value == "h2" else "###"
        lines.append(f"{prefix} {s.heading}")
        for kp in s.key_points[:3]:
            lines.append(f"   • {kp}")
    return "\n".join(lines)


def _build_single_shot_prompt(
    outline: "Outline",
    flat_sections: list[OutlineSection],
    topic: str,
    primary_keyword: str,
    target_word_count: int,
    content_format: str,
    brief: "ContentBrief | None",
    serp_context: str,
    gaps_context: str,
    required_elements: list[str],
) -> str:
    """One prompt that generates the complete article.

    The full outline skeleton is embedded upfront so the LLM sees all headings
    and key points before writing a single word — eliminating context isolation,
    hallucinated filler, and repetition across sections.
    """
    skeleton = _build_outline_skeleton(flat_sections)

    intro_words = min(180, target_word_count // 9)
    conclusion_words = min(120, target_word_count // 12)
    body_words = target_word_count - intro_words - conclusion_words
    body_sections = [s for s in flat_sections if s.level.value in ("h2", "h3")]
    words_per_section = max(100, body_words // max(1, len(body_sections)))

    style_block = ""
    if brief and brief.writing_style_notes:
        style_block = f"\nWRITING STYLE (from SERP analysis): {brief.writing_style_notes}"
    if brief and brief.competitive_angle:
        style_block += f"\nCOMPETITIVE ANGLE: {brief.competitive_angle}"

    element_hints = {
        "numbered_steps": "Use numbered lists for sequential steps.",
        "code_snippets": "Include code snippets in markdown fenced blocks.",
        "architecture_diagram": "Include ASCII diagrams for system/flow visualisation.",
        "comparison_table": "Include a markdown table to compare options.",
        "tool_list": "Name specific real tools with brief descriptions.",
        "real_examples": "Use concrete real-world examples with named tools or companies.",
        "pros_cons_list": "Include explicit pros and cons as bullet lists.",
        "metrics_data": "Include specific numbers, benchmarks, or performance data.",
    }
    elements_block = ""
    if required_elements:
        hints = [element_hints[e] for e in required_elements if e in element_hints]
        if hints:
            elements_block = "\nCONTENT ELEMENTS TO INCLUDE:\n" + "\n".join(f"- {h}" for h in hints)

    format_instructions = {
        "listicle": (
            "FORMAT — LISTICLE:\n"
            "Each ## section = one specific item (tool/strategy/agent/resource).\n"
            "Per item: opening sentence (what it is + primary use case) → **Key features** (3–4 bullet points, specific capabilities) → **Best for** (one line) → **Pricing** (optional, only if known).\n"
            "No generic items. No invented case studies. No fake statistics."
        ),
        "tutorial": (
            "FORMAT — TUTORIAL:\n"
            "Use numbered steps for any sequential process. Name real tools and APIs.\n"
            "Each section should be actionable — reader can follow along."
        ),
        "comparison": (
            "FORMAT — COMPARISON:\n"
            "Use markdown tables to compare options. State pros and cons explicitly.\n"
            "End with a clear recommendation for specific use cases."
        ),
        "explainer": (
            "FORMAT — EXPLAINER:\n"
            "Use analogies to make abstract concepts concrete. Define technical terms on first use.\n"
            "Build understanding progressively — simple to complex."
        ),
        "case_study": (
            "FORMAT — CASE STUDY:\n"
            "Ground every claim in a real or realistic scenario. Include metrics.\n"
            "Narrative arc: problem → approach → result → lesson."
        ),
    }
    format_block = format_instructions.get(content_format, "")

    gaps_block = f"\nCONTENT GAPS (topics competitors miss — weave in naturally):\n{gaps_context}" if gaps_context else ""
    serp_block = f"\nCOMPETITOR CONTEXT (angles already covered):\n{serp_context}" if serp_context else ""

    return f"""Write a complete {target_word_count}-word article using the outline below.

TOPIC: "{topic}"
PRIMARY KEYWORD: "{primary_keyword}" — use the exact phrase once in the opening paragraph, then use natural variations throughout (plural forms, rephrasing, synonyms). Do NOT repeat the exact same phrase more than 2–3 times total.
TITLE: {outline.title}

COMPLETE OUTLINE — write every section in this exact order, covering the key points listed:
{skeleton}

WORD BUDGET:
- Opening paragraph / intro: ~{intro_words} words
- Each section (~{words_per_section} words each)
- Conclusion: ~{conclusion_words} words
- Total: {target_word_count} words{style_block}

{format_block}{elements_block}{serp_block}{gaps_block}

UNIVERSAL RULES:
- Follow the outline exactly — do not add, remove, or reorder sections.
- Each section must address its listed key points (shown as bullets above).
- Write each ## heading ONCE only. Do not repeat the heading as bold text in the section body.
- Do NOT include a # (H1) title heading — the title is stored separately.
- No invented statistics ("studies show 60%", "experts say") without citing a real named source + year.
- No fake testimonials, fabricated case studies, or made-up user quotes.
- No filler openers: "In today's digital landscape", "It's worth noting", "As we all know".
- No generic closers per section: "Overall a great option", "Definitely worth trying".
- Do NOT add boilerplate sections like "Common Mistakes to Avoid", "Frequently Asked Questions", "Our Editorial Standards", "Reviewed for Accuracy", or "About the Author". Write ONLY the outline sections.
- Use markdown: ## for H2 sections, ### for H3, **bold** for key terms, bullet/numbered lists.
- Be specific — name real tools, real companies, real capabilities.
- Stop at {target_word_count} words. Do not pad to hit the count."""


def _build_section_with_context_prompt(
    section: OutlineSection,
    topic: str,
    primary_keyword: str,
    target_words: int,
    total_target_words: int,
    full_skeleton: str,
    written_so_far: str,
    serp_context: str,
    is_first: bool,
    content_format: str,
    required_elements: list[str],
    gaps_context: str,
) -> str:
    """Prompt for one section that includes the full outline + already-written content.

    Used for long articles (>2500 words) where single-shot isn't feasible.
    The writer sees the complete structure and what's already been written,
    preventing repetition and hallucination.
    """
    key_points = "\n".join(f"  • {p}" for p in section.key_points)
    min_w, max_w = int(target_words * 0.85), int(target_words * 1.15)
    intro_note = (
        f'IMPORTANT: This is the OPENING section — first paragraph must include the primary keyword "{primary_keyword}" naturally.\n'
        if is_first else ""
    )
    written_block = (
        f"\nALREADY WRITTEN (do not repeat these topics):\n{written_so_far[-1500:]}\n"
        if written_so_far else ""
    )
    element_hints = {
        "numbered_steps": "Use numbered lists for any sequential process.",
        "code_snippets": "Include a fenced code block if it illustrates the concept.",
        "comparison_table": "Include a markdown table if comparing options.",
        "real_examples": "Use a concrete real-world example with a named tool or company.",
    }
    elements = "\n".join(
        f"- {element_hints[e]}" for e in required_elements if e in element_hints
    )
    elements_block = f"\nRequired elements:\n{elements}" if elements else ""

    format_notes = {
        "listicle": "This item needs: specific opening sentence → **Key features** (3–4 bullets) → **Best for** (one line). No fake stats.",
        "tutorial": "Use numbered steps if describing a process. Name real tools and providers.",
        "comparison": "State pros and cons explicitly. Use a table if comparing multiple options.",
        "explainer": "Use an analogy or ASCII diagram if it clarifies. Define terms on first use.",
        "case_study": "Concrete scenario, named entities, measurable outcome.",
    }
    format_note = f"\nFormat: {format_notes[content_format]}" if content_format in format_notes else ""

    return f"""Write the section below for an article about "{topic}".

FULL ARTICLE OUTLINE (for context — follow this structure, do not deviate):
{full_skeleton}

NOW WRITE:
Section: {section.heading} ({section.level.value.upper()})
Key points to cover:
{key_points}
{intro_note}{format_note}{elements_block}

WORD COUNT: {min_w}–{max_w} words. Stop at {max_w}.
Primary keyword: "{primary_keyword}" — use natural variations (plural, rephrased). Do NOT repeat the exact phrase in every section.{written_block}

Rules:
- Do NOT include the section heading in your response — no ## heading, no **bold heading**, no plain heading at the start.
- Do NOT append boilerplate like "Common Mistakes", "FAQ", "Editorial Standards", or "Reviewed for Accuracy".
- No invented statistics without a real named source.
- No fake testimonials or case studies.
- No filler openers or generic closers.
- Be specific — real tools, real capabilities, precise language."""


async def article_writer(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    job_manager.update_status(job_id, JobStatus.DRAFTING)

    outline = state["outline"]
    serp_data = state["serp_data"]
    primary_keyword = state["primary_keyword"]
    target_word_count = state["target_word_count"]
    brief = state.get("content_brief")
    content_format = brief.format if brief else "explainer"
    required_elements = brief.required_elements if brief else []

    system = _SYSTEM_BASE + _FORMAT_SYSTEM_SUFFIX.get(content_format, "")
    if brief and brief.writing_style_notes:
        system = (
            _SYSTEM_BASE
            + f"\n\nWRITING STYLE (from SERP analysis): {brief.writing_style_notes}"
            + f"\nCOMPETITIVE ANGLE: {brief.competitive_angle}"
            + _FORMAT_SYSTEM_SUFFIX.get(content_format, "")
        )

    flat_sections = _flatten_sections(outline.sections)
    full_skeleton = _build_outline_skeleton(flat_sections)

    # SERP context
    serp_parts: list[str] = []
    if serp_data:
        serp_parts.extend(f"- {r.title}: {r.snippet}" for r in serp_data.results[:5])
        if serp_data.people_also_ask:
            serp_parts.append("\nQuestions people ask:")
            serp_parts.extend(f"- {q}" for q in serp_data.people_also_ask)
    serp_context = "\n".join(serp_parts)

    gaps_context = "\n".join(
        f"- [{g.priority.upper()}] {g.topic}: {g.reason}"
        for g in (state.get("content_gaps") or [])
    )

    draft_sections: list[ArticleSection] = []

    try:
        # ── SINGLE-SHOT path (≤2500 words) ──────────────────────────────────────
        # The full article is generated in one LLM call. The complete outline
        # skeleton is embedded upfront so the LLM sees all headings and key points
        # before writing anything — no context isolation, no hallucinated structure.
        if target_word_count <= _SINGLE_SHOT_WORD_LIMIT:
            logger.info(
                "[%s] article_writer: single-shot generation (%d words, format=%s)",
                job_id, target_word_count, content_format,
            )
            prompt = _build_single_shot_prompt(
                outline=outline,
                flat_sections=flat_sections,
                topic=state["topic"],
                primary_keyword=primary_keyword,
                target_word_count=target_word_count,
                content_format=content_format,
                brief=brief,
                serp_context=serp_context,
                gaps_context=gaps_context,
                required_elements=required_elements,
            )
            full_text: str = await llm_service.call_llm(
                prompt=prompt,
                system=system,
                response_model=None,
                temperature=0.7,
                max_tokens=section_max_tokens(target_word_count),
            )
            draft_sections = _parse_markdown_sections(full_text)
            logger.info(
                "[%s] article_writer: single-shot complete — %d sections, ~%d words",
                job_id, len(draft_sections), sum(s.word_count for s in draft_sections),
            )

        # ── MULTI-SHOT path (>2500 words) ────────────────────────────────────────
        # Each H2 section is written separately, but always with:
        #   1. The full outline skeleton (all headings visible)
        #   2. A rolling window of already-written content (prevents repetition)
        else:
            h2_count = sum(1 for s in flat_sections if s.level.value == "h2")
            h3_count = len(flat_sections) - h2_count
            total_weight = max(1, h2_count * 1.0 + h3_count * 0.6)
            words_per_h2 = max(150, int(target_word_count / total_weight))
            words_per_h3 = max(100, int(target_word_count * 0.6 / total_weight))

            logger.info(
                "[%s] article_writer: multi-shot generation (%d words, %d sections, format=%s)",
                job_id, target_word_count, len(flat_sections), content_format,
            )
            written_so_far = ""
            for i, section in enumerate(flat_sections):
                is_h2 = section.level.value == "h2"
                section_target = words_per_h2 if is_h2 else words_per_h3
                logger.info(
                    "[%s] article_writer: section %d/%d — %s (~%d words)",
                    job_id, i + 1, len(flat_sections), section.heading, section_target,
                )
                prompt = _build_section_with_context_prompt(
                    section=section,
                    topic=state["topic"],
                    primary_keyword=primary_keyword,
                    target_words=section_target,
                    total_target_words=target_word_count,
                    full_skeleton=full_skeleton,
                    written_so_far=written_so_far,
                    serp_context=serp_context,
                    is_first=(i == 0),
                    content_format=content_format,
                    required_elements=required_elements,
                    gaps_context=gaps_context,
                )
                section_text: str = await llm_service.call_llm(
                    prompt=prompt,
                    system=system,
                    response_model=None,
                    temperature=0.7,
                    max_tokens=section_max_tokens(section_target),
                )
                # Clean up: strip heading if LLM repeated it, strip boilerplate
                section_text = _strip_duplicate_heading(section_text, section.heading)
                section_text = _strip_boilerplate(section_text)
                draft_sections.append(ArticleSection(
                    heading=section.heading,
                    level=section.level,
                    content=section_text,
                    word_count=count_words(section_text),
                ))
                # Keep a rolling summary of what's been written for the next prompt
                written_so_far += f"\n\n## {section.heading}\n{section_text[:400]}"

        total_words = sum(s.word_count for s in draft_sections)
        logger.info("[%s] article_writer: done — %d words, %d sections", job_id, total_words, len(draft_sections))
        job_manager.save_pipeline_artifact(job_id, "draft", {
            "total_words": total_words,
            "content_format": content_format,
            "generation_mode": "single_shot" if target_word_count <= _SINGLE_SHOT_WORD_LIMIT else "multi_shot",
            "sections": [
                {"heading": s.heading, "level": s.level.value,
                 "word_count": s.word_count, "content": s.content}
                for s in draft_sections
            ],
        })
        return {"draft_sections": draft_sections, "status": JobStatus.DRAFTING}

    except Exception as e:
        logger.exception("[%s] article_writer failed", job_id)
        if draft_sections:
            return {"draft_sections": draft_sections, "status": JobStatus.DRAFTING}
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "drafting_failed", "error": str(e)}
