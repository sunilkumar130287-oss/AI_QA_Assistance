"""Repo agent — scans and understands the codebase structure.

Detects tech stack, builds dependency graphs, identifies relevant files,
and generates structural skeletons for downstream agents.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents.base_agent import BaseAgent
from core.state import PipelineState


class RepoAgent(BaseAgent):
    """Agent 2: Codebase analysis and structural understanding."""

    @property
    def name(self) -> str:
        return "repo_agent"

    @property
    def system_prompt(self) -> str:
        return """You are a codebase analysis agent. Your job is to understand a repository's structure,
tech stack, and identify the files most relevant to the current task.

You have access to: file_tool, ast_tool, search_tool

Your task:
1. List the project structure (top 3 levels) using file_tool action "list_files"
2. Detect the tech stack: language(s), framework(s), build system, test framework
   - Check pom.xml, build.gradle, package.json, angular.json, pyproject.toml
3. Detect framework versions (e.g., Spring Boot version from pom.xml)
4. Build a dependency graph using ast_tool action "build_dependency_graph"
5. Based on the task context provided, identify the 10-20 most relevant files
6. Generate structural skeletons of key files using ast_tool action "get_file_skeleton"
7. Identify the build command and test command for this project

When calling a tool, use this format:
ACTION: file_tool
ARGS:
```json
{"action": "list_files", "directory": ".", "recursive": true}
```

When complete, respond with:
COMPLETE:
RESULT:
```json
{
  "tech_stack": {"languages": [], "frameworks": [], "build_system": "", "test_framework": "", "versions": {}},
  "project_structure": "tree output",
  "relevant_files": ["file1.java", "file2.java"],
  "build_command": "mvn compile",
  "test_command": "mvn test",
  "build_system": "maven"
}
```"""

    def build_initial_message(self, state: PipelineState) -> str:
        context = f"Task: {state.task_type}\n"
        if state.story_title:
            context += f"Story: {state.story_title}\n"
        if state.story_description:
            context += f"Description: {state.story_description[:500]}\n"
        if state.acceptance_criteria:
            context += "Acceptance Criteria:\n"
            for ac in state.acceptance_criteria:
                context += f"  - {ac}\n"

        return (
            f"Analyze the codebase in the current working directory.\n\n"
            f"Context for relevance:\n{context}\n"
            f"Identify the tech stack, build system, and the files most relevant "
            f"to the task described above."
        )

    def extract_result(self, state: PipelineState, messages: list[dict]) -> PipelineState:
        last = self._get_last_assistant_message(messages)
        parsed = self._extract_json(last)

        if parsed:
            state.tech_stack = parsed.get("tech_stack", state.tech_stack)
            state.project_structure = parsed.get("project_structure", state.project_structure)
            state.relevant_files = parsed.get("relevant_files", state.relevant_files)
            state.build_system = parsed.get("build_system", state.build_system)

        # Also gather info from tool results
        for msg in messages:
            content = msg.get("content", "")
            if "Tool Result [ast_tool]" in content and "dependency graph" in content.lower():
                state.repo_map = {"raw": content[:2000]}

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
