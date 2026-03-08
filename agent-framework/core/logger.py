"""Structured logging with correlation IDs.

Provides both human-readable console output (via Rich) and machine-parseable
JSON file output for observability and replay.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any


class StructuredFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach any extra structured fields
        for key in ("correlation_id", "agent", "tool", "duration_ms",
                     "tokens", "prompt_len", "response_len", "stage"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class PlainFormatter(logging.Formatter):
    """Human-readable console format with optional colour support."""

    FMT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
    DATEFMT = "%H:%M:%S"

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, datefmt=self.DATEFMT)


def setup_logging(config: dict) -> logging.Logger:
    """Initialise the root logger from the config dict.

    Parameters
    ----------
    config:
        ``logging`` section of config.yaml — expects keys
        ``level``, ``format`` ("structured"|"plain"), and ``file``.
    """
    level_name = config.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = config.get("format", "structured")
    log_file = config.get("file", "./logs/agent.log")

    root = logging.getLogger("agent")
    root.setLevel(level)
    root.handlers.clear()

    # Console handler — always plain for readability
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(PlainFormatter())
    root.addHandler(console)

    # File handler — structured JSON by default
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
    file_handler.setLevel(level)
    if fmt == "structured":
        file_handler.setFormatter(StructuredFormatter())
    else:
        file_handler.setFormatter(PlainFormatter())
    root.addHandler(file_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``agent`` namespace."""
    return logging.getLogger(f"agent.{name}")


class LogContext:
    """Convenience helper for emitting structured log entries.

    Usage::

        ctx = LogContext(correlation_id="abc123", agent="coder_agent")
        ctx.info("Starting implementation", stage="code")
        ctx.tool_call("file_tool", duration_ms=12, success=True)
        ctx.llm_call(prompt_len=400, response_len=1200, tokens=1600, duration_ms=3400)
    """

    def __init__(self, correlation_id: str = "", agent: str = ""):
        self._logger = get_logger(agent or "system")
        self._defaults: dict[str, Any] = {}
        if correlation_id:
            self._defaults["correlation_id"] = correlation_id
        if agent:
            self._defaults["agent"] = agent

    def _log(self, level: int, msg: str, **extra: Any) -> None:
        merged = {**self._defaults, **extra}
        self._logger.log(level, msg, extra=merged)

    def debug(self, msg: str, **extra: Any) -> None:
        self._log(logging.DEBUG, msg, **extra)

    def info(self, msg: str, **extra: Any) -> None:
        self._log(logging.INFO, msg, **extra)

    def warning(self, msg: str, **extra: Any) -> None:
        self._log(logging.WARNING, msg, **extra)

    def error(self, msg: str, **extra: Any) -> None:
        self._log(logging.ERROR, msg, **extra)

    def tool_call(self, tool_name: str, duration_ms: float,
                  success: bool, detail: str = "") -> None:
        """Log a tool execution."""
        status = "OK" if success else "FAIL"
        self.info(
            f"Tool {tool_name} [{status}] ({duration_ms:.0f}ms) {detail}",
            tool=tool_name,
            duration_ms=duration_ms,
        )

    def llm_call(self, prompt_len: int, response_len: int,
                 tokens: int, duration_ms: float) -> None:
        """Log an LLM round-trip."""
        self.info(
            f"LLM call: prompt={prompt_len} resp={response_len} "
            f"tokens={tokens} latency={duration_ms:.0f}ms",
            prompt_len=prompt_len,
            response_len=response_len,
            tokens=tokens,
            duration_ms=duration_ms,
        )

    def stage(self, stage_name: str) -> None:
        """Log a pipeline stage transition."""
        self.info(f">>> Stage: {stage_name}", stage=stage_name)
