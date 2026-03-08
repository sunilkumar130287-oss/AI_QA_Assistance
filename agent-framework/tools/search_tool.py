"""Codebase search tool — regex and keyword search across files.

Provides contextual search results with surrounding lines, supporting
file-type filtering and configurable result limits.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.logger import get_logger
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("search_tool")

# Default patterns to skip during search
_SKIP_DIRS = {
    "node_modules", ".git", "target", "build", "dist",
    "__pycache__", ".idea", ".vscode", ".gradle", ".mvn",
    "vendor", ".tox", "venv", ".venv", "env",
}

_BINARY_EXTENSIONS = {
    ".class", ".jar", ".war", ".ear", ".pyc", ".pyo",
    ".so", ".dll", ".exe", ".bin", ".dat", ".zip",
    ".tar", ".gz", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".eot",
}


class SearchTool(BaseTool):
    """Search codebase files by regex or keyword."""

    def __init__(self, workspace: str) -> None:
        self._workspace = Path(workspace).resolve()

    @property
    def name(self) -> str:
        return "search_tool"

    @property
    def description(self) -> str:
        return (
            "Search codebase: regex_search (pattern across files), "
            "find_files (by name pattern), find_symbol (class/method name)."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "regex_search")
        dispatch = {
            "regex_search": self._regex_search,
            "find_files": self._find_files,
            "find_symbol": self._find_symbol,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        try:
            return handler(**kwargs)
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Search error: {exc}")

    # ── Actions ─────────────────────────────────────────────────────────

    def _regex_search(self, **kwargs: Any) -> ToolResult:
        pattern: str = kwargs["pattern"]
        file_pattern: str = kwargs.get("file_pattern", "*")
        directory: str = kwargs.get("directory", ".")
        context_lines: int = kwargs.get("context_lines", 2)
        max_results: int = kwargs.get("max_results", 50)

        root = (self._workspace / directory).resolve()
        if not root.is_dir():
            return ToolResult(success=False, output="", error=f"Directory not found: {directory}")

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return ToolResult(success=False, output="", error=f"Invalid regex: {exc}")

        matches: list[str] = []
        files_searched = 0

        for path in self._walk_files(root, file_pattern):
            if len(matches) >= max_results:
                break
            files_searched += 1
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lines = content.split("\n")
            rel = str(path.relative_to(self._workspace))
            for i, line in enumerate(lines):
                if regex.search(line):
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    snippet_lines = []
                    for j in range(start, end):
                        marker = ">>>" if j == i else "   "
                        snippet_lines.append(f"  {j + 1:>5} | {marker} {lines[j]}")
                    matches.append(f"{rel}:{i + 1}\n" + "\n".join(snippet_lines))
                    if len(matches) >= max_results:
                        break

        if not matches:
            return ToolResult(
                success=True,
                output=f"No matches for '{pattern}' (searched {files_searched} files)",
            )
        header = f"Found {len(matches)} match(es) for '{pattern}' in {files_searched} files:"
        return ToolResult(
            success=True,
            output=header + "\n\n" + "\n\n".join(matches),
            metadata={"match_count": len(matches), "files_searched": files_searched},
        )

    def _find_files(self, **kwargs: Any) -> ToolResult:
        pattern: str = kwargs["pattern"]
        directory: str = kwargs.get("directory", ".")
        max_results: int = kwargs.get("max_results", 100)

        root = (self._workspace / directory).resolve()
        if not root.is_dir():
            return ToolResult(success=False, output="", error=f"Directory not found: {directory}")

        results: list[str] = []
        for path in root.rglob(pattern):
            if path.is_file() and not self._should_skip(path):
                results.append(str(path.relative_to(self._workspace)))
                if len(results) >= max_results:
                    break

        if not results:
            return ToolResult(success=True, output=f"No files matching '{pattern}'")
        return ToolResult(
            success=True,
            output="\n".join(sorted(results)),
            metadata={"file_count": len(results)},
        )

    def _find_symbol(self, **kwargs: Any) -> ToolResult:
        """Find a class, function, or method definition by name."""
        symbol: str = kwargs["symbol"]
        file_pattern: str = kwargs.get("file_pattern", "*")

        # Build patterns for common definition styles
        patterns = [
            rf"(?:class|interface|enum)\s+{re.escape(symbol)}\b",  # class/interface
            rf"(?:def|function|func)\s+{re.escape(symbol)}\s*\(",  # function
            rf"(?:public|private|protected|static|\s)+\S+\s+{re.escape(symbol)}\s*\(",  # Java method
            rf"(?:const|let|var|export)\s+{re.escape(symbol)}\b",  # JS/TS variable
        ]
        combined_pattern = "|".join(patterns)

        return self._regex_search(
            pattern=combined_pattern,
            file_pattern=file_pattern,
            context_lines=3,
            max_results=20,
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _walk_files(self, root: Path, pattern: str) -> list[Path]:
        """Walk directory tree, skipping ignored dirs and binary files."""
        results: list[Path] = []
        for path in root.rglob(pattern):
            if path.is_file() and not self._should_skip(path):
                results.append(path)
        return results

    @staticmethod
    def _should_skip(path: Path) -> bool:
        """Check if a path should be excluded from search."""
        # Skip binary files
        if path.suffix.lower() in _BINARY_EXTENSIONS:
            return True
        # Skip ignored directories
        for part in path.parts:
            if part in _SKIP_DIRS:
                return True
        # Skip very large files
        try:
            if path.stat().st_size > 1_000_000:
                return True
        except OSError:
            return True
        return False
