"""
Node: faq_generator

Generates FAQ items from "People Also Ask" data and article content.
Runs as part of the DRAFTING phase.
"""

import logging

from pydantic import BaseModel

from app.models.article import FAQItem
from app.models.job import JobStatus
from app.models.state import SEOPipelineState
from app.services.job_manager import job_manager
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an SEO content expert. "
    "Generate concise, accurate FAQ answers that directly address the question. "
    "Answers should be 2–4 sentences, written in plain language, and naturally "
    "include relevant keywords where appropriate."
)


class _FAQList(BaseModel):
    items: list[FAQItem]


def _build_prompt(topic: str, people_also_ask: list[str], primary_keyword: str) -> str:
    questions = "\n".join(f"- {q}" for q in people_also_ask) if people_also_ask else (
        f"- What is {topic}?\n"
        f"- How do I get started with {topic}?\n"
        f"- What are the benefits of {topic}?\n"
        f"- What are common mistakes in {topic}?"
    )
    return f"""Generate FAQ answers for an article about "{topic}" (primary keyword: "{primary_keyword}").

Questions from search data:
{questions}

For each question write a clear, helpful answer of 2–4 sentences.
If the provided questions are fewer than 4, add 1–2 additional highly relevant questions and answer them.
Answers must be factually accurate and conversational in tone."""


async def faq_generator(state: SEOPipelineState) -> dict:
    job_id = state["job_id"]
    logger.info("[%s] faq_generator: generating FAQ", job_id)

    serp_data = state.get("serp_data")
    people_also_ask = serp_data.people_also_ask if serp_data else []

    try:
        prompt = _build_prompt(
            topic=state["topic"],
            people_also_ask=people_also_ask,
            primary_keyword=state["primary_keyword"],
        )
        result: _FAQList = await llm_service.call_llm(
            prompt=prompt,
            system=SYSTEM,
            response_model=_FAQList,
            temperature=0.5,
            max_tokens=2048,
        )
        logger.info("[%s] faq_generator: generated %d FAQ items", job_id, len(result.items))
        return {"faq": result.items, "status": JobStatus.DRAFTING}

    except Exception as e:
        logger.exception("[%s] faq_generator failed", job_id)
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
        return {"status": "drafting_failed", "error": str(e)}
