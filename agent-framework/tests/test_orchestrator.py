"""Tests for core/orchestrator.py — full pipeline with mocked agents.

Verifies the orchestration flow, retry logic, escalation, and state management.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from core.exceptions import EscalationRequired, SkillNotFoundError
from core.llm_client import LLMClient, LLMResponse
from core.orchestrator import Orchestrator
from core.state import PipelineState


@pytest.fixture
def config():
    return {
        "torri": {
            "base_url": "https://torri.example.com/v1",
            "api_key": "test-key",
            "model": "gpt-4o",
            "max_tokens": 1024,
            "temperature": 0,
            "timeout_seconds": 30,
            "max_retries": 2,
            "retry_delay_seconds": 0.1,
        },
        "jira": {
            "base_url": "https://jira.example.com",
            "api_token": "jira-token",
            "username": "test@example.com",
        },
        "git": {
            "default_remote": "origin",
            "commit_prefix": "[agent]",
            "provider": "github",
            "api_token": "git-token",
            "api_url": "https://api.github.com",
        },
        "execution": {
            "max_agent_iterations": 3,
            "working_directory": "./test-workspace",
            "command_timeout_seconds": 30,
        },
        "logging": {
            "level": "WARNING",
            "format": "plain",
            "file": "./logs/test.log",
        },
        "skills_dir": "./skills",
    }


@pytest.fixture
def user_input():
    return {
        "jira_id": "PROJ-1234",
        "repo_url": "https://git.example.com/team/service.git",
        "branch": "main",
        "task_type": "story_implementation",
    }


class TestOrchestratorInit:
    """Test orchestrator initialization."""

    def test_init_creates_llm_client(self, config):
        orch = Orchestrator(config)
        assert orch.llm is not None
        assert orch.config == config


class TestOrchestratorPipeline:
    """Test the full pipeline flow with mocked agents."""

    @patch("core.orchestrator.ReviewerAgent")
    @patch("core.orchestrator.CoderAgent")
    @patch("core.orchestrator.TestAgent")
    @patch("core.orchestrator.PlannerAgent")
    @patch("core.orchestrator.RepoAgent")
    @patch("core.orchestrator.ContextAgent")
    def test_successful_pipeline(
        self,
        MockContextAgent, MockRepoAgent, MockPlannerAgent,
        MockTestAgent, MockCoderAgent, MockReviewerAgent,
        config, user_input,
    ):
        """Happy path: all agents succeed, review passes."""
        # Setup: each mock agent's run() modifies state appropriately
        def context_run(state):
            state.story_title = "Add login"
            state.story_type = "feature"
            state.acceptance_criteria = ["Users can log in"]
            return state

        def repo_run(state):
            state.tech_stack = {"languages": ["java"], "frameworks": ["spring-boot"]}
            state.build_system = "maven"
            state.relevant_files = ["src/main/java/Login.java"]
            return state

        def planner_run(state):
            state.execution_plan = [
                {"step_number": 1, "description": "Write tests", "agent": "test_agent"},
                {"step_number": 2, "description": "Implement", "agent": "coder_agent"},
            ]
            return state

        def test_run(state):
            state.test_files_created = ["src/test/java/LoginTest.java"]
            return state

        def coder_run(state):
            state.files_modified = ["src/main/java/Login.java"]
            return state

        def reviewer_run(state):
            state.review_passed = True
            state.pr_url = "https://github.com/org/repo/pull/42"
            return state

        MockContextAgent.return_value.run.side_effect = context_run
        MockRepoAgent.return_value.run.side_effect = repo_run
        MockPlannerAgent.return_value.run.side_effect = planner_run
        MockTestAgent.return_value.run.side_effect = test_run
        MockCoderAgent.return_value.run.side_effect = coder_run
        MockReviewerAgent.return_value.run.side_effect = reviewer_run

        orch = Orchestrator(config)
        state = orch.run(user_input)

        assert state.review_passed is True
        assert state.pr_url == "https://github.com/org/repo/pull/42"
        assert state.story_title == "Add login"
        assert len(state.execution_plan) == 2

    @patch("core.orchestrator.ReviewerAgent")
    @patch("core.orchestrator.CoderAgent")
    @patch("core.orchestrator.TestAgent")
    @patch("core.orchestrator.PlannerAgent")
    @patch("core.orchestrator.RepoAgent")
    @patch("core.orchestrator.ContextAgent")
    def test_review_retry_loop(
        self,
        MockContextAgent, MockRepoAgent, MockPlannerAgent,
        MockTestAgent, MockCoderAgent, MockReviewerAgent,
        config, user_input,
    ):
        """Review fails first time, passes second time."""
        for mock in [MockContextAgent, MockRepoAgent, MockPlannerAgent, MockTestAgent, MockCoderAgent]:
            mock.return_value.run.side_effect = lambda s: s

        review_call_count = 0

        def reviewer_run(state):
            nonlocal review_call_count
            review_call_count += 1
            if review_call_count == 1:
                state.review_passed = False
                state.review_comments = ["Tests failing"]
            else:
                state.review_passed = True
                state.pr_url = "https://github.com/org/repo/pull/99"
            return state

        MockReviewerAgent.return_value.run.side_effect = reviewer_run

        orch = Orchestrator(config)
        state = orch.run(user_input)

        assert state.review_passed is True
        assert review_call_count == 2


class TestOrchestratorEscalation:
    """Test escalation logic."""

    def test_should_escalate_many_errors(self):
        state = PipelineState()
        for i in range(5):
            state.record_error("test", f"Error {i}")

        assert Orchestrator._should_escalate(state) is True

    def test_should_escalate_repeated_error(self):
        state = PipelineState()
        for _ in range(3):
            state.record_error("test", "Same error")

        assert Orchestrator._should_escalate(state) is True

    def test_should_not_escalate_few_errors(self):
        state = PipelineState()
        state.record_error("test", "Error 1")
        state.record_error("test", "Error 2")

        assert Orchestrator._should_escalate(state) is False


class TestPipelineState:
    """Test PipelineState convenience methods."""

    def test_record_error(self):
        state = PipelineState()
        state.record_error("agent_x", "something broke", {"line": 42})
        assert len(state.errors) == 1
        assert state.errors[0]["agent"] == "agent_x"
        assert state.errors[0]["details"]["line"] == 42

    def test_summary(self):
        state = PipelineState(jira_id="TEST-1", task_type="feature")
        state.files_modified = ["a.py", "b.py"]
        state.total_llm_calls = 10
        summary = state.summary()
        assert summary["jira_id"] == "TEST-1"
        assert summary["files_modified"] == 2
        assert summary["total_llm_calls"] == 10

    def test_elapsed_seconds(self):
        import time
        state = PipelineState()
        time.sleep(0.01)
        elapsed = state.elapsed_seconds()
        assert elapsed >= 0.01
