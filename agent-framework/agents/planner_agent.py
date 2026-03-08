"""Planner agent — creates concrete execution plans from context + skill.

Receives Jira context, codebase understanding, and a skill playbook, then
produces an ordered list of steps with validation criteria and rollback plans.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents.base_agent import BaseAgent
from core.state import PipelineState


class PlannerAgent(BaseAgent):
    """Agent 3: Execution planning with TDFlow enforcement."""

    @property
    def name(self) -> str:
        return "planner_agent"

    @property
    def system_prompt(self) -> str:
        return """You are a planning agent. You receive:
- Jira story context (from context_agent)
- Codebase understanding (from repo_agent)
- A skill playbook (YAML with step-by-step instructions for this task type)

Your job is to create a concrete, ordered execution plan.

Each step in the plan must specify:
- step_number: sequential order
- description: what to do
- agent: which agent executes this (test_agent or coder_agent)
- files_involved: which files will be read or modified
- validation: how to verify this step succeeded (e.g., "build passes", "test X passes")
- rollback: what to do if this step fails

The plan MUST follow TDFlow:
1. Tests are written BEFORE implementation code
2. Tests must fail initially (proving they test the right thing)
3. Implementation code is written to make tests pass
4. Build must pass after every code change

For upgrade tasks, the plan must be INCREMENTAL:
- One dependency/file change at a time
- Build verification after each change
- Never batch multiple breaking changes together

You do NOT need to call any tools. Analyze the context provided and produce the plan.

Respond with:
COMPLETE:
RESULT:
```json
[
  {
    "step_number": 1,
    "description": "...",
    "agent": "test_agent",
    "files_involved": ["..."],
    "validation": "...",
    "rollback": "..."
  }
]
```"""

    def build_initial_message(self, state: PipelineState) -> str:
        parts: list[str] = []

        parts.append("=== JIRA STORY CONTEXT ===")
        parts.append(f"Title: {state.story_title}")
        parts.append(f"Type: {state.story_type}")
        parts.append(f"Description: {state.story_description[:1000]}")
        if state.acceptance_criteria:
            parts.append("Acceptance Criteria:")
            for i, ac in enumerate(state.acceptance_criteria, 1):
                parts.append(f"  {i}. {ac}")

        parts.append("\n=== CODEBASE CONTEXT ===")
        parts.append(f"Tech Stack: {json.dumps(state.tech_stack)}")
        parts.append(f"Build System: {state.build_system}")
        if state.relevant_files:
            parts.append(f"Relevant Files: {', '.join(state.relevant_files[:20])}")
        if state.project_structure:
            parts.append(f"Structure:\n{state.project_structure[:1000]}")

        parts.append(f"\n=== SKILL CONTEXT ===")
        parts.append(f"Skill: {state.skill_name}")
        if state.skill_context:
            parts.append(f"Skill Instructions:\n{json.dumps(state.skill_context, indent=2)[:2000]}")

        parts.append(
            "\nCreate a concrete execution plan following TDFlow "
            "(tests first, then implementation). Output as a JSON array of steps."
        )

        return "\n".join(parts)

    def extract_result(self, state: PipelineState, messages: list[dict]) -> PipelineState:
        last = self._get_last_assistant_message(messages)

        # Extract JSON array from response
        json_match = re.search(r"```(?:json)?\s*\n(\[.*?\])\s*\n```", last, re.DOTALL)
        if json_match:
            try:
                state.execution_plan = json.loads(json_match.group(1))
                return state
            except json.JSONDecodeError:
                pass

        # Try to find JSON array directly
        array_match = re.search(r"\[.*\]", last, re.DOTALL)
        if array_match:
            try:
                state.execution_plan = json.loads(array_match.group(0))
                return state
            except json.JSONDecodeError:
                pass

        state.record_error(self.name, "Could not parse execution plan from response")
        return state
