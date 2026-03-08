"""Tests for core/llm_client.py — Torri proxy gateway.

Covers: successful calls, retry on 429, retry on 5xx, timeout handling,
response parsing, token tracking, and tool-call parsing.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.exceptions import LLMCallError, LLMRateLimitError, LLMTimeoutError
from core.llm_client import LLMClient, LLMResponse


@pytest.fixture
def client_config():
    return {
        "base_url": "https://torri.example.com/v1",
        "api_key": "test-key",
        "model": "gpt-4o",
        "max_tokens": 1024,
        "temperature": 0,
        "timeout_seconds": 30,
        "max_retries": 2,
        "retry_delay_seconds": 0.1,
    }


@pytest.fixture
def client(client_config):
    return LLMClient(client_config)


def _mock_response(content: str, status_code: int = 200, usage: dict | None = None):
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = {}
    body = {
        "choices": [{"message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        "model": "gpt-4o",
    }
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


class TestLLMClientCall:
    """Test the basic call() method."""

    @patch.object(requests.Session, "post")
    def test_successful_call(self, mock_post, client):
        mock_post.return_value = _mock_response("Hello, world!")

        resp = client.call(
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )

        assert isinstance(resp, LLMResponse)
        assert resp.content == "Hello, world!"
        assert resp.usage["total_tokens"] == 150
        assert resp.model == "gpt-4o"
        assert resp.latency_ms > 0

    @patch.object(requests.Session, "post")
    def test_system_prompt_prepended(self, mock_post, client):
        mock_post.return_value = _mock_response("OK")

        client.call(
            system_prompt="System prompt here.",
            messages=[{"role": "user", "content": "Hello"}],
        )

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == "System prompt here."
        assert payload["messages"][1]["role"] == "user"

    @patch.object(requests.Session, "post")
    def test_json_response_format(self, mock_post, client):
        mock_post.return_value = _mock_response('{"key": "value"}')

        client.call(
            system_prompt="Return JSON.",
            messages=[{"role": "user", "content": "data"}],
            response_format="json",
        )

        payload = mock_post.call_args[1]["json"]
        assert payload["response_format"] == {"type": "json_object"}

    @patch.object(requests.Session, "post")
    def test_token_tracking(self, mock_post, client):
        mock_post.return_value = _mock_response("A")
        client.call(system_prompt="S", messages=[{"role": "user", "content": "Q"}])
        mock_post.return_value = _mock_response("B", usage={"total_tokens": 200})
        client.call(system_prompt="S", messages=[{"role": "user", "content": "Q"}])

        assert client.stats["total_calls"] == 2
        assert client.stats["total_tokens"] == 350


class TestLLMClientRetry:
    """Test retry logic on 429 and 5xx errors."""

    @patch.object(requests.Session, "post")
    def test_retry_on_429(self, mock_post, client):
        """Should retry on rate limit, then succeed."""
        rate_limit_resp = MagicMock(spec=requests.Response)
        rate_limit_resp.status_code = 429
        rate_limit_resp.headers = {"Retry-After": "0.1"}
        rate_limit_resp.text = "Rate limited"

        success_resp = _mock_response("Succeeded after retry")

        mock_post.side_effect = [rate_limit_resp, success_resp]

        resp = client.call(system_prompt="S", messages=[{"role": "user", "content": "Q"}])
        assert resp.content == "Succeeded after retry"
        assert mock_post.call_count == 2

    @patch.object(requests.Session, "post")
    def test_retry_exhaustion_on_429(self, mock_post, client):
        """Should raise after max retries."""
        rate_limit_resp = MagicMock(spec=requests.Response)
        rate_limit_resp.status_code = 429
        rate_limit_resp.headers = {}
        rate_limit_resp.text = "Rate limited"

        mock_post.return_value = rate_limit_resp

        with pytest.raises(LLMRateLimitError):
            client.call(system_prompt="S", messages=[{"role": "user", "content": "Q"}])

    @patch.object(requests.Session, "post")
    def test_error_on_5xx(self, mock_post, client):
        """Should raise on server errors."""
        error_resp = MagicMock(spec=requests.Response)
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"

        mock_post.return_value = error_resp

        with pytest.raises(LLMCallError):
            client.call(system_prompt="S", messages=[{"role": "user", "content": "Q"}])


class TestLLMClientTimeout:
    """Test timeout handling."""

    @patch.object(requests.Session, "post")
    def test_timeout_raises(self, mock_post, client):
        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

        with pytest.raises(LLMTimeoutError):
            client.call(system_prompt="S", messages=[{"role": "user", "content": "Q"}])


class TestLLMClientParsing:
    """Test response parsing."""

    @patch.object(requests.Session, "post")
    def test_empty_choices_raises(self, mock_post, client):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.json.return_value = {"choices": [], "usage": {}}

        mock_post.return_value = resp

        with pytest.raises(LLMCallError, match="Empty choices"):
            client.call(system_prompt="S", messages=[{"role": "user", "content": "Q"}])

    @patch.object(requests.Session, "post")
    def test_tool_call_parsing(self, mock_post, client):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "file_tool",
                            "arguments": '{"action": "read", "filepath": "main.py"}',
                        },
                    }],
                },
            }],
            "usage": {"total_tokens": 100},
            "model": "gpt-4o",
        }
        mock_post.return_value = resp

        result = client.call_with_tools(
            system_prompt="S",
            messages=[{"role": "user", "content": "Q"}],
            tools=[],
        )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "file_tool"
        assert result.tool_calls[0]["arguments"]["action"] == "read"
