"""AST parsing and dependency graph tool.

Provides multi-language AST analysis using Python's built-in ``ast`` module
for Python files and regex-based parsing for Java/JS/TS. Uses NetworkX for
dependency graphs and PageRank ranking.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import networkx as nx

from core.logger import get_logger
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("ast_tool")

_SKIP_DIRS = {
    "node_modules", ".git", "target", "build", "dist",
    "__pycache__", ".idea", ".vscode", ".gradle", "vendor",
}


class ASTTool(BaseTool):
    """AST parsing, dependency graphs, and symbol lookup."""

    def __init__(self, workspace: str) -> None:
        self._workspace = Path(workspace).resolve()

    @property
    def name(self) -> str:
        return "ast_tool"

    @property
    def description(self) -> str:
        return (
            "AST operations: parse_file, build_dependency_graph, rank_modules, "
            "find_references, get_file_skeleton."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "parse_file")
        dispatch = {
            "parse_file": self._parse_file,
            "build_dependency_graph": self._build_dependency_graph,
            "rank_modules": self._rank_modules,
            "find_references": self._find_references,
            "get_file_skeleton": self._get_file_skeleton,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        try:
            return handler(**kwargs)
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"AST error: {exc}")

    # ── Actions ─────────────────────────────────────────────────────────

    def _parse_file(self, **kwargs: Any) -> ToolResult:
        filepath: str = kwargs["filepath"]
        path = (self._workspace / filepath).resolve()
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {filepath}")

        ext = path.suffix.lower()
        content = path.read_text(encoding="utf-8", errors="replace")

        if ext == ".py":
            result = self._parse_python(content, filepath)
        elif ext == ".java":
            result = self._parse_java(content, filepath)
        elif ext in (".js", ".ts", ".tsx", ".jsx"):
            result = self._parse_js_ts(content, filepath)
        else:
            result = {"filepath": filepath, "language": "unknown", "symbols": []}

        return ToolResult(success=True, output=json.dumps(result, indent=2), metadata=result)

    def _build_dependency_graph(self, **kwargs: Any) -> ToolResult:
        """Build import dependency graph for the project."""
        directory: str = kwargs.get("directory", ".")
        root = (self._workspace / directory).resolve()

        graph = nx.DiGraph()
        file_imports: dict[str, list[str]] = {}

        for path in self._source_files(root):
            rel = str(path.relative_to(self._workspace))
            graph.add_node(rel)
            content = path.read_text(encoding="utf-8", errors="replace")
            imports = self._extract_imports(content, path.suffix.lower())
            file_imports[rel] = imports
            for imp in imports:
                resolved = self._resolve_import(imp, root, path.suffix.lower())
                if resolved:
                    graph.add_edge(rel, resolved)

        edges = list(graph.edges())
        return ToolResult(
            success=True,
            output=f"Dependency graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges",
            metadata={
                "nodes": list(graph.nodes()),
                "edges": edges,
                "file_imports": file_imports,
            },
        )

    def _rank_modules(self, **kwargs: Any) -> ToolResult:
        """Run PageRank on the dependency graph to find most important modules."""
        # First build the graph
        graph_result = self._build_dependency_graph(**kwargs)
        if not graph_result.success:
            return graph_result

        edges = graph_result.metadata.get("edges", [])
        nodes = graph_result.metadata.get("nodes", [])

        G = nx.DiGraph()
        G.add_nodes_from(nodes)
        G.add_edges_from(edges)

        if G.number_of_nodes() == 0:
            return ToolResult(success=True, output="No modules to rank.")

        try:
            ranks = nx.pagerank(G)
        except nx.NetworkXError:
            ranks = {n: 1.0 / G.number_of_nodes() for n in G.nodes()}

        sorted_ranks = sorted(ranks.items(), key=lambda x: x[1], reverse=True)
        top_n = kwargs.get("top_n", 20)
        top = sorted_ranks[:top_n]

        lines = ["Module Importance Ranking (PageRank):"]
        for i, (mod, score) in enumerate(top, 1):
            lines.append(f"  {i:>3}. {mod} (score: {score:.4f})")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={"rankings": dict(top)},
        )

    def _find_references(self, **kwargs: Any) -> ToolResult:
        """Find all usages of a symbol across the codebase."""
        symbol: str = kwargs["symbol"]
        directory: str = kwargs.get("directory", ".")
        root = (self._workspace / directory).resolve()

        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        references: list[dict] = []

        for path in self._source_files(root):
            content = path.read_text(encoding="utf-8", errors="replace")
            rel = str(path.relative_to(self._workspace))
            for i, line in enumerate(content.split("\n")):
                if pattern.search(line):
                    references.append({
                        "file": rel,
                        "line": i + 1,
                        "content": line.strip()[:200],
                    })
                    if len(references) >= 50:
                        break
            if len(references) >= 50:
                break

        if not references:
            return ToolResult(success=True, output=f"No references found for '{symbol}'")

        lines = [f"Found {len(references)} reference(s) for '{symbol}':"]
        for ref in references:
            lines.append(f"  {ref['file']}:{ref['line']} — {ref['content']}")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={"references": references},
        )

    def _get_file_skeleton(self, **kwargs: Any) -> ToolResult:
        """Return signatures only — no method bodies."""
        filepath: str = kwargs["filepath"]
        path = (self._workspace / filepath).resolve()
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {filepath}")

        ext = path.suffix.lower()
        content = path.read_text(encoding="utf-8", errors="replace")

        if ext == ".py":
            skeleton = self._python_skeleton(content)
        elif ext == ".java":
            skeleton = self._java_skeleton(content)
        elif ext in (".js", ".ts", ".tsx", ".jsx"):
            skeleton = self._js_ts_skeleton(content)
        else:
            skeleton = f"# Skeleton not supported for {ext}"

        return ToolResult(success=True, output=skeleton)

    # ── Python parsing ──────────────────────────────────────────────────

    @staticmethod
    def _parse_python(content: str, filepath: str) -> dict:
        """Parse Python file using the ``ast`` module."""
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return {"filepath": filepath, "language": "python", "error": str(exc)}

        symbols: list[dict] = []
        imports: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    {"name": m.name, "line": m.lineno, "args": [a.arg for a in m.args.args]}
                    for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                bases = [ast.dump(b) for b in node.bases]
                symbols.append({
                    "type": "class", "name": node.name, "line": node.lineno,
                    "methods": methods, "bases": bases,
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top-level functions only (methods handled above)
                if not any(isinstance(p, ast.ClassDef) for p in ast.walk(tree)):
                    pass  # simplified
                symbols.append({
                    "type": "function", "name": node.name, "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(module)

        return {
            "filepath": filepath, "language": "python",
            "symbols": symbols, "imports": imports,
        }

    @staticmethod
    def _python_skeleton(content: str) -> str:
        """Generate Python skeleton with signatures only."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return "# Could not parse Python file"

        lines: list[str] = []
        source_lines = content.split("\n")

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                lines.append(ast.get_source_segment(content, node) or f"import ...")
            elif isinstance(node, ast.ImportFrom):
                lines.append(ast.get_source_segment(content, node) or f"from ... import ...")
            elif isinstance(node, ast.ClassDef):
                lines.append("")
                # Get class definition line
                class_line = source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else f"class {node.name}:"
                lines.append(class_line)
                # Docstring
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    lines.append(f'    """{node.body[0].value.value[:100]}"""')
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_line = source_lines[item.lineno - 1] if item.lineno <= len(source_lines) else f"    def {item.name}(...):"
                        lines.append(f"    {func_line.strip()}")
                        lines.append("        ...")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines.append("")
                func_line = source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else f"def {node.name}(...):"
                lines.append(func_line)
                lines.append("    ...")

        return "\n".join(lines)

    # ── Java parsing (regex-based) ──────────────────────────────────────

    @staticmethod
    def _parse_java(content: str, filepath: str) -> dict:
        symbols: list[dict] = []
        imports: list[str] = []

        for m in re.finditer(r"^import\s+([\w.]+);", content, re.MULTILINE):
            imports.append(m.group(1))

        for m in re.finditer(
            r"(?:public|private|protected|abstract)?\s*(?:static\s+)?(?:class|interface|enum)\s+(\w+)",
            content,
        ):
            symbols.append({"type": "class", "name": m.group(1), "line": content[:m.start()].count("\n") + 1})

        for m in re.finditer(
            r"(?:public|private|protected)\s+(?:static\s+)?(?:[\w<>\[\]]+)\s+(\w+)\s*\([^)]*\)",
            content,
        ):
            symbols.append({"type": "method", "name": m.group(1), "line": content[:m.start()].count("\n") + 1})

        return {"filepath": filepath, "language": "java", "symbols": symbols, "imports": imports}

    @staticmethod
    def _java_skeleton(content: str) -> str:
        lines: list[str] = []
        source_lines = content.split("\n")
        brace_depth = 0
        in_method = False

        for line in source_lines:
            stripped = line.strip()

            # Always include package, import, annotation, class/interface
            if stripped.startswith(("package ", "import ", "@")):
                lines.append(line)
                continue

            if re.match(r"(?:public|private|protected|abstract)?\s*(?:static\s+)?(?:class|interface|enum)\s+", stripped):
                lines.append("")
                lines.append(line)
                continue

            # Method signatures
            if re.match(r"\s*(?:public|private|protected)\s+.*\(.*\)\s*(?:throws\s+[\w,\s]+)?\s*\{?\s*$", stripped):
                lines.append(f"    {stripped.split('{')[0].strip()}" + " { ... }")
                in_method = True
                brace_depth = 0
                continue

            if in_method:
                brace_depth += stripped.count("{") - stripped.count("}")
                if brace_depth <= 0:
                    in_method = False
                continue

            # Include field declarations
            if re.match(r"\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?[\w<>\[\]]+\s+\w+", stripped):
                lines.append(line)

        return "\n".join(lines)

    # ── JS/TS parsing (regex-based) ─────────────────────────────────────

    @staticmethod
    def _parse_js_ts(content: str, filepath: str) -> dict:
        symbols: list[dict] = []
        imports: list[str] = []

        for m in re.finditer(r"(?:import\s+.*from\s+['\"])([\w./@-]+)", content):
            imports.append(m.group(1))

        for m in re.finditer(r"(?:export\s+)?class\s+(\w+)", content):
            symbols.append({"type": "class", "name": m.group(1), "line": content[:m.start()].count("\n") + 1})

        for m in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", content):
            symbols.append({"type": "function", "name": m.group(1), "line": content[:m.start()].count("\n") + 1})

        for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(", content):
            symbols.append({"type": "function", "name": m.group(1), "line": content[:m.start()].count("\n") + 1})

        return {"filepath": filepath, "language": "javascript/typescript", "symbols": symbols, "imports": imports}

    @staticmethod
    def _js_ts_skeleton(content: str) -> str:
        lines: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith(("import ", "export ", "from ")):
                lines.append(line)
            elif re.match(r"(?:export\s+)?(?:class|interface|type|enum)\s+", stripped):
                lines.append("")
                lines.append(line)
            elif re.match(r"(?:export\s+)?(?:async\s+)?function\s+", stripped):
                lines.append("")
                sig = stripped.split("{")[0].strip()
                lines.append(f"{sig} {{ ... }}")
            elif re.match(r"(?:export\s+)?(?:const|let|var)\s+\w+\s*=", stripped):
                lines.append(line.split("=")[0].strip() + " = ...")
        return "\n".join(lines)

    # ── Import resolution ───────────────────────────────────────────────

    @staticmethod
    def _extract_imports(content: str, ext: str) -> list[str]:
        imports: list[str] = []
        if ext == ".py":
            for m in re.finditer(r"^(?:from\s+([\w.]+)|import\s+([\w.]+))", content, re.MULTILINE):
                imports.append(m.group(1) or m.group(2))
        elif ext == ".java":
            for m in re.finditer(r"^import\s+([\w.]+);", content, re.MULTILINE):
                imports.append(m.group(1))
        elif ext in (".js", ".ts", ".tsx", ".jsx"):
            for m in re.finditer(r"(?:import\s+.*from\s+['\"])([\w./@-]+)", content):
                imports.append(m.group(1))
        return imports

    def _resolve_import(self, imp: str, root: Path, ext: str) -> str | None:
        """Try to resolve an import to a file path in the project."""
        if ext == ".py":
            # Convert dot notation to path
            rel_path = imp.replace(".", "/")
            for suffix in [".py", "/__init__.py"]:
                candidate = root / (rel_path + suffix)
                if candidate.exists():
                    return str(candidate.relative_to(self._workspace))
        elif ext == ".java":
            rel_path = imp.replace(".", "/") + ".java"
            # Search in src directories
            for src_dir in ["src/main/java", "src"]:
                candidate = root / src_dir / rel_path
                if candidate.exists():
                    return str(candidate.relative_to(self._workspace))
        elif ext in (".js", ".ts", ".tsx", ".jsx"):
            if imp.startswith("."):
                for suffix in ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"]:
                    candidate = root / (imp + suffix)
                    if candidate.exists():
                        return str(candidate.relative_to(self._workspace))
        return None

    def _source_files(self, root: Path) -> list[Path]:
        """Collect all source files, skipping ignored directories."""
        files: list[Path] = []
        extensions = {".py", ".java", ".js", ".ts", ".tsx", ".jsx", ".kt", ".go"}
        for path in root.rglob("*"):
            if path.suffix.lower() in extensions and path.is_file():
                skip = False
                for part in path.parts:
                    if part in _SKIP_DIRS:
                        skip = True
                        break
                if not skip:
                    files.append(path)
        return files
