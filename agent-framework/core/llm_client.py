"""Single LLM gateway — every LLM call in the application routes through here.

Communicates with the Torri corporate proxy which exposes an OpenAI-compatible
chat-completions API.  Handles retries, timeouts, token tracking, and
structured logging so that no other module needs to know HTTP details.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.exceptions import LLMCallError, LLMRateLimitError, LLMTimeoutError
from core.logger import LogContext, get_logger

logger = get_logger("llm_client")


@dataclass
class LLMResponse:
    """Structured response from a Torri proxy call."""

    content: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0
    model: str = ""
    raw: dict = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)


class LLMClient:
    """OpenAI-compatible chat-completions client for the Torri proxy.

    Parameters
    ----------
    config : dict
        The ``torri`` section of config.yaml.  Required keys:
        ``base_url``, ``api_key``, ``model``.
    """

    def __init__(self, config: dict) -> None:
        self.base_url = config["base_url"].rstrip("/")
        self.api_key = config["api_key"]
        self.model = config.get("model", "gpt-4o")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0)
        self.timeout = config.get("timeout_seconds", 120)
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay_seconds", 2)

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

        # Running totals for observability
        self._total_calls = 0
        self._total_tokens = 0

    # ── Public API ──────────────────────────────────────────────────────

    def call(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: str = "text",
        correlation_id: str | None = None,
    ) -> LLMResponse:
        """Make a single chat-completion call through the Torri proxy.

        Parameters
        ----------
        system_prompt:
            Injected as the first ``system`` message.
        messages:
            List of ``{"role": "...", "content": "..."}`` dicts.
        temperature:
            Sampling temperature override (default: instance default).
        max_tokens:
            Max response tokens override.
        response_format:
            ``"text"`` (default) or ``"json"`` (requests JSON mode).
        correlation_id:
            Optional ID for log correlation.

        Returns
        -------
        LLMResponse
        """
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        return self._send(payload, correlation_id)

    def call_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        tools: list[dict],
        correlation_id: str | None = None,
    ) -> LLMResponse:
        """Chat-completion call with OpenAI function-calling tools.

        Parameters
        ----------
        tools:
            List of tool definitions in OpenAI function-calling format.
        """
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "tools": tools,
        }
        return self._send(payload, correlation_id)

    # ── Internals ───────────────────────────────────────────────────────

    def _send(self, payload: dict, correlation_id: str | None) -> LLMResponse:
        """Send request with retry, timeout, and structured logging."""
        url = f"{self.base_url}/chat/completions"
        log_ctx = LogContext(correlation_id=correlation_id or "", agent="llm_client")

        prompt_chars = sum(len(m.get("content", "")) for m in payload["messages"])

        start = time.time()
        try:
            response = self._request_with_retry(url, payload)
        except LLMCallError:
            raise
        except requests.exceptions.Timeout as exc:
            raise LLMTimeoutError(
                f"Request timed out after {self.timeout}s",
                timeout_seconds=self.timeout,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise LLMCallError(f"HTTP error: {exc}") from exc

        latency_ms = (time.time() - start) * 1000
        body = response.json()

        # Parse response
        llm_resp = self._parse_response(body, latency_ms)

        # Track totals
        self._total_calls += 1
        self._total_tokens += llm_resp.usage.get("total_tokens", 0)

        # Structured log
        log_ctx.llm_call(
            prompt_len=prompt_chars,
            response_len=len(llm_resp.content),
            tokens=llm_resp.usage.get("total_tokens", 0),
            duration_ms=latency_ms,
        )
        return llm_resp

    @retry(
        retry=retry_if_exception_type(LLMRateLimitError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _request_with_retry(self, url: str, payload: dict) -> requests.Response:
        """POST with automatic retry on 429 / 5xx."""
        resp = self._session.post(url, json=payload, timeout=self.timeout)

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", self.retry_delay))
            raise LLMRateLimitError(retry_after=retry_after)

        if resp.status_code >= 500:
            raise LLMCallError(
                f"Server error {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        if resp.status_code != 200:
            raise LLMCallError(
                f"Unexpected status {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        return resp

    @staticmethod
    def _parse_response(body: dict, latency_ms: float) -> LLMResponse:
        """Extract content and metadata from the API response body."""
        choices = body.get("choices", [])
        if not choices:
            raise LLMCallError("Empty choices in LLM response", details=body)

        message = choices[0].get("message", {})
        content = message.get("content", "") or ""

        # Handle tool calls (function calling)
        tool_calls: list[dict] = []
        raw_tool_calls = message.get("tool_calls", [])
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {"_raw": args_str}
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "arguments": args,
            })

        usage = body.get("usage", {})
        model = body.get("model", "")

        return LLMResponse(
            content=content,
            usage=usage,
            latency_ms=latency_ms,
            model=model,
            raw=body,
            tool_calls=tool_calls,
        )

    # ── Observability ───────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, int]:
        return {"total_calls": self._total_calls, "total_tokens": self._total_tokens}
