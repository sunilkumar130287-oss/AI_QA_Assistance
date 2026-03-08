"""Tests for agents — base agent loop, response parsing, and individual agents.

All LLM calls and tools are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agents.base_agent import BaseAgent
from agents.context_agent import ContextAgent
from agents.planner_agent import PlannerAgent
from core.llm_client import LLMClient, LLMResponse
from core.state import PipelineState
from tools.base_tool import BaseTool, ToolResult


# ── Test the base agent response parser ─────────────────────────────────


class TestBaseAgentParsing:
    """Test _parse_response for all expected formats."""

    def test_parse_complete(self):
        content = "THINKING: Done with analysis.\nCOMPLETE:\nRESULT: All tasks finished."
        result = BaseAgent._parse_response(content)
        assert result["type"] == "complete"
        assert "All tasks finished" in result["result"]

    def test_parse_tool_call(self):
        content = (
            "THINKING: I need to read a file.\n"
            "ACTION: file_tool\n"
            "ARGS:\n"
            "```json\n"
            '{"action": "read", "filepath": "main.py"}\n'
            "```"
        )
        result = BaseAgent._parse_response(content)
        assert result["type"] == "tool_call"
        assert result["tool"] == "file_tool"
        assert result["args"]["action"] == "read"
        assert result["args"]["filepath"] == "main.py"

    def test_parse_tool_call_without_json_fence(self):
        content = 'ACTION: search_tool\nARGS: {"action": "regex_search", "pattern": "TODO"}'
        result = BaseAgent._parse_response(content)
        assert result["type"] == "tool_call"
        assert result["tool"] == "search_tool"

    def test_parse_thinking_only(self):
        content = "THINKING: I need to consider the approach..."
        result = BaseAgent._parse_response(content)
        assert result["type"] == "thinking"

    def test_parse_unknown(self):
        content = "Here is some random text without any action markers."
        result = BaseAgent._parse_response(content)
        assert result["type"] == "unknown"

    def test_parse_empty(self):
        result = BaseAgent._parse_response("")
        assert result["type"] == "unknown"


# ── Test the CodeAct loop ───────────────────────────────────────────────


class ConcreteAgent(BaseAgent):
    """Minimal concrete agent for testing the base loop."""

    @property
    def name(self) -> str:
        return "test_agent"

    @property
    def system_prompt(self) -> str:
        return "You are a test agent."

    def build_initial_message(self, state: PipelineState) -> str:
        return f"Process: {state.jira_id}"

    def extract_result(self, state: PipelineState, messages: list) -> PipelineState:
        state.story_title = "Extracted"
        return state


class TestCodeActLoop:
    """Test the Think-Act-Observe loop in BaseAgent.run()."""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock(spec=LLMClient)

    @pytest.fixture
    def mock_tool(self):
        tool = MagicMock(spec=BaseTool)
        tool.name = "file_tool"
        tool.execute.return_value = ToolResult(success=True, output="file contents here")
        return tool

    @pytest.fixture
    def state(self):
        return PipelineState(jira_id="TEST-1", task_type="test")

    def test_immediate_completion(self, mock_llm, state):
        """Agent completes on first turn."""
        mock_llm.call.return_value = LLMResponse(
            content="COMPLETE:\nRESULT: Done.",
            usage={"total_tokens": 100},
        )

        agent = ConcreteAgent(mock_llm, {}, {"max_agent_iterations": 5})
        result = agent.run(state)

        assert result.story_title == "Extracted"
        assert mock_llm.call.call_count == 1

    def test_tool_call_then_complete(self, mock_llm, mock_tool, state):
        """Agent calls a tool, then completes."""
        mock_llm.call.side_effect = [
            LLMResponse(
                content='ACTION: file_tool\nARGS:\n```json\n{"action": "read", "filepath": "x.py"}\n```',
                usage={"total_tokens": 100},
            ),
            LLMResponse(
                content="COMPLETE:\nRESULT: Read the file.",
                usage={"total_tokens": 80},
            ),
        ]

        agent = ConcreteAgent(mock_llm, {"file_tool": mock_tool}, {"max_agent_iterations": 5})
        result = agent.run(state)

        assert result.story_title == "Extracted"
        assert mock_llm.call.call_count == 2
        mock_tool.execute.assert_called_once()
        assert result.total_llm_calls == 2

    def test_max_iterations(self, mock_llm, state):
        """Agent stops at max iterations."""
        mock_llm.call.return_value = LLMResponse(
            content="THINKING: Still working...",
            usage={"total_tokens": 50},
        )

        agent = ConcreteAgent(mock_llm, {}, {"max_agent_iterations": 3})
        result = agent.run(state)

        assert mock_llm.call.call_count == 3
        assert len(result.errors) > 0

    def test_unknown_tool(self, mock_llm, state):
        """Agent tries to call a tool that doesn't exist."""
        mock_llm.call.side_effect = [
            LLMResponse(
                content='ACTION: nonexistent_tool\nARGS:\n```json\n{}\n```',
                usage={"total_tokens": 50},
            ),
            LLMResponse(
                content="COMPLETE:\nRESULT: Done.",
                usage={"total_tokens": 50},
            ),
        ]

        agent = ConcreteAgent(mock_llm, {}, {"max_agent_iterations": 5})
        result = agent.run(state)

        assert mock_llm.call.call_count == 2

    def test_tool_exception_handled(self, mock_llm, mock_tool, state):
        """Tool raises an exception — should be caught and reported."""
        mock_tool.execute.side_effect = RuntimeError("disk full")

        mock_llm.call.side_effect = [
            LLMResponse(
                content='ACTION: file_tool\nARGS:\n```json\n{"action": "read"}\n```',
                usage={"total_tokens": 50},
            ),
            LLMResponse(
                content="COMPLETE:\nRESULT: Handled error.",
                usage={"total_tokens": 50},
            ),
        ]

        agent = ConcreteAgent(mock_llm, {"file_tool": mock_tool}, {"max_agent_iterations": 5})
        result = agent.run(state)
        assert mock_llm.call.call_count == 2


# ── Test ContextAgent extraction ────────────────────────────────────────


class TestContextAgent:
    """Test ContextAgent.extract_result parsing."""

    @pytest.fixture
    def agent(self):
        return ContextAgent(
            llm_client=MagicMock(spec=LLMClient),
            tools={},
            config={"max_agent_iterations": 5},
        )

    def test_extract_from_json_response(self, agent):
        state = PipelineState(jira_id="TEST-1")
        messages = [
            {"role": "user", "content": "Analyze"},
            {"role": "assistant", "content": (
                'COMPLETE:\nRESULT:\n```json\n'
                '{"title": "Add login", "description": "User login feature", '
                '"acceptance_criteria": ["Users can log in", "Error shown on failure"], '
                '"story_type": "feature"}\n```'
            )},
        ]

        result = agent.extract_result(state, messages)
        assert result.story_title == "Add login"
        assert result.story_type == "feature"
        assert len(result.acceptance_criteria) == 2

    def test_extract_from_tool_result_fallback(self, agent):
        state = PipelineState(jira_id="TEST-2")
        messages = [
            {"role": "user", "content": "Analyze"},
            {"role": "user", "content": (
                'Tool Result [jira_tool]:\n'
                '{"title": "Fix bug", "description": "Fix NPE", '
                '"acceptance_criteria": ["No NPE on null input"], '
                '"story_type": "bug"}'
            )},
            {"role": "assistant", "content": "I found the story details."},
        ]

        result = agent.extract_result(state, messages)
        assert result.story_title == "Fix bug"
        assert result.story_type == "bug"


# ── Test PlannerAgent extraction ────────────────────────────────────────


class TestPlannerAgent:
    """Test PlannerAgent.extract_result plan parsing."""

    @pytest.fixture
    def agent(self):
        return PlannerAgent(
            llm_client=MagicMock(spec=LLMClient),
            tools={},
            config={"max_agent_iterations": 5},
        )

    def test_extract_plan(self, agent):
        state = PipelineState(jira_id="TEST-3")
        plan = [
            {"step_number": 1, "description": "Write tests", "agent": "test_agent"},
            {"step_number": 2, "description": "Implement", "agent": "coder_agent"},
        ]
        messages = [
            {"role": "user", "content": "Plan"},
            {"role": "assistant", "content": f"COMPLETE:\nRESULT:\n```json\n{json.dumps(plan)}\n```"},
        ]

        result = agent.extract_result(state, messages)
        assert len(result.execution_plan) == 2
        assert result.execution_plan[0]["agent"] == "test_agent"
