"""Test agent — writes tests following Test-Driven Flow.

Writes tests for acceptance criteria BEFORE implementation, ensures they
fail initially, and reports test status for the coder agent.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents.base_agent import BaseAgent
from core.state import PipelineState


class TestAgent(BaseAgent):
    """Agent 4: Test-Driven Flow — write tests first, verify they fail."""

    @property
    def name(self) -> str:
        return "test_agent"

    @property
    def system_prompt(self) -> str:
        return """You are a test engineering agent. You follow Test-Driven Flow (TDFlow) strictly.

You have access to: file_tool, test_tool, build_tool, search_tool

Your process:
1. Read the acceptance criteria and execution plan
2. Search for existing test patterns in the project (search_tool)
3. Read existing test files to understand conventions (file_tool)
4. For each acceptance criterion, write a test that:
   - Tests the EXPECTED behavior described in the AC
   - Is a proper unit test or integration test for the project's test framework
   - Follows the project's existing test patterns and conventions
   - Uses the project's existing test utilities and helpers
5. Write test files using file_tool action "write"
6. Run the tests using test_tool action "run_tests" — they MUST FAIL initially
   - If a test passes before implementation, it's testing the wrong thing. Revise it.
7. Report which tests were created and their initial (failing) status

For upgrade tasks:
- Write tests that verify the NEW behavior works
- Write tests that verify deprecated APIs are no longer used

CRITICAL: The test runner is your oracle. It provides binary truth. Trust it over assumptions.
If a test fails unexpectedly, read the error carefully before making changes.
Never fake test output. Always run actual tests via the test_tool.

When calling a tool:
ACTION: file_tool
ARGS:
```json
{"action": "write", "filepath": "src/test/java/MyTest.java", "content": "..."}
```

When complete:
COMPLETE:
RESULT:
```json
{
  "test_files_created": ["path/to/test1.java"],
  "test_scenarios": [
    {"name": "test_ac1_happy_path", "ac": "AC text", "status": "FAIL"}
  ],
  "initial_results": {"passed": 0, "failed": 3, "errors": 0}
}
```"""

    def build_initial_message(self, state: PipelineState) -> str:
        parts: list[str] = []

        parts.append("=== TASK ===")
        parts.append(f"Story: {state.story_title}")
        parts.append(f"Type: {state.story_type}")

        if state.acceptance_criteria:
            parts.append("\n=== ACCEPTANCE CRITERIA ===")
            for i, ac in enumerate(state.acceptance_criteria, 1):
                parts.append(f"  {i}. {ac}")

        parts.append(f"\n=== TECH STACK ===")
        parts.append(f"Build System: {state.build_system}")
        parts.append(f"Tech Stack: {json.dumps(state.tech_stack)}")

        if state.execution_plan:
            test_steps = [s for s in state.execution_plan if s.get("agent") == "test_agent"]
            if test_steps:
                parts.append("\n=== PLAN STEPS FOR YOU ===")
                for step in test_steps:
                    parts.append(f"  Step {step.get('step_number')}: {step.get('description')}")
                    if step.get("files_involved"):
                        parts.append(f"    Files: {', '.join(step['files_involved'])}")

        if state.relevant_files:
            parts.append(f"\n=== RELEVANT SOURCE FILES ===")
            for f in state.relevant_files[:15]:
                parts.append(f"  - {f}")

        parts.append(
            "\nWrite tests for the acceptance criteria above. "
            "Follow existing test patterns. Tests must FAIL initially."
        )
        return "\n".join(parts)

    def extract_result(self, state: PipelineState, messages: list[dict]) -> PipelineState:
        last = self._get_last_assistant_message(messages)
        parsed = self._extract_json(last)

        if parsed:
            state.test_files_created = parsed.get("test_files_created", state.test_files_created)
            state.test_scenarios = parsed.get("test_scenarios", state.test_scenarios)
            state.initial_test_results = parsed.get("initial_results", state.initial_test_results)
        else:
            # Try to gather from tool calls
            for msg in messages:
                content = msg.get("content", "")
                if "Tool Result [file_tool]" in content and "Wrote" in content:
                    # Extract written file paths
                    match = re.search(r"Wrote \d+ bytes to (\S+)", content)
                    if match:
                        filepath = match.group(1)
                        if "test" in filepath.lower():
                            if filepath not in state.test_files_created:
                                state.test_files_created.append(filepath)

                if "Tool Result [test_tool]" in content:
                    # Extract test results
                    passed = re.search(r"(\d+) passed", content)
                    failed = re.search(r"(\d+) failed", content)
                    state.initial_test_results = {
                        "passed": int(passed.group(1)) if passed else 0,
                        "failed": int(failed.group(1)) if failed else 0,
                    }

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
