"""Language Server Protocol client tool.

Provides IDE-like capabilities: go-to-definition, find-references,
hover info, and diagnostics. Falls back to regex-based search when
no LSP server is available.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from core.logger import get_logger
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("lsp_tool")


class LSPTool(BaseTool):
    """Language Server Protocol client for IDE-like code intelligence.

    When an LSP server is not available, falls back to regex-based
    analysis using the AST tool patterns.
    """

    def __init__(self, workspace: str) -> None:
        self._workspace = Path(workspace).resolve()

    @property
    def name(self) -> str:
        return "lsp_tool"

    @property
    def description(self) -> str:
        return (
            "Code intelligence: go_to_definition, find_references, hover, "
            "diagnostics. Falls back to regex when no LSP server available."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "go_to_definition")
        dispatch = {
            "go_to_definition": self._go_to_definition,
            "find_references": self._find_references,
            "hover": self._hover,
            "diagnostics": self._diagnostics,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        try:
            return handler(**kwargs)
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"LSP error: {exc}")

    # ── Actions (regex fallback) ────────────────────────────────────────

    def _go_to_definition(self, **kwargs: Any) -> ToolResult:
        """Find the definition of a symbol using regex patterns."""
        symbol: str = kwargs["symbol"]
        file_hint: str = kwargs.get("file", "")

        patterns = [
            rf"(?:class|interface|enum)\s+{re.escape(symbol)}\b",
            rf"def\s+{re.escape(symbol)}\s*\(",
            rf"function\s+{re.escape(symbol)}\s*\(",
            rf"(?:public|private|protected)\s+\S+\s+{re.escape(symbol)}\s*\(",
            rf"(?:const|let|var)\s+{re.escape(symbol)}\s*=",
        ]

        search_paths = self._get_search_paths(file_hint)
        combined = "|".join(patterns)
        regex = re.compile(combined)

        for path in search_paths:
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for i, line in enumerate(content.split("\n")):
                if regex.search(line):
                    rel = str(path.relative_to(self._workspace))
                    return ToolResult(
                        success=True,
                        output=f"Definition found: {rel}:{i + 1}\n  {line.strip()}",
                        metadata={"file": rel, "line": i + 1, "content": line.strip()},
                    )

        return ToolResult(
            success=True,
            output=f"Definition not found for '{symbol}' (regex fallback)",
        )

    def _find_references(self, **kwargs: Any) -> ToolResult:
        """Find all usages of a symbol."""
        symbol: str = kwargs["symbol"]
        regex = re.compile(rf"\b{re.escape(symbol)}\b")
        refs: list[dict] = []

        for path in self._source_files():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel = str(path.relative_to(self._workspace))
            for i, line in enumerate(content.split("\n")):
                if regex.search(line):
                    refs.append({"file": rel, "line": i + 1, "content": line.strip()[:200]})
                    if len(refs) >= 50:
                        break
            if len(refs) >= 50:
                break

        if not refs:
            return ToolResult(success=True, output=f"No references found for '{symbol}'")

        lines = [f"Found {len(refs)} reference(s) for '{symbol}':"]
        for r in refs:
            lines.append(f"  {r['file']}:{r['line']} — {r['content']}")

        return ToolResult(success=True, output="\n".join(lines), metadata={"references": refs})

    def _hover(self, **kwargs: Any) -> ToolResult:
        """Get type/documentation info for a symbol (regex fallback)."""
        symbol: str = kwargs["symbol"]
        filepath: str = kwargs.get("file", "")

        if not filepath:
            return ToolResult(success=True, output=f"Hover info unavailable for '{symbol}' (no LSP)")

        path = (self._workspace / filepath).resolve()
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {filepath}")

        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")

        # Find the symbol and extract surrounding context
        for i, line in enumerate(lines):
            if re.search(rf"\b{re.escape(symbol)}\b", line):
                # Look for docstring/comment above
                doc_lines: list[str] = []
                for j in range(max(0, i - 5), i):
                    l = lines[j].strip()
                    if l.startswith(("#", "//", "/*", "*", "/**", '"""', "'''")):
                        doc_lines.append(l)

                return ToolResult(
                    success=True,
                    output=f"Symbol: {symbol}\nFile: {filepath}:{i + 1}\n"
                           f"Definition: {line.strip()}\n"
                           f"Documentation: {' '.join(doc_lines) if doc_lines else 'N/A'}",
                )

        return ToolResult(success=True, output=f"Symbol '{symbol}' not found in {filepath}")

    def _diagnostics(self, **kwargs: Any) -> ToolResult:
        """Run basic diagnostics (syntax check) on a file."""
        filepath: str = kwargs["filepath"]
        path = (self._workspace / filepath).resolve()
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {filepath}")

        ext = path.suffix.lower()
        content = path.read_text(encoding="utf-8", errors="replace")

        if ext == ".py":
            return self._python_diagnostics(content, filepath)
        elif ext == ".java":
            return self._java_diagnostics(content, filepath)

        return ToolResult(success=True, output=f"No diagnostics available for {ext}")

    # ── Language-specific diagnostics ───────────────────────────────────

    @staticmethod
    def _python_diagnostics(content: str, filepath: str) -> ToolResult:
        """Check Python syntax."""
        import ast as python_ast

        try:
            python_ast.parse(content)
            return ToolResult(success=True, output=f"{filepath}: No syntax errors")
        except SyntaxError as exc:
            return ToolResult(
                success=False,
                output=f"{filepath}:{exc.lineno}: SyntaxError: {exc.msg}",
                error=f"Syntax error at line {exc.lineno}: {exc.msg}",
            )

    @staticmethod
    def _java_diagnostics(content: str, filepath: str) -> ToolResult:
        """Basic Java syntax checks (brace matching, etc.)."""
        issues: list[str] = []

        # Check brace balance
        opens = content.count("{")
        closes = content.count("}")
        if opens != closes:
            issues.append(f"Unbalanced braces: {opens} opening, {closes} closing")

        # Check for unclosed strings
        lines = content.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            quote_count = stripped.count('"') - stripped.count('\\"')
            if quote_count % 2 != 0:
                issues.append(f"Line {i + 1}: Possible unclosed string")

        if not issues:
            return ToolResult(success=True, output=f"{filepath}: No issues detected")

        return ToolResult(
            success=False,
            output="\n".join(issues),
            error=f"{len(issues)} issue(s) found",
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_search_paths(self, file_hint: str) -> list[Path]:
        """Get files to search, prioritizing the hinted file."""
        paths: list[Path] = []
        if file_hint:
            hint_path = (self._workspace / file_hint).resolve()
            if hint_path.is_file():
                paths.append(hint_path)
        paths.extend(self._source_files())
        return paths

    def _source_files(self) -> list[Path]:
        skip = {"node_modules", ".git", "target", "build", "dist", "__pycache__"}
        exts = {".py", ".java", ".js", ".ts", ".tsx", ".jsx", ".kt", ".go"}
        results: list[Path] = []
        for path in self._workspace.rglob("*"):
            if path.suffix.lower() in exts and path.is_file():
                if not any(part in skip for part in path.parts):
                    results.append(path)
        return results
