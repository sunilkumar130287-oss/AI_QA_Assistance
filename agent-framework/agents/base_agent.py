"""Abstract base agent with the CodeAct Think → Act → Observe loop.

Every agent inherits from this class.  The loop runs:
    1. Build initial message from pipeline state
    2. Call LLM with system prompt + messages
    3. Parse response for tool calls OR completion signal
    4. If tool call → execute tool, append result, goto 2
    5. If complete → extract result into state, return
    6. If max iterations → log warning, extract partial result
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from core.exceptions import MaxIterationsError
from core.llm_client import LLMClient, LLMResponse
from core.logger import LogContext, get_logger
from core.state import PipelineState
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("base_agent")


class BaseAgent(ABC):
    """Abstract base for all pipeline agents.

    Subclasses must implement:
    - ``name`` — unique identifier
    - ``system_prompt`` — instructions for the LLM
    - ``build_initial_message`` — construct the first user message from state
    - ``extract_result`` — write agent output back to state
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tools: dict[str, BaseTool],
        config: dict,
    ) -> None:
        self.llm = llm_client
        self.tools = tools
        self.config = config
        self.max_iterations = config.get("max_agent_iterations", 25)

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        ...

    @abstractmethod
    def build_initial_message(self, state: PipelineState) -> str:
        ...

    @abstractmethod
    def extract_result(self, state: PipelineState, messages: list[dict]) -> PipelineState:
        ...

    # ── The CodeAct Loop ────────────────────────────────────────────────

    def run(self, state: PipelineState) -> PipelineState:
        """Execute the Think → Act → Observe loop."""
        log_ctx = LogContext(correlation_id=state.correlation_id, agent=self.name)
        log_ctx.stage(f"Agent {self.name} starting")

        messages: list[dict[str, str]] = [
            {"role": "user", "content": self.build_initial_message(state)},
        ]

        for iteration in range(1, self.max_iterations + 1):
            log_ctx.info(f"Iteration {iteration}/{self.max_iterations}")

            response = self.llm.call(
                system_prompt=self.system_prompt,
                messages=messages,
                correlation_id=state.correlation_id,
            )

            state.total_llm_calls += 1
            state.total_tokens_used += response.usage.get("total_tokens", 0)

            # Parse the LLM response
            action = self._parse_response(response.content)

            if action["type"] == "complete":
                log_ctx.info(f"Agent {self.name} completed in {iteration} iteration(s)")
                messages.append({"role": "assistant", "content": response.content})
                return self.extract_result(state, messages)

            if action["type"] == "tool_call":
                tool_name = action["tool"]
                tool_args = action["args"]
                log_ctx.info(f"Tool call: {tool_name}({json.dumps(tool_args)[:200]})")

                tool = self.tools.get(tool_name)
                start = time.time()

                if tool is None:
                    tool_result = ToolResult(
                        success=False,
                        output="",
                        error=f"Unknown tool: {tool_name}. Available: {list(self.tools.keys())}",
                    )
                else:
                    try:
                        tool_result = tool.execute(**tool_args)
                    except Exception as exc:
                        tool_result = ToolResult(success=False, output="", error=str(exc))

                duration_ms = (time.time() - start) * 1000
                log_ctx.tool_call(tool_name, duration_ms, tool_result.success)

                # Append assistant + tool result to conversation
                messages.append({"role": "assistant", "content": response.content})
                result_text = tool_result.output if tool_result.success else f"ERROR: {tool_result.error}"
                messages.append({
                    "role": "user",
                    "content": f"Tool Result [{tool_name}]:\n{result_text}",
                })
                continue

            if action["type"] == "thinking":
                # LLM is reasoning but didn't produce a tool call or completion
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": (
                        "Continue. If you need to use a tool, format your response with "
                        "ACTION/ARGS blocks. If you are done, respond with COMPLETE."
                    ),
                })
                continue

            # Unknown action type — prompt for clarification
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": (
                    "Your response was not in the expected format. Use:\n"
                    "ACTION: <tool_name>\nARGS:\n```json\n{...}\n```\n"
                    "Or: COMPLETE:\nRESULT: <summary>"
                ),
            })

        # Max iterations reached
        log_ctx.warning(f"Agent {self.name} hit max iterations ({self.max_iterations})")
        state.record_error(self.name, f"Max iterations reached ({self.max_iterations})")
        return self.extract_result(state, messages)

    # ── Response Parsing ────────────────────────────────────────────────

    @staticmethod
    def _parse_response(content: str) -> dict[str, Any]:
        """Parse an LLM response into an action dict.

        Expected formats:

        **Tool call**::

            THINKING: ...
            ACTION: tool_name
            ARGS:
            ```json
            {"key": "value"}
            ```

        **Completion**::

            COMPLETE:
            RESULT: summary text
        """
        if not content:
            return {"type": "unknown"}

        # Check for completion
        if re.search(r"^COMPLETE:", content, re.MULTILINE):
            result_match = re.search(r"RESULT:\s*(.+)", content, re.DOTALL)
            return {
                "type": "complete",
                "result": result_match.group(1).strip() if result_match else "",
            }

        # Check for tool call
        action_match = re.search(r"^ACTION:\s*(\S+)", content, re.MULTILINE)
        if action_match:
            tool_name = action_match.group(1).strip()

            # Extract JSON args
            args: dict = {}
            json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
            if json_match:
                try:
                    args = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    # Try to fix common issues
                    raw = json_match.group(1).strip()
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        args = {"_raw_args": raw}
            else:
                # Try ARGS: on same line or next line
                args_match = re.search(r"ARGS:\s*({.+})", content, re.DOTALL)
                if args_match:
                    try:
                        args = json.loads(args_match.group(1))
                    except json.JSONDecodeError:
                        args = {"_raw_args": args_match.group(1)}

            return {"type": "tool_call", "tool": tool_name, "args": args}

        # Check if it's just thinking
        if re.search(r"^THINKING:", content, re.MULTILINE):
            return {"type": "thinking"}

        return {"type": "unknown"}

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_last_assistant_message(self, messages: list[dict]) -> str:
        """Extract the last assistant message content."""
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                return msg["content"]
        return ""

    def _get_all_tool_results(self, messages: list[dict]) -> list[str]:
        """Collect all tool result messages."""
        return [
            msg["content"]
            for msg in messages
            if msg["role"] == "user" and msg["content"].startswith("Tool Result")
        ]
