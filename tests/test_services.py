"""
Tests for Phase 2 services: LLM service and SERP service.

Run:
    pytest tests/test_services.py -v
    pytest tests/test_services.py -v -k "TestExtractJson"   # single class
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from app.services.llm_service import LLMService, _extract_json, _structured_system
from app.services.serp_service import (
    SERPService,
    _extract_domain,
    _extract_themes,
    _is_retryable,
)
from app.models.serp import SERPData, SERPResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claude_response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    """Minimal mock of an Anthropic Messages response."""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = stop_reason
    return resp


def _make_openai_response(text: str) -> MagicMock:
    """Minimal mock of an OpenAI ChatCompletion response."""
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_llm_service() -> LLMService:
    """LLMService with both SDK clients replaced by AsyncMocks."""
    svc = LLMService.__new__(LLMService)
    svc._claude = AsyncMock()
    svc._openai = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_raw_json_object(self):
        assert _extract_json('{"a": 1}') == '{"a": 1}'

    def test_raw_nested_json(self):
        import json
        text = '{"a": {"b": {"c": 1}}}'
        assert json.loads(_extract_json(text)) == {"a": {"b": {"c": 1}}}

    def test_fenced_with_json_tag(self):
        text = "```json\n{\"key\": \"value\"}\n```"
        assert _extract_json(text) == '{"key": "value"}'

    def test_fenced_without_tag(self):
        text = "```\n{\"key\": \"value\"}\n```"
        assert _extract_json(text) == '{"key": "value"}'

    def test_fenced_nested_json(self):
        """Regression test for the non-greedy truncation bug."""
        import json
        text = "```json\n{\"sections\": [{\"heading\": \"Intro\", \"sub\": {\"key\": \"val\"}}]}\n```"
        result = json.loads(_extract_json(text))
        assert result["sections"][0]["sub"]["key"] == "val"

    def test_raw_nested_json_in_surrounding_text(self):
        import json
        text = 'Here is your result: {"outer": {"inner": 42}} — done.'
        assert json.loads(_extract_json(text)) == {"outer": {"inner": 42}}

    def test_no_json_returns_stripped_text(self):
        assert _extract_json("  just plain text  ") == "just plain text"

    def test_json_array(self):
        import json
        text = '[{"a": 1}, {"b": 2}]'
        assert json.loads(_extract_json(text)) == [{"a": 1}, {"b": 2}]

    def test_strips_js_line_comments(self):
        import json
        text = '{\n  "content": "hello world",\n  // This is a comment\n  "value": 42\n}'
        result = json.loads(_extract_json(text))
        assert result == {"content": "hello world", "value": 42}

    def test_preserves_urls_in_strings(self):
        import json
        text = '{"url": "https://example.com/path"}'
        result = json.loads(_extract_json(text))
        assert result["url"] == "https://example.com/path"


# ---------------------------------------------------------------------------
# LLMService
# ---------------------------------------------------------------------------

class TestLLMServiceTextResponse:
    @pytest.mark.asyncio
    async def test_returns_plain_text(self):
        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            return_value=_make_claude_response("Hello world")
        )
        result = await svc.call_llm("Say hello")
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_system_prompt_is_passed(self):
        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            return_value=_make_claude_response("ok")
        )
        await svc.call_llm("prompt", system="You are an SEO expert.")
        call_kwargs = svc._claude.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are an SEO expert."

    @pytest.mark.asyncio
    async def test_custom_model_is_forwarded(self):
        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            return_value=_make_claude_response("ok")
        )
        await svc.call_llm("prompt", model="claude-opus-4-6")
        call_kwargs = svc._claude.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"


class TestLLMServiceStructuredOutput:
    @pytest.mark.asyncio
    async def test_parses_pydantic_model(self):
        class Simple(BaseModel):
            name: str
            value: int

        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            return_value=_make_claude_response('{"name": "test", "value": 42}')
        )
        result = await svc.call_llm("Generate", response_model=Simple)
        assert isinstance(result, Simple)
        assert result.name == "test"
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_parses_nested_model_from_fenced_block(self):
        """Regression: nested JSON inside a code fence must not be truncated."""
        class Inner(BaseModel):
            key: str

        class Outer(BaseModel):
            inner: Inner

        svc = _make_llm_service()
        json_in_fence = "```json\n{\"inner\": {\"key\": \"val\"}}\n```"
        svc._claude.messages.create = AsyncMock(
            return_value=_make_claude_response(json_in_fence)
        )
        result = await svc.call_llm("Generate", response_model=Outer)
        assert isinstance(result, Outer)
        assert result.inner.key == "val"

    @pytest.mark.asyncio
    async def test_schema_is_appended_to_system_prompt(self):
        class Simple(BaseModel):
            name: str

        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            return_value=_make_claude_response('{"name": "x"}')
        )
        await svc.call_llm("prompt", system="Base system.", response_model=Simple)
        call_kwargs = svc._claude.messages.create.call_args.kwargs
        assert "Base system." in call_kwargs["system"]
        assert "name" in call_kwargs["system"]  # schema injected


class TestLLMServiceFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_openai_on_connection_error(self):
        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        svc._openai.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("OpenAI response")
        )
        result = await svc.call_llm("Say hello")
        assert result == "OpenAI response"

    @pytest.mark.asyncio
    async def test_falls_back_on_timeout(self):
        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )
        svc._openai.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("fallback")
        )
        result = await svc.call_llm("prompt")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_openai_not_called_when_claude_succeeds(self):
        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            return_value=_make_claude_response("from claude")
        )
        await svc.call_llm("prompt")
        svc._openai.chat.completions.create.assert_not_called()


class TestLLMServiceErrorCases:
    @pytest.mark.asyncio
    async def test_max_tokens_stop_reason_raises(self):
        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            return_value=_make_claude_response("truncated...", stop_reason="max_tokens")
        )
        with pytest.raises(RuntimeError, match="max_tokens"):
            await svc._call_claude("prompt", "", "claude-sonnet-4-6", None, 0.7, 100)

    @pytest.mark.asyncio
    async def test_empty_content_list_raises(self):
        svc = _make_llm_service()
        resp = MagicMock()
        resp.content = []
        resp.stop_reason = "end_turn"
        svc._claude.messages.create = AsyncMock(return_value=resp)
        with pytest.raises(RuntimeError, match="empty response"):
            await svc._call_claude("prompt", "", "claude-sonnet-4-6", None, 0.7, 100)

    @pytest.mark.asyncio
    async def test_openai_none_content_handled(self):
        """OpenAI can return None for message.content — must not crash."""
        svc = _make_llm_service()
        svc._claude.messages.create = AsyncMock(
            side_effect=httpx.ConnectError("down")
        )
        msg = MagicMock()
        msg.content = None  # OpenAI edge case
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        svc._openai.chat.completions.create = AsyncMock(return_value=resp)
        result = await svc.call_llm("prompt")
        assert result == ""


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------

class TestIsRetryable:
    def _http_error(self, status: int) -> httpx.HTTPStatusError:
        req = httpx.Request("GET", "https://serpapi.com")
        resp = httpx.Response(status, request=req)
        return httpx.HTTPStatusError(str(status), request=req, response=resp)

    def test_timeout_retryable(self):
        assert _is_retryable(httpx.TimeoutException("timeout"))

    def test_connect_error_retryable(self):
        assert _is_retryable(httpx.ConnectError("refused"))

    def test_429_retryable(self):
        assert _is_retryable(self._http_error(429))

    def test_500_retryable(self):
        assert _is_retryable(self._http_error(500))

    def test_502_retryable(self):
        assert _is_retryable(self._http_error(502))

    def test_503_retryable(self):
        assert _is_retryable(self._http_error(503))

    def test_504_retryable(self):
        assert _is_retryable(self._http_error(504))

    def test_401_not_retryable(self):
        assert not _is_retryable(self._http_error(401))

    def test_400_not_retryable(self):
        assert not _is_retryable(self._http_error(400))

    def test_404_not_retryable(self):
        assert not _is_retryable(self._http_error(404))

    def test_generic_exception_not_retryable(self):
        assert not _is_retryable(ValueError("unexpected"))


# ---------------------------------------------------------------------------
# _extract_domain
# ---------------------------------------------------------------------------

class TestExtractDomain:
    def test_strips_www(self):
        assert _extract_domain("https://www.example.com/path") == "example.com"

    def test_no_www(self):
        assert _extract_domain("https://backlinko.com/seo-tips") == "backlinko.com"

    def test_empty_url_returns_empty(self):
        assert _extract_domain("") == ""

    def test_subdomain_preserved(self):
        assert _extract_domain("https://blog.example.com/post") == "blog.example.com"


# ---------------------------------------------------------------------------
# _extract_themes
# ---------------------------------------------------------------------------

class TestExtractThemes:
    def _make_result(self, title: str, snippet: str, domain: str = "example.com") -> SERPResult:
        return SERPResult(position=1, title=title, url=f"https://{domain}", snippet=snippet, domain=domain)

    def test_extracts_guide_theme(self):
        results = [self._make_result("A complete guide to SEO", "comprehensive guide")]
        themes = _extract_themes(results)
        assert any("guide" in t.theme.lower() for t in themes)

    def test_empty_results_returns_empty(self):
        assert _extract_themes([]) == []

    def test_frequency_matches_number_of_matching_results(self):
        results = [
            self._make_result("guide one", "a guide", domain="a.com"),
            self._make_result("guide two", "a guide", domain="b.com"),
            self._make_result("guide three", "a guide", domain="c.com"),
        ]
        themes = _extract_themes(results)
        guide = next((t for t in themes if "guide" in t.theme.lower()), None)
        assert guide is not None
        assert guide.frequency == 3

    def test_sources_match_domains(self):
        results = [
            self._make_result("beginner tutorial", "for beginners", domain="a.com"),
            self._make_result("other title", "other snippet", domain="b.com"),
        ]
        themes = _extract_themes(results)
        beginner = next((t for t in themes if "beginner" in t.theme.lower()), None)
        assert beginner is not None
        assert "a.com" in beginner.sources
        assert "b.com" not in beginner.sources


# ---------------------------------------------------------------------------
# SERPService.mock_search
# ---------------------------------------------------------------------------

class TestMockSearch:
    @pytest.mark.asyncio
    async def test_is_async(self):
        """mock_search must be awaitable so test fixtures can swap it for search()."""
        svc = SERPService()
        data = await svc.mock_search("python seo")
        assert isinstance(data, SERPData)

    @pytest.mark.asyncio
    async def test_returns_10_results(self):
        svc = SERPService()
        data = await svc.mock_search("link building")
        assert len(data.results) == 10

    @pytest.mark.asyncio
    async def test_positions_are_sequential(self):
        svc = SERPService()
        data = await svc.mock_search("SEO")
        assert [r.position for r in data.results] == list(range(1, 11))

    @pytest.mark.asyncio
    async def test_query_is_preserved(self):
        svc = SERPService()
        data = await svc.mock_search("on-page SEO")
        assert data.query == "on-page SEO"

    @pytest.mark.asyncio
    async def test_has_people_also_ask(self):
        svc = SERPService()
        data = await svc.mock_search("keyword research")
        assert len(data.people_also_ask) > 0
        assert all(len(q) > 0 for q in data.people_also_ask)

    @pytest.mark.asyncio
    async def test_has_themes(self):
        svc = SERPService()
        data = await svc.mock_search("content marketing")
        assert len(data.themes) > 0
        assert all(t.frequency > 0 for t in data.themes)

    @pytest.mark.asyncio
    async def test_all_results_have_domains(self):
        svc = SERPService()
        data = await svc.mock_search("technical SEO")
        assert all(len(r.domain) > 0 for r in data.results)


# ---------------------------------------------------------------------------
# SERPService.search — no API key
# ---------------------------------------------------------------------------

class TestSearchWithoutKey:
    @pytest.mark.asyncio
    async def test_raises_runtime_error(self):
        svc = SERPService()
        with patch("app.services.serp_service.settings") as mock_settings:
            mock_settings.serpapi_key = ""
            with pytest.raises(RuntimeError, match="SERPAPI_KEY"):
                await svc.search("test query")

    @pytest.mark.asyncio
    async def test_error_message_mentions_mock_search(self):
        svc = SERPService()
        with patch("app.services.serp_service.settings") as mock_settings:
            mock_settings.serpapi_key = ""
            with pytest.raises(RuntimeError, match="mock_search"):
                await svc.search("test")


# ---------------------------------------------------------------------------
# SERPService retry behaviour
# ---------------------------------------------------------------------------

class TestRetryBehaviour:
    def _make_http_error(self, status: int) -> httpx.HTTPStatusError:
        req = httpx.Request("GET", "https://serpapi.com")
        resp = httpx.Response(status, request=req)
        return httpx.HTTPStatusError(str(status), request=req, response=resp)

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt_after_429(self):
        svc = SERPService()
        mock_data = await svc.mock_search("test")
        attempt = 0

        async def flaky_fetch(query: str) -> SERPData:
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise self._make_http_error(429)
            return mock_data

        with patch.object(svc, "_fetch", side_effect=flaky_fetch), \
             patch("app.services.serp_service.settings") as s, \
             patch("app.services.serp_service.asyncio.sleep", new_callable=AsyncMock):
            s.serpapi_key = "fake-key"
            result = await svc.search("test")

        assert attempt == 2
        assert isinstance(result, SERPData)

    @pytest.mark.asyncio
    async def test_raises_after_all_attempts_exhausted(self):
        svc = SERPService()
        attempt = 0

        async def always_fails(query: str) -> SERPData:
            nonlocal attempt
            attempt += 1
            raise self._make_http_error(500)

        with patch.object(svc, "_fetch", side_effect=always_fails), \
             patch("app.services.serp_service.settings") as s, \
             patch("app.services.serp_service.asyncio.sleep", new_callable=AsyncMock):
            s.serpapi_key = "fake-key"
            with pytest.raises(httpx.HTTPStatusError):
                await svc.search("test")

        assert attempt == 3  # all retries used

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately_no_retry(self):
        svc = SERPService()
        attempt = 0

        async def bad_key_fetch(query: str) -> SERPData:
            nonlocal attempt
            attempt += 1
            raise self._make_http_error(401)

        with patch.object(svc, "_fetch", side_effect=bad_key_fetch), \
             patch("app.services.serp_service.settings") as s:
            s.serpapi_key = "fake-key"
            with pytest.raises(httpx.HTTPStatusError):
                await svc.search("test")

        assert attempt == 1  # no retries for 401

    @pytest.mark.asyncio
    async def test_sleep_called_between_retries(self):
        svc = SERPService()
        mock_data = await svc.mock_search("test")
        attempt = 0

        async def two_failures(query: str) -> SERPData:
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise self._make_http_error(503)
            return mock_data

        mock_sleep = AsyncMock()
        with patch.object(svc, "_fetch", side_effect=two_failures), \
             patch("app.services.serp_service.settings") as s, \
             patch("app.services.serp_service.asyncio.sleep", mock_sleep):
            s.serpapi_key = "fake-key"
            await svc.search("test")

        assert mock_sleep.call_count == 2
        # Exponential backoff: 1s then 2s
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0]
