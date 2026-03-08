"""File system operations tool — read, write, search, replace, list.

All paths are validated to remain within the configured workspace directory.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from core.exceptions import ToolExecutionError
from core.logger import get_logger
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("file_tool")

# Language detection by extension
_LANG_MAP = {
    ".py": "python", ".java": "java", ".kt": "kotlin",
    ".js": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript", ".go": "go", ".rs": "rust",
    ".rb": "ruby", ".cs": "csharp", ".xml": "xml",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".html": "html", ".css": "css", ".scss": "scss",
    ".sql": "sql", ".sh": "shell", ".bash": "shell",
    ".gradle": "groovy", ".groovy": "groovy",
}


class FileTool(BaseTool):
    """File read/write/search operations sandboxed to the workspace."""

    def __init__(self, workspace: str) -> None:
        self._workspace = Path(workspace).resolve()

    @property
    def name(self) -> str:
        return "file_tool"

    @property
    def description(self) -> str:
        return (
            "File operations: read, write, search, replace, list_files, get_file_info. "
            "All paths relative to workspace root."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "read")
        dispatch = {
            "read": self._read,
            "write": self._write,
            "search": self._search,
            "replace": self._replace,
            "list_files": self._list_files,
            "get_file_info": self._get_file_info,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        try:
            return handler(**kwargs)
        except ToolExecutionError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Unexpected error: {exc}")

    # ── Path safety ─────────────────────────────────────────────────────

    def _safe_path(self, filepath: str) -> Path:
        """Resolve and validate that the path is inside the workspace."""
        resolved = (self._workspace / filepath).resolve()
        if not str(resolved).startswith(str(self._workspace)):
            raise ToolExecutionError("file_tool", f"Path escapes workspace: {filepath}")
        return resolved

    # ── Actions ─────────────────────────────────────────────────────────

    def _read(self, **kwargs: Any) -> ToolResult:
        filepath = kwargs["filepath"]
        path = self._safe_path(filepath)
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {filepath}")
        content = path.read_text(encoding="utf-8", errors="replace")
        # Add line numbers
        numbered = "\n".join(
            f"{i + 1:>6} | {line}" for i, line in enumerate(content.split("\n"))
        )
        return ToolResult(
            success=True, output=numbered,
            metadata={"lines": content.count("\n") + 1, "size": len(content)},
        )

    def _write(self, **kwargs: Any) -> ToolResult:
        filepath = kwargs["filepath"]
        content: str = kwargs["content"]
        path = self._safe_path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(
            success=True,
            output=f"Wrote {len(content)} bytes to {filepath}",
            metadata={"bytes_written": len(content)},
        )

    def _search(self, **kwargs: Any) -> ToolResult:
        pattern: str = kwargs["pattern"]
        directory: str = kwargs.get("directory", ".")
        file_pattern: str = kwargs.get("file_pattern", "*")
        context_lines: int = kwargs.get("context_lines", 2)

        search_root = self._safe_path(directory)
        if not search_root.is_dir():
            return ToolResult(success=False, output="", error=f"Directory not found: {directory}")

        regex = re.compile(pattern, re.IGNORECASE)
        matches: list[str] = []
        max_matches = 50

        for path in search_root.rglob(file_pattern):
            if not path.is_file() or len(matches) >= max_matches:
                break
            # Skip binary and large files
            if path.stat().st_size > 1_000_000:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
            except Exception:
                continue

            rel = str(path.relative_to(self._workspace))
            for i, line in enumerate(lines):
                if regex.search(line):
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    snippet = "\n".join(
                        f"  {j + 1:>5} | {'>>>' if j == i else '   '} {lines[j]}"
                        for j in range(start, end)
                    )
                    matches.append(f"{rel}:{i + 1}\n{snippet}")
                    if len(matches) >= max_matches:
                        break

        if not matches:
            return ToolResult(success=True, output="No matches found.")
        return ToolResult(
            success=True,
            output=f"Found {len(matches)} match(es):\n\n" + "\n\n".join(matches),
            metadata={"match_count": len(matches)},
        )

    def _replace(self, **kwargs: Any) -> ToolResult:
        filepath: str = kwargs["filepath"]
        old_text: str = kwargs["old_text"]
        new_text: str = kwargs["new_text"]

        path = self._safe_path(filepath)
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {filepath}")

        content = path.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count == 0:
            return ToolResult(success=False, output="", error="old_text not found in file")

        updated = content.replace(old_text, new_text)
        path.write_text(updated, encoding="utf-8")
        return ToolResult(
            success=True,
            output=f"Replaced {count} occurrence(s) in {filepath}",
            metadata={"replacements": count},
        )

    def _list_files(self, **kwargs: Any) -> ToolResult:
        directory: str = kwargs.get("directory", ".")
        pattern: str = kwargs.get("pattern", "*")
        recursive: bool = kwargs.get("recursive", True)
        max_files: int = kwargs.get("max_files", 500)

        root = self._safe_path(directory)
        if not root.is_dir():
            return ToolResult(success=False, output="", error=f"Directory not found: {directory}")

        gen = root.rglob(pattern) if recursive else root.glob(pattern)
        files: list[str] = []
        for p in gen:
            if p.is_file():
                files.append(str(p.relative_to(self._workspace)))
                if len(files) >= max_files:
                    break

        return ToolResult(
            success=True,
            output="\n".join(sorted(files)),
            metadata={"file_count": len(files)},
        )

    def _get_file_info(self, **kwargs: Any) -> ToolResult:
        filepath: str = kwargs["filepath"]
        path = self._safe_path(filepath)
        if not path.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {filepath}")

        stat = path.stat()
        ext = path.suffix.lower()
        info = {
            "path": filepath,
            "size_bytes": stat.st_size,
            "is_file": path.is_file(),
            "is_dir": path.is_dir(),
            "language": _LANG_MAP.get(ext, "unknown"),
            "extension": ext,
        }
        return ToolResult(success=True, output=json.dumps(info, indent=2), metadata=info)
