"""Git operations tool — clone, branch, commit, push, PR creation.

All operations run via subprocess with timeouts and path safety checks.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import requests

from core.exceptions import ToolExecutionError
from core.logger import get_logger
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("git_tool")


class GitTool(BaseTool):
    """Git operations sandboxed to the workspace directory."""

    def __init__(self, config: dict, workspace: str) -> None:
        self._workspace = Path(workspace).resolve()
        self._remote = config.get("default_remote", "origin")
        self._commit_prefix = config.get("commit_prefix", "[agent]")
        self._pr_template = config.get("pr_template", "Agent-generated PR for {jira_id}")
        self._provider = config.get("provider", "github")  # github | bitbucket
        self._api_token = config.get("api_token", "")
        self._api_url = config.get("api_url", "https://api.github.com")
        self._timeout = 120

    @property
    def name(self) -> str:
        return "git_tool"

    @property
    def description(self) -> str:
        return (
            "Git operations: clone, create_branch, commit, push, create_pr, "
            "diff, reset_file, get_changed_files."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "diff")
        dispatch = {
            "clone": self._clone,
            "create_branch": self._create_branch,
            "commit": self._commit,
            "push": self._push,
            "create_pr": self._create_pr,
            "diff": self._diff,
            "reset_file": self._reset_file,
            "get_changed_files": self._get_changed_files,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        try:
            return handler(**kwargs)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"Git command timed out after {self._timeout}s")
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Git error: {exc}")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _run(self, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
        """Run a git command with safety checks."""
        # Block dangerous commands
        cmd_str = " ".join(args)
        dangerous = ["rm -rf", "push --force", "push -f", "clean -fd"]
        for d in dangerous:
            if d in cmd_str:
                raise ToolExecutionError("git_tool", f"Blocked dangerous command: {cmd_str}")

        work_dir = cwd or str(self._workspace)
        return subprocess.run(
            ["git"] + args,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )

    def _safe_path(self, filepath: str) -> Path:
        resolved = (self._workspace / filepath).resolve()
        if not str(resolved).startswith(str(self._workspace)):
            raise ToolExecutionError("git_tool", f"Path escapes workspace: {filepath}")
        return resolved

    # ── Actions ─────────────────────────────────────────────────────────

    def _clone(self, **kwargs: Any) -> ToolResult:
        repo_url: str = kwargs["repo_url"]
        branch: str = kwargs.get("branch", "main")
        working_dir: str = kwargs.get("working_dir", str(self._workspace))

        target = Path(working_dir).resolve()
        target.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            ["git", "clone", "--branch", branch, "--single-branch", repo_url, str(target)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            # Maybe directory already has a repo — try fetch+checkout instead
            if "already exists" in result.stderr:
                self._run(["fetch", self._remote], cwd=str(target))
                self._run(["checkout", branch], cwd=str(target))
                self._run(["pull", self._remote, branch], cwd=str(target))
                return ToolResult(success=True, output=f"Updated existing repo at {target}")
            return ToolResult(success=False, output="", error=result.stderr)

        return ToolResult(success=True, output=f"Cloned {repo_url} (branch: {branch}) to {target}")

    def _create_branch(self, **kwargs: Any) -> ToolResult:
        branch_name: str = kwargs["branch_name"]
        result = self._run(["checkout", "-b", branch_name])
        if result.returncode != 0:
            return ToolResult(success=False, output="", error=result.stderr)
        return ToolResult(success=True, output=f"Created and switched to branch: {branch_name}")

    def _commit(self, **kwargs: Any) -> ToolResult:
        message: str = kwargs["message"]
        files: list[str] = kwargs.get("files", [])

        # Stage files
        if files:
            for f in files:
                self._safe_path(f)  # validate
            result = self._run(["add"] + files)
        else:
            result = self._run(["add", "-A"])

        if result.returncode != 0:
            return ToolResult(success=False, output="", error=f"git add failed: {result.stderr}")

        full_message = f"{self._commit_prefix} {message}"
        result = self._run(["commit", "-m", full_message])
        if result.returncode != 0:
            return ToolResult(success=False, output="", error=f"git commit failed: {result.stderr}")

        return ToolResult(success=True, output=f"Committed: {full_message}")

    def _push(self, **kwargs: Any) -> ToolResult:
        branch: str = kwargs.get("branch", "")
        if not branch:
            # Detect current branch
            result = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
            branch = result.stdout.strip()

        result = self._run(["push", self._remote, branch])
        if result.returncode != 0:
            # Try setting upstream
            result = self._run(["push", "--set-upstream", self._remote, branch])
            if result.returncode != 0:
                return ToolResult(success=False, output="", error=result.stderr)

        return ToolResult(success=True, output=f"Pushed to {self._remote}/{branch}")

    def _create_pr(self, **kwargs: Any) -> ToolResult:
        title: str = kwargs["title"]
        body: str = kwargs.get("body", "")
        source_branch: str = kwargs["source_branch"]
        target_branch: str = kwargs.get("target_branch", "main")

        if self._provider == "github":
            return self._create_github_pr(title, body, source_branch, target_branch)
        elif self._provider == "bitbucket":
            return self._create_bitbucket_pr(title, body, source_branch, target_branch)
        else:
            return ToolResult(success=False, output="", error=f"Unsupported provider: {self._provider}")

    def _create_github_pr(self, title: str, body: str, head: str, base: str) -> ToolResult:
        # Extract owner/repo from remote URL
        result = self._run(["remote", "get-url", self._remote])
        remote_url = result.stdout.strip()
        owner, repo = self._parse_repo_url(remote_url)

        url = f"{self._api_url}/repos/{owner}/{repo}/pulls"
        headers = {"Authorization": f"token {self._api_token}", "Accept": "application/vnd.github.v3+json"}
        payload = {"title": title, "body": body, "head": head, "base": base}

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code not in (200, 201):
            return ToolResult(success=False, output="", error=f"PR creation failed: {resp.text[:500]}")

        pr_data = resp.json()
        return ToolResult(
            success=True,
            output=f"PR created: {pr_data.get('html_url', '')}",
            metadata={"pr_url": pr_data.get("html_url", ""), "pr_number": pr_data.get("number")},
        )

    def _create_bitbucket_pr(self, title: str, body: str, head: str, base: str) -> ToolResult:
        result = self._run(["remote", "get-url", self._remote])
        remote_url = result.stdout.strip()
        owner, repo = self._parse_repo_url(remote_url)

        url = f"{self._api_url}/2.0/repositories/{owner}/{repo}/pullrequests"
        headers = {"Authorization": f"Bearer {self._api_token}", "Content-Type": "application/json"}
        payload = {
            "title": title,
            "description": body,
            "source": {"branch": {"name": head}},
            "destination": {"branch": {"name": base}},
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code not in (200, 201):
            return ToolResult(success=False, output="", error=f"PR creation failed: {resp.text[:500]}")

        pr_data = resp.json()
        pr_url = pr_data.get("links", {}).get("html", {}).get("href", "")
        return ToolResult(success=True, output=f"PR created: {pr_url}", metadata={"pr_url": pr_url})

    def _diff(self, **kwargs: Any) -> ToolResult:
        result = self._run(["diff"])
        staged = self._run(["diff", "--staged"])
        output = ""
        if staged.stdout.strip():
            output += f"=== STAGED ===\n{staged.stdout}\n"
        if result.stdout.strip():
            output += f"=== UNSTAGED ===\n{result.stdout}\n"
        if not output:
            output = "No changes."
        return ToolResult(success=True, output=output)

    def _reset_file(self, **kwargs: Any) -> ToolResult:
        filepath: str = kwargs["filepath"]
        self._safe_path(filepath)
        result = self._run(["checkout", "HEAD", "--", filepath])
        if result.returncode != 0:
            return ToolResult(success=False, output="", error=result.stderr)
        return ToolResult(success=True, output=f"Reset {filepath} to HEAD")

    def _get_changed_files(self, **kwargs: Any) -> ToolResult:
        result = self._run(["status", "--porcelain"])
        if result.returncode != 0:
            return ToolResult(success=False, output="", error=result.stderr)

        files = {"modified": [], "added": [], "deleted": [], "untracked": []}
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            status = line[:2].strip()
            filepath = line[3:].strip()
            if status in ("M", "MM"):
                files["modified"].append(filepath)
            elif status in ("A", "AM"):
                files["added"].append(filepath)
            elif status == "D":
                files["deleted"].append(filepath)
            elif status == "??":
                files["untracked"].append(filepath)

        return ToolResult(success=True, output=json.dumps(files, indent=2), metadata=files)

    @staticmethod
    def _parse_repo_url(url: str) -> tuple[str, str]:
        """Extract (owner, repo) from git remote URL."""
        # SSH: git@github.com:owner/repo.git
        ssh_match = re.match(r".*[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
        if ssh_match:
            return ssh_match.group(1), ssh_match.group(2)
        # HTTPS: https://github.com/owner/repo.git
        https_match = re.match(r"https?://[^/]+/([^/]+)/([^/]+?)(?:\.git)?$", url)
        if https_match:
            return https_match.group(1), https_match.group(2)
        raise ToolExecutionError("git_tool", f"Cannot parse repo URL: {url}")
