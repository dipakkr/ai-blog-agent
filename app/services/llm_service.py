import json
import logging
import re
from typing import Optional, Type, TypeVar, Union

import anthropic
import openai
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _strip_js_comments(text: str) -> str:
    """Remove JavaScript-style // line comments from JSON text.

    LLMs (especially OpenAI fallback) sometimes include // comments in JSON
    output, which is invalid JSON. This strips them while preserving strings
    that contain // (e.g. URLs).
    """
    # Remove single-line // comments that are NOT inside quoted strings.
    # Strategy: match strings first (to skip them), then strip comments.
    return re.sub(
        r'("(?:[^"\\]|\\.)*")|//[^\n]*',
        lambda m: m.group(1) if m.group(1) else "",
        text,
    )


def _extract_json(text: str) -> str:
    """Extract the outermost JSON object or array from text.

    Handles:
    - Raw JSON
    - JSON wrapped in ```json ... ``` or ``` ... ``` fences
    - JSON with JavaScript-style // comments (stripped before extraction)
    Uses greedy matching to correctly capture nested objects/arrays.
    """
    # Strip fences first, then search for JSON in the remainder
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    search_text = fenced.group(1) if fenced else text

    # Strip JS-style comments that LLMs sometimes include
    search_text = _strip_js_comments(search_text)

    # Greedy match — captures full nested structure
    raw = re.search(r"(\{.*\}|\[.*\])", search_text, re.DOTALL)
    if raw:
        return raw.group(1).strip()
    return search_text.strip()


def _structured_system(system: str, response_model: Type[BaseModel]) -> str:
    schema = json.dumps(response_model.model_json_schema(), indent=2)
    suffix = (
        f"\n\nYou MUST respond with a single JSON object whose fields are filled "
        f"with real values based on the user's request. "
        f"Do NOT return the schema itself. Do NOT return example placeholders. "
        f"Do NOT wrap in markdown. Output only the filled JSON object.\n\n"
        f"Required JSON structure:\n{schema}"
    )
    return f"{system}{suffix}".strip()


class LLMService:
    def __init__(self) -> None:
        self._claude = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=60.0,  # prevent indefinite hangs on API degradation
        )
        self._openai = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    async def call_llm(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        response_model: Optional[Type[T]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Union[str, T]:
        """Call Claude (primary). Falls back to OpenAI on any exception.

        Args:
            prompt: The user message.
            system: System prompt. If response_model is set, the JSON schema
                    is appended automatically — do not add it manually.
            model: Override the primary model. Defaults to settings.primary_llm.
            response_model: Pydantic model to parse the response into.
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.

        Returns:
            Parsed Pydantic instance if response_model is set, else raw string.
        """
        active_model = model or settings.primary_llm
        try:
            return await self._call_claude(
                prompt=prompt,
                system=system,
                model=active_model,
                response_model=response_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.warning(
                "Claude call failed (model=%s, error=%s: %s) — falling back to %s",
                active_model,
                type(e).__name__,
                e,
                settings.fallback_llm,
            )
            return await self._call_openai(
                prompt=prompt,
                system=system,
                model=settings.fallback_llm,
                response_model=response_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    async def _call_claude(
        self,
        prompt: str,
        system: str,
        model: str,
        response_model: Optional[Type[T]],
        temperature: float,
        max_tokens: int,
    ) -> Union[str, T]:
        effective_system = (
            _structured_system(system, response_model) if response_model else system
        )
        response = await self._claude.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=effective_system,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"Claude response truncated (max_tokens={max_tokens} reached). "
                "Increase max_tokens for this call."
            )
        if not response.content:
            raise RuntimeError("Claude returned an empty response content list.")
        text = response.content[0].text.strip()
        if response_model:
            return response_model.model_validate_json(_extract_json(text))
        return text

    async def _call_openai(
        self,
        prompt: str,
        system: str,
        model: str,
        response_model: Optional[Type[T]],
        temperature: float,
        max_tokens: int,
    ) -> Union[str, T]:
        effective_system = (
            _structured_system(system, response_model) if response_model else system
        )
        messages: list[dict] = []
        if effective_system:
            messages.append({"role": "system", "content": effective_system})
        messages.append({"role": "user", "content": prompt})

        response = await self._openai.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        text = (response.choices[0].message.content or "").strip()
        if response_model:
            return response_model.model_validate_json(_extract_json(text))
        return text


llm_service = LLMService()
