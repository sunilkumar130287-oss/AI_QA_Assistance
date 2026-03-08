"""Repository map builder — creates a compressed structural representation.

Pipeline: directory walk → AST parse → dependency graph → PageRank →
skeleton generation.  The output is a token-efficient map that fits
within LLM context limits while preserving structural understanding.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from core.logger import get_logger

logger = get_logger("repo_map")

_SKIP_DIRS = {
    "node_modules", ".git", "target", "build", "dist",
    "__pycache__", ".idea", ".vscode", ".gradle", ".mvn",
    "vendor", ".tox", "venv", ".venv", "env",
}

_SOURCE_EXTENSIONS = {
    ".py", ".java", ".kt", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".rb", ".cs", ".scala",
}

_CONFIG_FILES = {
    "pom.xml", "build.gradle", "build.gradle.kts",
    "package.json", "angular.json", "tsconfig.json",
    "requirements.txt", "pyproject.toml", "setup.py",
    "Cargo.toml", "go.mod", "Makefile", "Dockerfile",
    ".env", "application.yml", "application.properties",
}


@dataclass
class RepoMapResult:
    """Result of repo map building."""

    project_root: str = ""
    file_count: int = 0
    tech_stack: dict[str, Any] = field(default_factory=dict)
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)
    file_rankings: dict[str, float] = field(default_factory=dict)
    skeletons: dict[str, str] = field(default_factory=dict)
    structure_tree: str = ""


class RepoMap:
    """Build a compressed structural map of a repository.

    Usage::

        rm = RepoMap(ignore_patterns=["node_modules", ".git"])
        result = rm.build("/path/to/project")
        top_files = rm.get_relevant_files("upgrade Spring Boot", top_n=15)
    """

    def __init__(
        self,
        ignore_patterns: list[str] | None = None,
        max_files: int = 500,
        max_depth: int = 10,
    ) -> None:
        self._ignore = set(ignore_patterns or _SKIP_DIRS)
        self._max_files = max_files
        self._max_depth = max_depth
        self._result: RepoMapResult | None = None
        self._project_root: Path | None = None
        self._graph: nx.DiGraph = nx.DiGraph()

    # ── Public API ──────────────────────────────────────────────────────

    def build(self, project_root: str, ignore_patterns: list[str] | None = None) -> RepoMapResult:
        """Full pipeline: scan → parse → graph → rank → skeleton."""
        root = Path(project_root).resolve()
        self._project_root = root
        if ignore_patterns:
            self._ignore = set(ignore_patterns)

        logger.info(f"Building repo map for {root}")

        # 1. Scan directory tree
        files = self._scan_files(root)
        logger.info(f"Found {len(files)} source files")

        # 2. Detect tech stack
        tech_stack = self._detect_tech_stack(root)

        # 3. Build structure tree
        structure = self._build_structure_tree(root)

        # 4. Parse files and build dependency graph
        self._graph = nx.DiGraph()
        dep_graph: dict[str, list[str]] = {}

        for fpath in files:
            rel = str(fpath.relative_to(root))
            self._graph.add_node(rel)
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                imports = self._extract_imports(content, fpath.suffix.lower())
                dep_graph[rel] = imports
                for imp in imports:
                    resolved = self._resolve_import(imp, root, fpath.suffix.lower())
                    if resolved:
                        self._graph.add_edge(rel, resolved)
            except Exception:
                dep_graph[rel] = []

        # 5. PageRank
        rankings = self._compute_rankings()

        # 6. Generate skeletons for top files
        top_files = sorted(rankings.items(), key=lambda x: x[1], reverse=True)[:30]
        skeletons: dict[str, str] = {}
        for fpath_str, _ in top_files:
            fpath = root / fpath_str
            if fpath.is_file():
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    skeletons[fpath_str] = self._generate_skeleton(content, fpath.suffix.lower())
                except Exception:
                    skeletons[fpath_str] = "# Could not parse"

        self._result = RepoMapResult(
            project_root=str(root),
            file_count=len(files),
            tech_stack=tech_stack,
            dependency_graph=dep_graph,
            file_rankings=rankings,
            skeletons=skeletons,
            structure_tree=structure,
        )
        return self._result

    def get_relevant_files(self, query: str, top_n: int = 20) -> list[str]:
        """Given a task description, return the most relevant files.

        Combines PageRank importance with keyword relevance.
        """
        if not self._result:
            return []

        rankings = dict(self._result.file_rankings)

        # Boost files whose names or paths match query keywords
        keywords = set(re.findall(r"\w+", query.lower()))
        for fpath, score in list(rankings.items()):
            path_words = set(re.findall(r"\w+", fpath.lower()))
            overlap = len(keywords & path_words)
            if overlap > 0:
                rankings[fpath] = score * (1 + overlap * 0.5)

        sorted_files = sorted(rankings.items(), key=lambda x: x[1], reverse=True)
        return [f for f, _ in sorted_files[:top_n]]

    def get_skeleton(self, filepath: str) -> str:
        """Return signatures-only view of a file."""
        if self._result and filepath in self._result.skeletons:
            return self._result.skeletons[filepath]

        if self._project_root is None:
            return ""

        path = self._project_root / filepath
        if not path.is_file():
            return ""

        content = path.read_text(encoding="utf-8", errors="replace")
        return self._generate_skeleton(content, path.suffix.lower())

    def get_dependency_chain(self, filepath: str) -> list[str]:
        """Return all files that this file depends on (transitive)."""
        if not self._graph.has_node(filepath):
            return []
        try:
            return list(nx.descendants(self._graph, filepath))
        except nx.NetworkXError:
            return []

    # ── Internal pipeline ───────────────────────────────────────────────

    def _scan_files(self, root: Path) -> list[Path]:
        """Walk directory tree respecting ignore patterns and limits."""
        files: list[Path] = []
        for path in root.rglob("*"):
            if len(files) >= self._max_files:
                break
            if not path.is_file():
                continue
            if path.suffix.lower() not in _SOURCE_EXTENSIONS:
                continue
            # Check ignore patterns
            skip = False
            for part in path.relative_to(root).parts:
                if part in self._ignore:
                    skip = True
                    break
            if not skip:
                # Check depth
                depth = len(path.relative_to(root).parts)
                if depth <= self._max_depth:
                    files.append(path)
        return files

    @staticmethod
    def _detect_tech_stack(root: Path) -> dict[str, Any]:
        """Detect languages, frameworks, build system, and versions."""
        stack: dict[str, Any] = {
            "languages": [],
            "frameworks": [],
            "build_system": "",
            "test_framework": "",
            "versions": {},
        }

        # Check for build/config files
        if (root / "pom.xml").exists():
            stack["build_system"] = "maven"
            stack["languages"].append("java")
            # Try to extract Spring Boot version
            try:
                pom = (root / "pom.xml").read_text(encoding="utf-8")
                sb_match = re.search(r"<version>(\d+\.\d+\.\d+[^<]*)</version>", pom)
                if "spring-boot" in pom:
                    stack["frameworks"].append("spring-boot")
                    parent_ver = re.search(
                        r"spring-boot-starter-parent.*?<version>([^<]+)</version>",
                        pom, re.DOTALL,
                    )
                    if parent_ver:
                        stack["versions"]["spring-boot"] = parent_ver.group(1)
                java_ver = re.search(r"<java\.version>(\d+)</java\.version>", pom)
                if java_ver:
                    stack["versions"]["java"] = java_ver.group(1)
            except Exception:
                pass

        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            stack["build_system"] = "gradle"
            stack["languages"].append("java")

        if (root / "package.json").exists():
            stack["build_system"] = stack["build_system"] or "npm"
            try:
                import json
                pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "@angular/core" in deps:
                    stack["frameworks"].append("angular")
                    stack["versions"]["angular"] = deps["@angular/core"].lstrip("^~")
                    stack["languages"].append("typescript")
                if "react" in deps:
                    stack["frameworks"].append("react")
                    stack["versions"]["react"] = deps["react"].lstrip("^~")
                if "typescript" in deps:
                    stack["languages"].append("typescript")
                else:
                    stack["languages"].append("javascript")
                if "jest" in deps:
                    stack["test_framework"] = "jest"
                if "karma" in deps or "karma-jasmine" in deps:
                    stack["test_framework"] = "karma"
            except Exception:
                stack["languages"].append("javascript")

        if (root / "angular.json").exists():
            if "angular" not in stack["frameworks"]:
                stack["frameworks"].append("angular")
            stack["build_system"] = stack["build_system"] or "angular-cli"

        if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
            stack["languages"].append("python")
            if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
                stack["test_framework"] = stack["test_framework"] or "pytest"

        # Deduplicate
        stack["languages"] = list(dict.fromkeys(stack["languages"]))
        stack["frameworks"] = list(dict.fromkeys(stack["frameworks"]))

        return stack

    def _build_structure_tree(self, root: Path, max_depth: int = 3) -> str:
        """Build a text representation of the project directory tree."""
        lines: list[str] = [root.name + "/"]
        self._tree_walk(root, root, lines, prefix="", depth=0, max_depth=max_depth)
        return "\n".join(lines[:200])  # limit output

    def _tree_walk(
        self, current: Path, root: Path, lines: list[str],
        prefix: str, depth: int, max_depth: int,
    ) -> None:
        if depth >= max_depth or len(lines) >= 200:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        # Filter
        entries = [
            e for e in entries
            if e.name not in self._ignore and not e.name.startswith(".")
        ]

        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                ext_prefix = prefix + ("    " if is_last else "│   ")
                self._tree_walk(entry, root, lines, ext_prefix, depth + 1, max_depth)
            else:
                lines.append(f"{prefix}{connector}{entry.name}")

    def _compute_rankings(self) -> dict[str, float]:
        """PageRank on the dependency graph."""
        if self._graph.number_of_nodes() == 0:
            return {}
        try:
            return nx.pagerank(self._graph)
        except nx.NetworkXError:
            # Fallback: uniform ranking
            n = self._graph.number_of_nodes()
            return {node: 1.0 / n for node in self._graph.nodes()}

    # ── Shared helpers ──────────────────────────────────────────────────

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
            for m in re.finditer(r"from\s+['\"]([^'\"]+)['\"]", content):
                imports.append(m.group(1))
        return imports

    def _resolve_import(self, imp: str, root: Path, ext: str) -> str | None:
        if ext == ".py":
            rel = imp.replace(".", "/")
            for suffix in [".py", "/__init__.py"]:
                candidate = root / (rel + suffix)
                if candidate.exists():
                    return str(candidate.relative_to(root))
        elif ext == ".java":
            rel = imp.replace(".", "/") + ".java"
            for src_dir in ["src/main/java", "src"]:
                candidate = root / src_dir / rel
                if candidate.exists():
                    return str(candidate.relative_to(root))
        elif ext in (".js", ".ts", ".tsx", ".jsx"):
            if imp.startswith("."):
                for suffix in ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"]:
                    candidate = root / (imp.lstrip("./") + suffix)
                    if candidate.exists():
                        return str(candidate.relative_to(root))
        return None

    @staticmethod
    def _generate_skeleton(content: str, ext: str) -> str:
        """Generate a signatures-only skeleton for a source file."""
        if ext == ".py":
            return RepoMap._python_skeleton(content)
        elif ext == ".java":
            return RepoMap._java_skeleton(content)
        elif ext in (".js", ".ts", ".tsx", ".jsx"):
            return RepoMap._js_skeleton(content)
        return content[:500]

    @staticmethod
    def _python_skeleton(content: str) -> str:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return "# Syntax error — could not parse"

        lines: list[str] = []
        source = content.split("\n")
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if node.lineno <= len(source):
                    lines.append(source[node.lineno - 1])
            elif isinstance(node, ast.ClassDef):
                lines.append("")
                if node.lineno <= len(source):
                    lines.append(source[node.lineno - 1])
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.lineno <= len(source):
                            lines.append(f"    {source[item.lineno - 1].strip()}")
                            lines.append("        ...")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines.append("")
                if node.lineno <= len(source):
                    lines.append(source[node.lineno - 1])
                    lines.append("    ...")
        return "\n".join(lines)

    @staticmethod
    def _java_skeleton(content: str) -> str:
        lines: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith(("package ", "import ", "@")):
                lines.append(line)
            elif re.match(r"(?:public|private|protected|abstract)?\s*(?:static\s+)?(?:class|interface|enum)\s+", stripped):
                lines.append("")
                lines.append(line)
            elif re.match(r"\s*(?:public|private|protected)\s+.*\(.*\)", stripped):
                sig = stripped.split("{")[0].strip()
                lines.append(f"    {sig} {{ ... }}")
        return "\n".join(lines)

    @staticmethod
    def _js_skeleton(content: str) -> str:
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
                lines.append(stripped.split("{")[0].strip() + " { ... }")
        return "\n".join(lines)
