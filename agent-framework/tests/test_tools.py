"""Tests for tools — file_tool, build_tool, search_tool, git_tool, jira_tool.

Each tool is tested with mocked external services where needed.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.base_tool import BaseTool, ToolResult
from tools.file_tool import FileTool
from tools.build_tool import BuildTool
from tools.search_tool import SearchTool
from tools.git_tool import GitTool


# ── FileTool Tests ──────────────────────────────────────────────────────


class TestFileTool:
    """Test FileTool read/write/search/replace operations."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Create a temp workspace with sample files."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text(
            "import os\n\ndef hello():\n    print('Hello')\n\ndef world():\n    return 42\n"
        )
        (tmp_path / "src" / "utils.py").write_text(
            "def add(a, b):\n    return a + b\n"
        )
        (tmp_path / "README.md").write_text("# Project\nThis is a test project.\n")
        return tmp_path

    @pytest.fixture
    def tool(self, workspace):
        return FileTool(str(workspace))

    def test_read_existing_file(self, tool):
        result = tool.execute(action="read", filepath="src/main.py")
        assert result.success
        assert "hello" in result.output
        assert "import os" in result.output

    def test_read_missing_file(self, tool):
        result = tool.execute(action="read", filepath="nonexistent.py")
        assert not result.success
        assert "not found" in result.error.lower()

    def test_write_file(self, tool, workspace):
        result = tool.execute(
            action="write",
            filepath="src/new_file.py",
            content="print('new')\n",
        )
        assert result.success
        assert (workspace / "src" / "new_file.py").exists()

    def test_write_creates_directories(self, tool, workspace):
        result = tool.execute(
            action="write",
            filepath="deep/nested/dir/file.txt",
            content="content",
        )
        assert result.success
        assert (workspace / "deep" / "nested" / "dir" / "file.txt").exists()

    def test_search_pattern(self, tool):
        result = tool.execute(action="search", pattern="def hello", directory=".")
        assert result.success
        assert "main.py" in result.output

    def test_search_no_matches(self, tool):
        result = tool.execute(action="search", pattern="nonexistent_function_xyz")
        assert result.success
        assert "No matches" in result.output

    def test_replace(self, tool, workspace):
        result = tool.execute(
            action="replace",
            filepath="src/main.py",
            old_text="print('Hello')",
            new_text="print('Hi')",
        )
        assert result.success
        content = (workspace / "src" / "main.py").read_text()
        assert "print('Hi')" in content
        assert "print('Hello')" not in content

    def test_replace_not_found(self, tool):
        result = tool.execute(
            action="replace",
            filepath="src/main.py",
            old_text="THIS DOES NOT EXIST",
            new_text="replacement",
        )
        assert not result.success
        assert "not found" in result.error.lower()

    def test_list_files(self, tool):
        result = tool.execute(action="list_files", directory=".", pattern="*.py")
        assert result.success
        assert "main.py" in result.output

    def test_path_traversal_blocked(self, tool):
        result = tool.execute(action="read", filepath="../../etc/passwd")
        assert not result.success
        assert "escapes" in result.error.lower()

    def test_get_file_info(self, tool):
        result = tool.execute(action="get_file_info", filepath="src/main.py")
        assert result.success
        info = json.loads(result.output)
        assert info["language"] == "python"
        assert info["is_file"] is True


# ── BuildTool Tests ─────────────────────────────────────────────────────


class TestBuildTool:
    """Test BuildTool auto-detection and command execution."""

    @pytest.fixture
    def maven_workspace(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project></project>")
        return tmp_path

    @pytest.fixture
    def npm_workspace(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        return tmp_path

    def test_detect_maven(self, maven_workspace):
        tool = BuildTool(str(maven_workspace))
        assert tool.detect_build_system() == "maven"

    def test_detect_npm(self, npm_workspace):
        tool = BuildTool(str(npm_workspace))
        assert tool.detect_build_system() == "npm"

    def test_detect_unknown(self, tmp_path):
        tool = BuildTool(str(tmp_path))
        assert tool.detect_build_system() == "unknown"

    def test_detect_action(self, maven_workspace):
        tool = BuildTool(str(maven_workspace))
        result = tool.execute(action="detect")
        assert result.success
        assert "maven" in result.output.lower()

    @patch("subprocess.run")
    def test_compile_success(self, mock_run, maven_workspace):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="BUILD SUCCESS",
            stderr="",
        )
        tool = BuildTool(str(maven_workspace))
        result = tool.execute(action="compile")
        assert result.success

    @patch("subprocess.run")
    def test_compile_failure(self, mock_run, maven_workspace):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="BUILD FAILURE\n[ERROR] compilation error",
        )
        tool = BuildTool(str(maven_workspace))
        result = tool.execute(action="compile")
        assert not result.success
        assert "BUILD FAILED" in result.error

    def test_dangerous_command_blocked(self, tmp_path):
        tool = BuildTool(str(tmp_path))
        result = tool.execute(action="custom", command="rm -rf /")
        assert not result.success
        assert "dangerous" in result.error.lower() or "Blocked" in result.error


# ── SearchTool Tests ────────────────────────────────────────────────────


class TestSearchTool:
    """Test SearchTool regex and file search."""

    @pytest.fixture
    def workspace(self, tmp_path):
        (tmp_path / "app.py").write_text("class UserService:\n    def get_user(self):\n        pass\n")
        (tmp_path / "test_app.py").write_text("def test_get_user():\n    assert True\n")
        (tmp_path / "config.yaml").write_text("database:\n  host: localhost\n")
        return tmp_path

    @pytest.fixture
    def tool(self, workspace):
        return SearchTool(str(workspace))

    def test_regex_search(self, tool):
        result = tool.execute(action="regex_search", pattern="class\\s+\\w+")
        assert result.success
        assert "UserService" in result.output

    def test_find_files(self, tool):
        result = tool.execute(action="find_files", pattern="*.py")
        assert result.success
        assert "app.py" in result.output

    def test_find_symbol(self, tool):
        result = tool.execute(action="find_symbol", symbol="get_user")
        assert result.success
        assert "get_user" in result.output

    def test_no_results(self, tool):
        result = tool.execute(action="regex_search", pattern="zzz_nonexistent_zzz")
        assert result.success
        assert "No matches" in result.output


# ── GitTool Tests ───────────────────────────────────────────────────────


class TestGitTool:
    """Test GitTool with mocked subprocess calls."""

    @pytest.fixture
    def config(self):
        return {
            "default_remote": "origin",
            "commit_prefix": "[agent]",
            "provider": "github",
            "api_token": "test-token",
            "api_url": "https://api.github.com",
        }

    @pytest.fixture
    def tool(self, config, tmp_path):
        return GitTool(config, str(tmp_path))

    @patch("subprocess.run")
    def test_diff(self, mock_run, tool):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="diff --git a/file.py b/file.py\n+new line",
            stderr="",
        )
        result = tool.execute(action="diff")
        assert result.success

    @patch("subprocess.run")
    def test_get_changed_files(self, mock_run, tool):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=" M src/main.py\n?? new_file.py\n",
            stderr="",
        )
        result = tool.execute(action="get_changed_files")
        assert result.success
        data = json.loads(result.output)
        assert "src/main.py" in data["modified"]
        assert "new_file.py" in data["untracked"]

    def test_dangerous_command_blocked(self, tool):
        """Ensure force push is blocked."""
        with pytest.raises(Exception):
            tool._run(["push", "--force", "origin", "main"])

    def test_parse_github_url(self):
        owner, repo = GitTool._parse_repo_url("https://github.com/myorg/myrepo.git")
        assert owner == "myorg"
        assert repo == "myrepo"

    def test_parse_ssh_url(self):
        owner, repo = GitTool._parse_repo_url("git@github.com:myorg/myrepo.git")
        assert owner == "myorg"
        assert repo == "myrepo"
