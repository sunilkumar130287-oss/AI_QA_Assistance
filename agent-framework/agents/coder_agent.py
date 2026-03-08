"""Coder agent — implements code changes with build/test verification.

Follows a strict loop: read → change → build → test → repeat.
Each change is small and focused, with build verification after every edit.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents.base_agent import BaseAgent
from core.state import PipelineState


class CoderAgent(BaseAgent):
    """Agent 5: Code implementation with continuous verification."""

    @property
    def name(self) -> str:
        return "coder_agent"

    @property
    def system_prompt(self) -> str:
        return """You are a senior software engineer agent. You write production-quality code.

You have access to: file_tool, build_tool, test_tool, search_tool, ast_tool, lsp_tool

Your process follows a strict loop:
1. Read the execution plan step you're implementing
2. Read the relevant source files to understand current code (file_tool action "read")
3. Make a SINGLE, focused change (file_tool action "write" or "replace")
4. Run the build (build_tool action "compile")
5. If build fails:
   - Read the error message carefully
   - Fix the specific error
   - Run the build again
   - Repeat until build passes (max 5 attempts per change)
6. Run the tests (test_tool action "run_tests")
7. If tests fail:
   - Read the failure message
   - Determine if it's your code or the test that's wrong
   - Fix your code (not the test, unless the test is clearly wrong)
   - Run tests again
8. Move to next plan step

CRITICAL RULES:
- NEVER modify a file without reading it first
- NEVER guess at import paths — use search_tool or ast_tool to find them
- NEVER write more than 50 lines without running the build
- NEVER fake terminal output or test results
- If stuck after 3 attempts on the same error, report it as blocked
- Follow existing code style and patterns in the repo
- Add comments explaining WHY, not WHAT

For upgrade tasks:
- Change ONE dependency/import at a time
- Build after each change
- Use migration patterns from the skill context

When calling a tool:
ACTION: file_tool
ARGS:
```json
{"action": "read", "filepath": "src/main/java/MyService.java"}
```

When complete:
COMPLETE:
RESULT:
```json
{
  "files_modified": ["file1.java"],
  "files_created": ["file2.java"],
  "changes_summary": "description of what was changed",
  "build_status": "passing",
  "test_status": "passing",
  "iterations": 5
}
```"""

    def build_initial_message(self, state: PipelineState) -> str:
        parts: list[str] = []

        parts.append("=== TASK ===")
        parts.append(f"Story: {state.story_title}")
        parts.append(f"Type: {state.story_type}")
        parts.append(f"Description: {state.story_description[:500]}")

        if state.acceptance_criteria:
            parts.append("\n=== ACCEPTANCE CRITERIA ===")
            for i, ac in enumerate(state.acceptance_criteria, 1):
                parts.append(f"  {i}. {ac}")

        parts.append(f"\n=== TECH STACK ===")
        parts.append(f"Build System: {state.build_system}")
        parts.append(f"Tech Stack: {json.dumps(state.tech_stack)}")

        if state.execution_plan:
            coder_steps = [s for s in state.execution_plan if s.get("agent") == "coder_agent"]
            parts.append("\n=== EXECUTION PLAN (YOUR STEPS) ===")
            for step in coder_steps:
                parts.append(f"  Step {step.get('step_number')}: {step.get('description')}")
                if step.get("files_involved"):
                    parts.append(f"    Files: {', '.join(step['files_involved'])}")
                if step.get("validation"):
                    parts.append(f"    Validation: {step['validation']}")

        if state.test_files_created:
            parts.append(f"\n=== TESTS WRITTEN (must pass when done) ===")
            for tf in state.test_files_created:
                parts.append(f"  - {tf}")

        if state.skill_context:
            skill_ctx = state.skill_context
            if skill_ctx.get("context"):
                parts.append(f"\n=== SKILL MIGRATION GUIDE ===")
                parts.append(str(skill_ctx["context"])[:2000])

        if state.relevant_files:
            parts.append(f"\n=== RELEVANT FILES ===")
            for f in state.relevant_files[:20]:
                parts.append(f"  - {f}")

        parts.append(
            "\nImplement the changes step by step. Read files before modifying. "
            "Run build after each change. Run tests to verify."
        )
        return "\n".join(parts)

    def extract_result(self, state: PipelineState, messages: list[dict]) -> PipelineState:
        last = self._get_last_assistant_message(messages)
        parsed = self._extract_json(last)

        if parsed:
            state.files_modified = parsed.get("files_modified", state.files_modified)
            state.files_created = parsed.get("files_created", state.files_created)
            state.code_changes_summary = parsed.get("changes_summary", state.code_changes_summary)
            state.iteration_count = parsed.get("iterations", state.iteration_count)
        else:
            # Gather from tool results
            for msg in messages:
                content = msg.get("content", "")
                if "Tool Result [file_tool]" in content:
                    write_match = re.search(r"Wrote \d+ bytes to (\S+)", content)
                    if write_match:
                        fp = write_match.group(1)
                        if fp not in state.files_modified and fp not in state.files_created:
                            state.files_modified.append(fp)
                    replace_match = re.search(r"Replaced \d+ occurrence.*in (\S+)", content)
                    if replace_match:
                        fp = replace_match.group(1)
                        if fp not in state.files_modified:
                            state.files_modified.append(fp)

        # Track build results from tool outputs
        for msg in messages:
            content = msg.get("content", "")
            if "Tool Result [build_tool]" in content:
                state.build_results.append({
                    "success": "BUILD SUCCESS" in content,
                    "output": content[:500],
                })

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
