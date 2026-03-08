"""Context agent — extracts and structures Jira story requirements.

Fetches the Jira story, parses acceptance criteria, classifies story type,
and produces a structured summary for downstream agents.
"""

from __future__ import annotations

import json
from typing import Any

from agents.base_agent import BaseAgent
from core.state import PipelineState


class ContextAgent(BaseAgent):
    """Agent 1: Jira story understanding and requirements extraction."""

    @property
    def name(self) -> str:
        return "context_agent"

    @property
    def system_prompt(self) -> str:
        return """You are a requirements analyst agent. Your job is to deeply understand a Jira story
and extract structured context that other agents will use to implement the work.

You have access to the jira_tool to fetch story details.

Your task:
1. Fetch the Jira story by ID using jira_tool with action "get_story"
2. Extract the title, description, and all acceptance criteria
3. Identify the story type (bug fix, new feature, upgrade/migration, test writing)
4. Extract any technical constraints mentioned
5. Check for linked stories or subtasks that provide additional context
6. Produce a clear, structured summary

When calling a tool, use this format:
ACTION: jira_tool
ARGS:
```json
{"action": "get_story", "jira_id": "PROJ-1234"}
```

When you have gathered all information, respond with:
COMPLETE:
RESULT:
```json
{
  "title": "...",
  "description": "...",
  "acceptance_criteria": ["AC1", "AC2"],
  "story_type": "feature|bug|upgrade|test",
  "technical_constraints": ["..."],
  "linked_issues": ["..."]
}
```"""

    def build_initial_message(self, state: PipelineState) -> str:
        return (
            f"Please analyze the Jira story: {state.jira_id}\n"
            f"Task type hint: {state.task_type}\n\n"
            f"Fetch the story details and extract structured requirements."
        )

    def extract_result(self, state: PipelineState, messages: list[dict]) -> PipelineState:
        """Parse the final agent response and update state."""
        last = self._get_last_assistant_message(messages)

        # Try to parse JSON from the response
        parsed = self._extract_json(last)
        if parsed:
            state.story_title = parsed.get("title", state.story_title)
            state.story_description = parsed.get("description", state.story_description)
            state.acceptance_criteria = parsed.get("acceptance_criteria", state.acceptance_criteria)
            state.story_type = parsed.get("story_type", state.story_type or state.task_type)
            state.story_metadata = {
                "technical_constraints": parsed.get("technical_constraints", []),
                "linked_issues": parsed.get("linked_issues", []),
            }
        else:
            # Fallback: try to extract from tool results
            for msg in messages:
                if msg["role"] == "user" and "Tool Result [jira_tool]" in msg["content"]:
                    try:
                        data = json.loads(
                            msg["content"].split("Tool Result [jira_tool]:\n", 1)[1]
                        )
                        state.story_title = data.get("title", "")
                        state.story_description = data.get("description", "")
                        state.acceptance_criteria = data.get("acceptance_criteria", [])
                        state.story_type = data.get("story_type", state.task_type)
                    except (json.JSONDecodeError, IndexError):
                        pass

        return state

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract JSON from the response text."""
        import re
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        # Try the whole text as JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        return None
