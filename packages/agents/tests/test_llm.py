"""LLMClient provider tests — mock the SDKs, never make a live API call."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel


class _Schema(BaseModel):
    pattern: str
    confidence: float


class TestClaudeProviderStructured:
    """Verify ClaudeProvider unpacks the tool_use block + records token telemetry."""

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-fake"})
    def test_structured_returns_validated_schema_from_tool_use_block(self, tmp_path) -> None:
        # Avoid disk-cache pollution — point the cache at a tmp dir for this test.
        with patch("agents.llm._cache") as mock_cache:
            mock_cache.get.return_value = None  # cache miss
            from agents.llm import ClaudeProvider

            with patch("anthropic.Anthropic") as MockAnthropic:
                # Build a fake response shaped like Anthropic's Message
                tool_use_block = MagicMock()
                tool_use_block.type = "tool_use"
                tool_use_block.input = {"pattern": "rename", "confidence": 0.92}
                response = MagicMock()
                response.content = [tool_use_block]
                response.usage.input_tokens = 100
                response.usage.output_tokens = 25
                response.usage.cache_read_input_tokens = 0
                response.usage.cache_creation_input_tokens = 0

                MockAnthropic.return_value.messages.create.return_value = response

                provider = ClaudeProvider(model="claude-haiku-4-5")
                result = provider.structured("system prompt", "user prompt", _Schema)

                assert isinstance(result, _Schema)
                assert result.pattern == "rename"
                assert result.confidence == 0.92
                # Token telemetry recorded
                assert provider.last_tokens_in == 100
                assert provider.last_tokens_out == 25
                assert provider.total_calls == 1
                assert provider.last_cache_hit is False

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-fake"})
    def test_structured_records_anthropic_cache_hit_when_cache_read_tokens_present(
        self, tmp_path
    ) -> None:
        with patch("agents.llm._cache") as mock_cache:
            mock_cache.get.return_value = None
            from agents.llm import ClaudeProvider

            with patch("anthropic.Anthropic") as MockAnthropic:
                tool_use_block = MagicMock()
                tool_use_block.type = "tool_use"
                tool_use_block.input = {"pattern": "concat", "confidence": 0.7}
                response = MagicMock()
                response.content = [tool_use_block]
                response.usage.input_tokens = 10
                response.usage.output_tokens = 20
                response.usage.cache_read_input_tokens = 500  # cache HIT
                response.usage.cache_creation_input_tokens = 0
                MockAnthropic.return_value.messages.create.return_value = response

                provider = ClaudeProvider(model="claude-haiku-4-5")
                provider.structured("sys", "user", _Schema)

                assert provider.last_cache_hit is True  # Anthropic prompt cache hit
                assert provider.total_cache_hits == 1
                # Total tokens include cached input
                assert provider.last_tokens_in == 510

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-fake"})
    def test_structured_returns_disk_cached_result_without_calling_anthropic(self) -> None:
        from agents.llm import ClaudeProvider, prompt_cache_key

        with patch("agents.llm._cache") as mock_cache:
            cached_payload = {"pattern": "derived", "confidence": 0.55}
            mock_cache.get.return_value = cached_payload

            with patch("anthropic.Anthropic") as MockAnthropic:
                provider = ClaudeProvider(model="claude-haiku-4-5")
                result = provider.structured("sys", "user", _Schema)

                # Cache hit -> no anthropic call
                MockAnthropic.return_value.messages.create.assert_not_called()
                assert result.pattern == "derived"
                assert provider.last_cache_hit is True  # disk-cache hit also counts


class TestClaudeProviderRequiresApiKey:
    def test_missing_anthropic_api_key_raises(self) -> None:
        from agents.llm import ClaudeProvider

        # Strip env to test the guard
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                ClaudeProvider()
