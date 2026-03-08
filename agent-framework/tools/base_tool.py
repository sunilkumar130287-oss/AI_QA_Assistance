"""Abstract base class for all tools.

Tools are deterministic: no LLM calls, no side effects beyond their stated
purpose.  Every tool returns a ``ToolResult``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Uniform return type for every tool execution."""

    success: bool
    output: str
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"ERROR: {self.error}"


class BaseTool(ABC):
    """Abstract base for all framework tools.

    Subclasses must define ``name``, ``description``, and ``execute``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short, unique identifier for the tool (e.g. ``file_tool``)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description shown to the LLM for tool selection."""
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool and return a ``ToolResult``."""
        ...

    def validate_inputs(self, **kwargs: Any) -> bool:
        """Optional input validation hook.  Returns True if inputs are valid."""
        return True

    # Convenience for OpenAI function-calling schema generation
    def to_schema(self) -> dict:
        """Return an OpenAI-compatible tool/function schema.

        Subclasses may override this to provide parameter details.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }
