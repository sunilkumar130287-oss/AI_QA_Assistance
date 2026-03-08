"""Shared pipeline state — the single mutable data object flowing through all agents.

Every agent reads from PipelineState, performs work, and writes results back.
No agent stores state between runs; PipelineState is the only shared memory.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class PipelineState:
    """Mutable state passed through the entire orchestration pipeline."""

    # ── User Input ──────────────────────────────────────────────────────
    jira_id: str = ""
    repo_url: str = ""
    branch: str = ""
    task_type: str = ""  # maps to a skill name

    # ── Agent 1 Output: Jira Context ────────────────────────────────────
    story_title: str = ""
    story_description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    story_type: str = ""  # bug, feature, upgrade, test
    story_metadata: dict = field(default_factory=dict)

    # ── Agent 2 Output: Repo Context ────────────────────────────────────
    repo_map: dict = field(default_factory=dict)
    tech_stack: dict = field(default_factory=dict)
    project_structure: str = ""
    relevant_files: list[str] = field(default_factory=list)
    build_system: str = ""  # maven, gradle, npm, angular

    # ── Agent 3 Output: Plan ────────────────────────────────────────────
    execution_plan: list[dict] = field(default_factory=list)
    skill_name: str = ""
    skill_context: dict = field(default_factory=dict)

    # ── Agent 4 Output: Tests ───────────────────────────────────────────
    test_files_created: list[str] = field(default_factory=list)
    test_scenarios: list[dict] = field(default_factory=list)
    initial_test_results: dict = field(default_factory=dict)

    # ── Agent 5 Output: Code Changes ────────────────────────────────────
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    code_changes_summary: str = ""
    build_results: list[dict] = field(default_factory=list)
    iteration_count: int = 0

    # ── Agent 6 Output: Review ──────────────────────────────────────────
    review_passed: bool = False
    review_comments: list[str] = field(default_factory=list)
    final_test_results: dict = field(default_factory=dict)
    pr_url: str = ""

    # ── Pipeline Metadata ───────────────────────────────────────────────
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    total_llm_calls: int = 0
    total_tokens_used: int = 0
    errors: list[dict] = field(default_factory=list)
    working_directory: str = ""

    # ── Convenience ─────────────────────────────────────────────────────

    def record_error(self, agent: str, error: str, details: dict | None = None) -> None:
        """Append an error entry to the audit trail."""
        self.errors.append({
            "agent": agent,
            "error": error,
            "details": details or {},
            "timestamp": time.time(),
        })

    def elapsed_seconds(self) -> float:
        """Wall-clock seconds since pipeline start."""
        end = self.end_time if self.end_time else time.time()
        return round(end - self.start_time, 2)

    def summary(self) -> dict:
        """Return a compact summary suitable for logging or display."""
        return {
            "correlation_id": self.correlation_id,
            "jira_id": self.jira_id,
            "task_type": self.task_type,
            "review_passed": self.review_passed,
            "pr_url": self.pr_url,
            "files_modified": len(self.files_modified),
            "files_created": len(self.files_created),
            "test_files_created": len(self.test_files_created),
            "total_llm_calls": self.total_llm_calls,
            "total_tokens_used": self.total_tokens_used,
            "elapsed_seconds": self.elapsed_seconds(),
            "errors": len(self.errors),
        }
