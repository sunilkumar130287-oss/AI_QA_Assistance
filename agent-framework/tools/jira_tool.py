"""Jira REST API integration tool.

Fetches story details, acceptance criteria, subtasks, and supports status
transitions.  Works with both Jira REST API v2 and v3 response shapes.
"""

from __future__ import annotations

import re
from typing import Any

import requests

from core.exceptions import ToolExecutionError
from core.logger import get_logger
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("jira_tool")


class JiraTool(BaseTool):
    """Read and update Jira issues."""

    def __init__(self, config: dict) -> None:
        self._base_url = config["base_url"].rstrip("/")
        self._auth = (config["username"], config["api_token"])
        self._session = requests.Session()
        self._session.auth = self._auth
        self._session.headers.update({"Accept": "application/json"})

    @property
    def name(self) -> str:
        return "jira_tool"

    @property
    def description(self) -> str:
        return (
            "Interact with Jira: get_story, update_story, get_subtasks. "
            "Extracts title, description, acceptance criteria, labels, and more."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "get_story")
        dispatch = {
            "get_story": self._get_story,
            "update_story": self._update_story,
            "get_subtasks": self._get_subtasks,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        try:
            return handler(**kwargs)
        except requests.exceptions.RequestException as exc:
            return ToolResult(success=False, output="", error=f"Jira API error: {exc}")

    # ── Actions ─────────────────────────────────────────────────────────

    def _get_story(self, **kwargs: Any) -> ToolResult:
        jira_id: str = kwargs["jira_id"]
        url = f"{self._base_url}/rest/api/2/issue/{jira_id}"
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        fields = data.get("fields", {})

        # Handle v2 vs v3 description format
        description = self._extract_description(fields.get("description", ""))

        acceptance_criteria = self._extract_acceptance_criteria(description)

        story_type = self._classify_story(fields)

        result = {
            "key": data.get("key", jira_id),
            "title": fields.get("summary", ""),
            "description": description,
            "acceptance_criteria": acceptance_criteria,
            "story_type": story_type,
            "status": fields.get("status", {}).get("name", ""),
            "priority": fields.get("priority", {}).get("name", ""),
            "labels": fields.get("labels", []),
            "components": [c.get("name", "") for c in fields.get("components", [])],
            "story_points": fields.get("story_points") or fields.get("customfield_10028"),
            "sprint": self._extract_sprint(fields),
            "linked_issues": self._extract_links(fields.get("issuelinks", [])),
            "subtasks": [
                {"key": s["key"], "summary": s["fields"]["summary"], "status": s["fields"]["status"]["name"]}
                for s in fields.get("subtasks", [])
            ],
            "comments": self._extract_comments(fields.get("comment", {})),
        }
        import json
        return ToolResult(success=True, output=json.dumps(result, indent=2), metadata=result)

    def _update_story(self, **kwargs: Any) -> ToolResult:
        jira_id: str = kwargs["jira_id"]
        status: str | None = kwargs.get("status")
        comment: str | None = kwargs.get("comment")

        if comment:
            url = f"{self._base_url}/rest/api/2/issue/{jira_id}/comment"
            resp = self._session.post(url, json={"body": comment}, timeout=30)
            resp.raise_for_status()

        if status:
            transitions = self._get_transitions(jira_id)
            target = next((t for t in transitions if t["name"].lower() == status.lower()), None)
            if target is None:
                return ToolResult(
                    success=False, output="",
                    error=f"Transition to '{status}' not available. Options: {[t['name'] for t in transitions]}",
                )
            url = f"{self._base_url}/rest/api/2/issue/{jira_id}/transitions"
            self._session.post(url, json={"transition": {"id": target["id"]}}, timeout=30)

        return ToolResult(success=True, output=f"Updated {jira_id}")

    def _get_subtasks(self, **kwargs: Any) -> ToolResult:
        jira_id: str = kwargs["jira_id"]
        url = f"{self._base_url}/rest/api/2/issue/{jira_id}"
        resp = self._session.get(url, params={"fields": "subtasks"}, timeout=30)
        resp.raise_for_status()
        subtasks = resp.json().get("fields", {}).get("subtasks", [])
        result = [
            {"key": s["key"], "summary": s["fields"]["summary"], "status": s["fields"]["status"]["name"]}
            for s in subtasks
        ]
        import json
        return ToolResult(success=True, output=json.dumps(result, indent=2), metadata={"subtasks": result})

    # ── Helpers ──────────────────────────────────────────────────────────

    def _extract_description(self, desc: Any) -> str:
        """Handle both plain-text (v2) and ADF (v3) description formats."""
        if isinstance(desc, str):
            return desc
        if isinstance(desc, dict):
            # Atlassian Document Format — flatten to text
            return self._adf_to_text(desc)
        return str(desc) if desc else ""

    def _adf_to_text(self, node: dict) -> str:
        """Recursively convert ADF JSON to plain text."""
        if node.get("type") == "text":
            return node.get("text", "")
        parts: list[str] = []
        for child in node.get("content", []):
            parts.append(self._adf_to_text(child))
        joiner = "\n" if node.get("type") in ("paragraph", "bulletList", "orderedList", "listItem") else ""
        return joiner.join(parts)

    @staticmethod
    def _extract_acceptance_criteria(description: str) -> list[str]:
        """Parse ACs from description — handles bullet lists, numbered lists, and AC headers."""
        criteria: list[str] = []
        if not description:
            return criteria

        # Look for an "Acceptance Criteria" section
        ac_section = ""
        ac_pattern = re.compile(
            r"(?:acceptance\s+criteria|ac[:\s])",
            re.IGNORECASE,
        )
        lines = description.split("\n")
        in_ac = False
        for line in lines:
            if ac_pattern.search(line):
                in_ac = True
                continue
            if in_ac:
                stripped = line.strip()
                if not stripped:
                    continue
                # Stop at next major heading
                if stripped.startswith("#") or stripped.startswith("h2.") or stripped.startswith("h3."):
                    break
                # Remove bullet / number prefixes
                cleaned = re.sub(r"^[\-\*\d\.\)]+\s*", "", stripped)
                if cleaned:
                    criteria.append(cleaned)

        # Fallback: grab any bullet/numbered items if no explicit AC section
        if not criteria:
            for line in lines:
                stripped = line.strip()
                if re.match(r"^[\-\*]\s+.+", stripped) or re.match(r"^\d+[\.\)]\s+.+", stripped):
                    cleaned = re.sub(r"^[\-\*\d\.\)]+\s*", "", stripped)
                    if cleaned:
                        criteria.append(cleaned)

        return criteria

    @staticmethod
    def _classify_story(fields: dict) -> str:
        """Classify story as bug, feature, upgrade, or test."""
        issue_type = fields.get("issuetype", {}).get("name", "").lower()
        labels = [l.lower() for l in fields.get("labels", [])]
        summary = fields.get("summary", "").lower()

        if issue_type == "bug" or "bug" in labels:
            return "bug"
        if any(kw in summary for kw in ("upgrade", "migration", "migrate", "update version")):
            return "upgrade"
        if any(kw in summary for kw in ("write test", "add test", "test coverage")):
            return "test"
        return "feature"

    @staticmethod
    def _extract_sprint(fields: dict) -> str:
        sprint = fields.get("sprint")
        if isinstance(sprint, dict):
            return sprint.get("name", "")
        # customfield fallback
        cf = fields.get("customfield_10020")
        if isinstance(cf, list) and cf:
            return cf[-1].get("name", "") if isinstance(cf[-1], dict) else str(cf[-1])
        return ""

    @staticmethod
    def _extract_links(links: list[dict]) -> list[dict]:
        result = []
        for link in links:
            entry: dict[str, str] = {"type": link.get("type", {}).get("name", "")}
            if "inwardIssue" in link:
                entry["key"] = link["inwardIssue"]["key"]
                entry["summary"] = link["inwardIssue"]["fields"]["summary"]
            elif "outwardIssue" in link:
                entry["key"] = link["outwardIssue"]["key"]
                entry["summary"] = link["outwardIssue"]["fields"]["summary"]
            result.append(entry)
        return result

    @staticmethod
    def _extract_comments(comment_field: dict) -> list[dict]:
        comments = comment_field.get("comments", [])
        return [
            {
                "author": c.get("author", {}).get("displayName", ""),
                "body": c.get("body", "")[:500],
                "created": c.get("created", ""),
            }
            for c in comments[-5:]  # last 5 comments only
        ]

    def _get_transitions(self, jira_id: str) -> list[dict]:
        url = f"{self._base_url}/rest/api/2/issue/{jira_id}/transitions"
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json().get("transitions", [])
