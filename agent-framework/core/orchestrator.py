"""Main pipeline orchestrator — runs agents in sequence with feedback loops.

No framework dependencies.  Manages the full lifecycle:
context → repo scan → plan → test → code → review → PR.
"""

from __future__ import annotations

import time
from typing import Any

from core.exceptions import (
    AgentFrameworkError,
    EscalationRequired,
    SkillNotFoundError,
)
from core.llm_client import LLMClient
from core.logger import LogContext, get_logger, setup_logging
from core.state import PipelineState
from agents.context_agent import ContextAgent
from agents.repo_agent import RepoAgent
from agents.planner_agent import PlannerAgent
from agents.test_agent import TestAgent
from agents.coder_agent import CoderAgent
from agents.reviewer_agent import ReviewerAgent
from skills.skill_loader import SkillLoader
from tools.ast_tool import ASTTool
from tools.base_tool import BaseTool
from tools.build_tool import BuildTool
from tools.file_tool import FileTool
from tools.git_tool import GitTool
from tools.jira_tool import JiraTool
from tools.lsp_tool import LSPTool
from tools.search_tool import SearchTool
from tools.test_tool import TestTool

logger = get_logger("orchestrator")


class Orchestrator:
    """Simple, linear pipeline with feedback loops.

    No framework dependencies.  Just Python.

    Usage::

        orch = Orchestrator(config)
        state = orch.run({
            "jira_id": "PROJ-1234",
            "repo_url": "https://git.company.com/team/service.git",
            "branch": "main",
            "task_type": "spring_boot_upgrade",
        })
    """

    MAX_REVIEW_RETRIES = 3

    def __init__(self, config: dict) -> None:
        self.config = config
        self.llm = LLMClient(config["torri"])
        self.skills = SkillLoader(config.get("skills_dir", "./skills"))
        self._tools: dict[str, BaseTool] = {}
        self._log: LogContext | None = None

    # ── Public API ──────────────────────────────────────────────────────

    def run(self, user_input: dict) -> PipelineState:
        """Execute the full pipeline.

        Parameters
        ----------
        user_input:
            Dict with keys: ``jira_id``, ``repo_url``, ``branch``, ``task_type``.

        Returns
        -------
        PipelineState
            Final state with full audit trail.
        """
        state = PipelineState(
            jira_id=user_input["jira_id"],
            repo_url=user_input["repo_url"],
            branch=user_input["branch"],
            task_type=user_input["task_type"],
        )
        state.working_directory = self.config.get("execution", {}).get(
            "working_directory", "./workspace"
        )

        self._log = LogContext(correlation_id=state.correlation_id, agent="orchestrator")
        self._log.stage("Pipeline started")
        self._log.info(
            f"Jira={state.jira_id} Repo={state.repo_url} "
            f"Branch={state.branch} Task={state.task_type}"
        )

        try:
            # 1. Load skill
            state = self._load_skill(state)

            # 2. Initialize tools (needs workspace path)
            self._tools = self._initialize_tools(state)

            # 3. Context agent — understand the Jira story
            state = self._run_agent("context_agent", ContextAgent, state, ["jira_tool"])

            # 4. Clone repo & repo agent — understand the codebase
            self._clone_repo(state)
            state = self._run_agent("repo_agent", RepoAgent, state, ["file_tool", "ast_tool", "search_tool"])

            # 5. Planner agent — create execution plan
            state = self._run_agent("planner_agent", PlannerAgent, state, [])

            # 6. Test agent — write failing tests (TDFlow)
            state = self._run_agent(
                "test_agent", TestAgent, state,
                ["file_tool", "test_tool", "build_tool", "search_tool"],
            )

            # 7-9. Code → Review loop (max 3 retries)
            for review_attempt in range(1, self.MAX_REVIEW_RETRIES + 1):
                self._log.info(f"Code/Review cycle {review_attempt}/{self.MAX_REVIEW_RETRIES}")

                # 7. Coder agent
                state = self._run_agent(
                    "coder_agent", CoderAgent, state,
                    ["file_tool", "build_tool", "test_tool", "search_tool", "ast_tool", "lsp_tool"],
                )

                # 8. Reviewer agent
                state = self._run_agent(
                    "reviewer_agent", ReviewerAgent, state,
                    ["file_tool", "test_tool", "build_tool", "git_tool", "search_tool"],
                )

                # 9. Check review result
                if state.review_passed:
                    self._log.info("Review PASSED")
                    break
                else:
                    self._log.warning(
                        f"Review FAILED (attempt {review_attempt}): "
                        f"{state.review_comments}"
                    )
                    if review_attempt == self.MAX_REVIEW_RETRIES:
                        state.record_error(
                            "orchestrator",
                            f"Review failed after {self.MAX_REVIEW_RETRIES} attempts",
                        )

            # 10. Update Jira (best effort)
            self._update_jira(state)

        except EscalationRequired as exc:
            self._log.error(f"Escalation: {exc}")
            state.record_error("orchestrator", str(exc), {"reason": exc.reason})
        except AgentFrameworkError as exc:
            self._log.error(f"Framework error: {exc}")
            state.record_error("orchestrator", str(exc))
        except Exception as exc:
            self._log.error(f"Unexpected error: {exc}")
            state.record_error("orchestrator", f"Unexpected: {exc}")

        # Finalize
        state.end_time = time.time()
        self._log.stage("Pipeline completed")
        self._log.info(f"Summary: {state.summary()}")

        return state

    # ── Pipeline steps ──────────────────────────────────────────────────

    def _load_skill(self, state: PipelineState) -> PipelineState:
        """Load the YAML skill for the task type."""
        self._log.stage("Loading skill")
        try:
            skill = self.skills.get(state.task_type)
        except SkillNotFoundError:
            self._log.warning(f"Skill '{state.task_type}' not found, using generic")
            try:
                skill = self.skills.get("story_implementation")
            except SkillNotFoundError:
                raise SkillNotFoundError(state.task_type)

        state.skill_name = skill.name
        state.skill_context = {
            "description": skill.description,
            "steps": skill.steps,
            "context": skill.context,
        }
        self._log.info(f"Loaded skill: {skill.name} ({len(skill.steps)} steps)")
        return state

    def _clone_repo(self, state: PipelineState) -> None:
        """Clone the repository to the workspace."""
        self._log.stage("Cloning repository")
        git_tool = self._tools.get("git_tool")
        if git_tool is None:
            return

        result = git_tool.execute(
            action="clone",
            repo_url=state.repo_url,
            branch=state.branch,
            working_dir=state.working_directory,
        )
        if not result.success:
            self._log.warning(f"Clone issue: {result.error}")
        else:
            self._log.info(result.output)

    def _run_agent(
        self,
        name: str,
        agent_class: type,
        state: PipelineState,
        tool_names: list[str],
    ) -> PipelineState:
        """Instantiate and run a single agent."""
        self._log.stage(f"Running {name}")

        agent_tools = {n: self._tools[n] for n in tool_names if n in self._tools}
        agent = agent_class(
            llm_client=self.llm,
            tools=agent_tools,
            config=self.config.get("execution", {}),
        )

        try:
            state = agent.run(state)
        except Exception as exc:
            self._log.error(f"Agent {name} failed: {exc}")
            state.record_error(name, str(exc))
            if self._should_escalate(state):
                raise EscalationRequired(name, str(exc))

        return state

    def _update_jira(self, state: PipelineState) -> None:
        """Update Jira with results (best effort)."""
        jira = self._tools.get("jira_tool")
        if jira is None:
            return

        try:
            comment = self._build_jira_comment(state)
            jira.execute(
                action="update_story",
                jira_id=state.jira_id,
                comment=comment,
            )
        except Exception as exc:
            self._log.warning(f"Failed to update Jira: {exc}")

    @staticmethod
    def _build_jira_comment(state: PipelineState) -> str:
        """Build a Jira comment summarizing the agent's work."""
        lines = [f"*Agent Framework — Automated Execution*"]
        lines.append(f"Correlation ID: {state.correlation_id}")
        lines.append(f"Task Type: {state.task_type}")
        lines.append(f"Duration: {state.elapsed_seconds()}s")
        lines.append(f"LLM Calls: {state.total_llm_calls}")

        if state.review_passed:
            lines.append(f"\n*Status: COMPLETED*")
            if state.pr_url:
                lines.append(f"PR: {state.pr_url}")
        else:
            lines.append(f"\n*Status: NEEDS ATTENTION*")
            if state.review_comments:
                lines.append("Issues:")
                for c in state.review_comments:
                    lines.append(f"  - {c}")

        if state.files_modified:
            lines.append(f"\nFiles modified: {len(state.files_modified)}")
        if state.test_files_created:
            lines.append(f"Tests created: {len(state.test_files_created)}")
        if state.errors:
            lines.append(f"\nErrors encountered: {len(state.errors)}")

        return "\n".join(lines)

    # ── Tool initialization ─────────────────────────────────────────────

    def _initialize_tools(self, state: PipelineState) -> dict[str, BaseTool]:
        """Create all tool instances.  Tools are shared across agents."""
        workspace = state.working_directory
        config = self.config

        tools: dict[str, BaseTool] = {}

        # Jira tool
        if "jira" in config:
            try:
                tools["jira_tool"] = JiraTool(config["jira"])
            except Exception as exc:
                logger.warning(f"Jira tool init failed: {exc}")

        # Git tool
        if "git" in config:
            tools["git_tool"] = GitTool(config["git"], workspace)

        # File operations
        tools["file_tool"] = FileTool(workspace)

        # Build tool
        timeout = config.get("execution", {}).get("command_timeout_seconds", 300)
        tools["build_tool"] = BuildTool(workspace, timeout)

        # Test tool
        tools["test_tool"] = TestTool(workspace, timeout=timeout)

        # AST tool
        tools["ast_tool"] = ASTTool(workspace)

        # Search tool
        tools["search_tool"] = SearchTool(workspace)

        # LSP tool
        tools["lsp_tool"] = LSPTool(workspace)

        return tools

    # ── Safety checks ───────────────────────────────────────────────────

    @staticmethod
    def _should_escalate(state: PipelineState) -> bool:
        """Determine if the task should be escalated to a human."""
        # Escalate after too many errors
        if len(state.errors) >= 5:
            return True
        # Escalate if the same error repeats 3 times
        error_msgs = [e["error"] for e in state.errors]
        for msg in set(error_msgs):
            if error_msgs.count(msg) >= 3:
                return True
        return False
