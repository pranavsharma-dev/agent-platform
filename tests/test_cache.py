import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cache import cache_get, cache_key, cache_set
from src.orchestrator import CachedResponse, Orchestrator, SpanData


class TestCacheKey:
    def test_deterministic_for_same_input(self):
        k1 = cache_key("plan", {"question": "What is 2+2?"})
        k2 = cache_key("plan", {"question": "What is 2+2?"})
        assert k1 == k2

    def test_different_for_different_step_type(self):
        k1 = cache_key("plan", {"question": "What is 2+2?"})
        k2 = cache_key("observe", {"question": "What is 2+2?"})
        assert k1 != k2

    def test_different_for_different_input(self):
        k1 = cache_key("plan", {"question": "What is 2+2?"})
        k2 = cache_key("plan", {"question": "What is 3+3?"})
        assert k1 != k2

    def test_key_order_independent(self):
        k1 = cache_key("plan", {"a": 1, "b": 2})
        k2 = cache_key("plan", {"b": 2, "a": 1})
        assert k1 == k2

    def test_has_cache_prefix(self):
        k = cache_key("plan", {"q": "test"})
        assert k.startswith("cache:")

    def test_sha256_length(self):
        k = cache_key("plan", {"q": "test"})
        hex_part = k[len("cache:"):]
        assert len(hex_part) == 64


class TestCacheGetSet:
    async def test_get_returns_none_when_no_pool(self):
        with patch("src.cache._pool", None):
            result = await cache_get("some-key")
            assert result is None

    async def test_set_does_nothing_when_no_pool(self):
        with patch("src.cache._pool", None):
            await cache_set("some-key", {"data": "value"})

    async def test_get_returns_none_on_miss(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        with patch("src.cache._pool", mock_redis):
            result = await cache_get("missing-key")
            assert result is None

    async def test_roundtrip(self):
        stored = {}
        mock_redis = AsyncMock()
        async def mock_set(key, value, ex=None):
            stored[key] = value
        async def mock_get(key):
            return stored.get(key)
        mock_redis.set = mock_set
        mock_redis.get = mock_get

        with patch("src.cache._pool", mock_redis):
            data = {"content": "test answer", "tokens_in": 100}
            await cache_set("test-key", data)
            result = await cache_get("test-key")
            assert result == data

    async def test_set_uses_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        with patch("src.cache._pool", mock_redis):
            await cache_set("k", {"v": 1}, ttl=7200)
            mock_redis.set.assert_called_once()
            call_kwargs = mock_redis.set.call_args
            assert call_kwargs.kwargs.get("ex") == 7200 or call_kwargs[1].get("ex") == 7200

    async def test_get_handles_redis_error_gracefully(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("src.cache._pool", mock_redis):
            result = await cache_get("key")
            assert result is None

    async def test_set_handles_redis_error_gracefully(self):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("src.cache._pool", mock_redis):
            await cache_set("key", {"data": "v"})


class TestSerializeResponse:
    def test_serializes_text_response(self):
        response = MagicMock()
        msg = MagicMock()
        msg.content = "The answer is 42"
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        choice.finish_reason = "stop"
        response.choices = [choice]

        result = Orchestrator._serialize_response(response, 100, 50)
        assert result == {
            "content": "The answer is 42",
            "tool_calls": None,
            "finish_reason": "stop",
            "tokens_in": 100,
            "tokens_out": 50,
        }

    def test_serializes_tool_call_response(self):
        response = MagicMock()
        msg = MagicMock()
        msg.content = None
        tc = MagicMock()
        tc.id = "call_01"
        tc.function = MagicMock()
        tc.function.name = "calculator"
        tc.function.arguments = '{"expression": "2+2"}'
        msg.tool_calls = [tc]
        choice = MagicMock()
        choice.message = msg
        choice.finish_reason = "tool_calls"
        response.choices = [choice]

        result = Orchestrator._serialize_response(response, 80, 30)
        assert result["finish_reason"] == "tool_calls"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "calculator"


class TestBuildMockResponse:
    def test_builds_text_response(self):
        cr = CachedResponse(
            content="The answer is 42",
            tool_calls=None,
            finish_reason="stop",
            tokens_in=100,
            tokens_out=50,
        )
        response = Orchestrator._build_mock_response(cr)
        assert response.choices[0].message.content == "The answer is 42"
        assert response.choices[0].message.tool_calls is None
        assert response.choices[0].finish_reason == "stop"
        assert response.usage.prompt_tokens == 100

    def test_builds_tool_call_response(self):
        cr = CachedResponse(
            content=None,
            tool_calls=[{"id": "c1", "name": "calculator", "arguments": '{"expression":"2+2"}'}],
            finish_reason="tool_calls",
            tokens_in=80,
            tokens_out=30,
        )
        response = Orchestrator._build_mock_response(cr)
        assert response.choices[0].finish_reason == "tool_calls"
        tc = response.choices[0].message.tool_calls[0]
        assert tc.function.name == "calculator"


class TestCacheIntegration:
    """Tests that the orchestrator uses cache correctly in its LLM call paths."""

    async def test_cache_miss_calls_llm_and_stores(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        answer_json = '{"answer": "42", "citations": [], "confidence": 0.9}'
        response = MagicMock()
        msg = MagicMock()
        msg.content = answer_json
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        choice.finish_reason = "stop"
        response.choices = [choice]
        response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

        orchestrator.client.chat.completions.create = AsyncMock(return_value=response)

        with patch("src.orchestrator.cache_get", new_callable=AsyncMock, return_value=None) as mock_get, \
             patch("src.orchestrator.cache_set", new_callable=AsyncMock) as mock_set:
            result = await orchestrator.run("What is 6*7?")

            assert result.answer == "42"
            mock_get.assert_called()
            mock_set.assert_called()
            orchestrator.client.chat.completions.create.assert_called()

    async def test_cache_hit_skips_llm_and_zero_cost(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock()

        cached_data = {
            "content": '{"answer": "42", "citations": [], "confidence": 0.9}',
            "tool_calls": None,
            "finish_reason": "stop",
            "tokens_in": 100,
            "tokens_out": 50,
        }

        with patch("src.orchestrator.cache_get", new_callable=AsyncMock, return_value=cached_data), \
             patch("src.orchestrator.cache_set", new_callable=AsyncMock):
            result = await orchestrator.run("What is 6*7?")

            assert result.answer == "42"
            orchestrator.client.chat.completions.create.assert_not_called()

    async def test_cache_hit_marks_span_as_cached(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock()

        cached_data = {
            "content": '{"answer": "cached", "citations": [], "confidence": 0.8}',
            "tool_calls": None,
            "finish_reason": "stop",
            "tokens_in": 50,
            "tokens_out": 25,
        }

        with patch("src.orchestrator.cache_get", new_callable=AsyncMock, return_value=cached_data), \
             patch("src.orchestrator.cache_set", new_callable=AsyncMock):
            from src.orchestrator import RunContext, State
            ctx = RunContext(question="test")
            ctx = await orchestrator._plan(ctx)

            plan_span = ctx.span_records[0]
            assert plan_span.cache_hit is True
            assert plan_span.cost_usd == Decimal("0")
            assert plan_span.tokens_in == 0
            assert plan_span.tokens_out == 0

    async def test_cache_hit_on_observe_step(self):
        from src.orchestrator import RunContext
        from src.tools.calculator import CalculatorTool

        calculator = CalculatorTool()
        orchestrator = Orchestrator(tools={"calculator": calculator})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        tool_call_response = MagicMock()
        tc_msg = MagicMock()
        tc_msg.content = None
        tc = MagicMock()
        tc.id = "call_1"
        tc.function = MagicMock()
        tc.function.name = "calculator"
        tc.function.arguments = '{"expression": "2+2"}'
        tc_msg.tool_calls = [tc]
        tc_choice = MagicMock()
        tc_choice.message = tc_msg
        tc_choice.finish_reason = "tool_calls"
        tool_call_response.choices = [tc_choice]
        tool_call_response.usage = MagicMock(prompt_tokens=80, completion_tokens=20)

        cached_observe = {
            "content": '{"answer": "4", "citations": [], "confidence": 0.99}',
            "tool_calls": None,
            "finish_reason": "stop",
            "tokens_in": 120,
            "tokens_out": 40,
        }

        with patch("src.orchestrator.cache_get", new_callable=AsyncMock) as mock_get, \
             patch("src.orchestrator.cache_set", new_callable=AsyncMock):
            orchestrator.client.chat.completions.create = AsyncMock(
                side_effect=[tool_call_response]
            )
            mock_get.side_effect = [None, cached_observe]

            result = await orchestrator.run("What is 2+2?")
            assert result.answer == "4"
            orchestrator.client.chat.completions.create.assert_called_once()

    async def test_full_cache_hit_run_has_zero_total_cost(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock()

        cached_data = {
            "content": '{"answer": "cached answer", "citations": [], "confidence": 0.95}',
            "tool_calls": None,
            "finish_reason": "stop",
            "tokens_in": 200,
            "tokens_out": 100,
        }

        with patch("src.orchestrator.cache_get", new_callable=AsyncMock, return_value=cached_data), \
             patch("src.orchestrator.cache_set", new_callable=AsyncMock):
            from src.orchestrator import RunContext
            ctx = RunContext(question="test cached")
            ctx = await orchestrator._plan(ctx)
            assert ctx.total_cost == Decimal("0")

    async def test_cache_miss_has_nonzero_cost(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        answer_json = '{"answer": "test", "citations": [], "confidence": 0.9}'
        response = MagicMock()
        msg = MagicMock()
        msg.content = answer_json
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        choice.finish_reason = "stop"
        response.choices = [choice]
        response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        orchestrator.client.chat.completions.create = AsyncMock(return_value=response)

        with patch("src.orchestrator.cache_get", new_callable=AsyncMock, return_value=None), \
             patch("src.orchestrator.cache_set", new_callable=AsyncMock):
            from src.orchestrator import RunContext
            ctx = RunContext(question="uncached")
            ctx = await orchestrator._plan(ctx)
            assert ctx.total_cost > Decimal("0")
            assert ctx.span_records[0].cache_hit is False
