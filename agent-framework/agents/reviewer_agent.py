"""Reviewer agent — QA verification, code review, and PR creation.

Runs the full test suite, reviews all modified files, checks for issues,
and creates the git commit and pull request if everything passes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents.base_agent import BaseAgent
from core.state import PipelineState


class ReviewerAgent(BaseAgent):
    """Agent 6: QA review, verification, and PR creation."""

    @property
    def name(self) -> str:
        return "reviewer_agent"

    @property
    def system_prompt(self) -> str:
        return """You are a senior QA engineer and code reviewer agent.

You have access to: file_tool, test_tool, build_tool, git_tool, search_tool

Your review checklist:
1. Run the FULL test suite using test_tool action "run_tests" — all tests must pass
2. Review every file that was modified using file_tool action "read":
   - Does the change match the acceptance criteria?
   - Are there any obvious bugs, security issues, or performance problems?
   - Does the code follow the project's existing patterns?
   - Are there any hardcoded values that should be configurable?
   - Are there any missing error handlers?
3. Check that no unintended files were modified using git_tool action "get_changed_files"
4. Verify the git diff looks clean using git_tool action "diff"
   - No debug statements, no commented-out code, no TODO markers
5. If everything passes, create the commit and PR:
   - git_tool action "commit" with a descriptive message
   - git_tool action "push"
   - git_tool action "create_pr" with title and body summarizing changes

If review FAILS:
- List specific issues that must be fixed
- Respond with review_passed = false

If review PASSES:
- Create the git commit and PR
- Respond with review_passed = true and the PR URL

When calling a tool:
ACTION: test_tool
ARGS:
```json
{"action": "run_tests"}
```

When complete:
COMPLETE:
RESULT:
```json
{
  "review_passed": true,
  "review_comments": ["All tests pass", "Code follows patterns"],
  "test_results": {"passed": 10, "failed": 0},
  "pr_url": "https://github.com/org/repo/pull/42",
  "files_reviewed": ["file1.java", "file2.java"]
}
```"""

    def build_initial_message(self, state: PipelineState) -> str:
        parts: list[str] = []

        parts.append("=== REVIEW TASK ===")
        parts.append(f"Story: {state.story_title} ({state.jira_id})")
        parts.append(f"Type: {state.story_type}")

        if state.acceptance_criteria:
            parts.append("\n=== ACCEPTANCE CRITERIA ===")
            for i, ac in enumerate(state.acceptance_criteria, 1):
                parts.append(f"  {i}. {ac}")

        parts.append(f"\n=== CHANGES MADE ===")
        parts.append(f"Summary: {state.code_changes_summary}")
        if state.files_modified:
            parts.append(f"Files modified: {', '.join(state.files_modified)}")
        if state.files_created:
            parts.append(f"Files created: {', '.join(state.files_created)}")
        if state.test_files_created:
            parts.append(f"Test files: {', '.join(state.test_files_created)}")

        parts.append(f"\n=== BUILD SYSTEM ===")
        parts.append(f"Build: {state.build_system}")

        parts.append(f"\n=== PR INFO ===")
        parts.append(f"Branch: {state.branch}")
        parts.append(f"Jira: {state.jira_id}")

        parts.append(
            "\nReview the changes above. Run tests. Review each modified file. "
            "If everything passes, create a commit and PR."
        )
        return "\n".join(parts)

    def extract_result(self, state: PipelineState, messages: list[dict]) -> PipelineState:
        last = self._get_last_assistant_message(messages)
        parsed = self._extract_json(last)

        if parsed:
            state.review_passed = parsed.get("review_passed", False)
            state.review_comments = parsed.get("review_comments", [])
            state.final_test_results = parsed.get("test_results", state.final_test_results)
            state.pr_url = parsed.get("pr_url", state.pr_url)
        else:
            # Check tool results for PR URL
            for msg in messages:
                content = msg.get("content", "")
                if "Tool Result [git_tool]" in content and "PR created" in content:
                    url_match = re.search(r"https?://\S+", content)
                    if url_match:
                        state.pr_url = url_match.group(0)
                        state.review_passed = True

            # Check test results
            for msg in reversed(messages):
                content = msg.get("content", "")
                if "Tool Result [test_tool]" in content:
                    if "TEST PASSED" in content:
                        state.review_passed = state.review_passed  # keep existing
                    elif "TEST FAILED" in content:
                        state.review_passed = False
                        state.review_comments.append("Tests failed during review")
                    break

        return state

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        return None
