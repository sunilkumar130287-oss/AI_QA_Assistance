"""Skeleton generator — produces signature-only views of source files.

Used by the perception pipeline to create token-efficient representations
of code that preserve structural information without method bodies.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


class SkeletonGenerator:
    """Generate signature-only code skeletons for multiple languages."""

    def generate(self, filepath: str, content: str | None = None) -> str:
        """Generate skeleton for a file.

        Parameters
        ----------
        filepath:
            Path to the file (used for language detection).
        content:
            File content.  If None, reads from disk.
        """
        path = Path(filepath)
        if content is None:
            if not path.is_file():
                return ""
            content = path.read_text(encoding="utf-8", errors="replace")

        ext = path.suffix.lower()
        generators = {
            ".py": self._python,
            ".java": self._java,
            ".kt": self._kotlin,
            ".js": self._javascript,
            ".ts": self._typescript,
            ".tsx": self._typescript,
            ".jsx": self._javascript,
        }
        gen = generators.get(ext)
        if gen is None:
            # Return first N lines as fallback
            return "\n".join(content.split("\n")[:30])
        return gen(content)

    # ── Language-specific generators ────────────────────────────────────

    @staticmethod
    def _python(content: str) -> str:
        """Python skeleton using the ``ast`` module."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return "# Could not parse"

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
                # Class docstring
                if (node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    doc = node.body[0].value.value
                    first_line = doc.strip().split("\n")[0][:100]
                    lines.append(f'    """{first_line}"""')

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

            elif isinstance(node, ast.Assign):
                # Module-level constants
                if node.lineno <= len(source):
                    line = source[node.lineno - 1].strip()
                    if line and line[0].isupper():
                        lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def _java(content: str) -> str:
        """Java skeleton — package, imports, class/method signatures."""
        lines: list[str] = []
        in_method_body = False
        brace_depth = 0

        for line in content.split("\n"):
            stripped = line.strip()

            # Always include these
            if stripped.startswith(("package ", "import ")):
                lines.append(line)
                continue

            if stripped.startswith("@"):
                lines.append(line)
                continue

            # Class/interface/enum declaration
            if re.match(
                r"(?:public|private|protected|abstract|final)?\s*"
                r"(?:static\s+)?(?:class|interface|enum)\s+",
                stripped,
            ):
                lines.append("")
                lines.append(line)
                in_method_body = False
                continue

            # Method signature
            if not in_method_body and re.match(
                r"\s*(?:public|private|protected)\s+(?:static\s+)?(?:abstract\s+)?"
                r"(?:synchronized\s+)?[\w<>\[\],\s]+\s+\w+\s*\(",
                stripped,
            ):
                sig = stripped.split("{")[0].strip()
                lines.append(f"    {sig} {{ ... }}")
                if "{" in stripped:
                    in_method_body = True
                    brace_depth = stripped.count("{") - stripped.count("}")
                continue

            # Field declaration
            if not in_method_body and re.match(
                r"\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?[\w<>\[\]]+\s+\w+",
                stripped,
            ):
                lines.append(line)
                continue

            if in_method_body:
                brace_depth += stripped.count("{") - stripped.count("}")
                if brace_depth <= 0:
                    in_method_body = False

        return "\n".join(lines)

    @staticmethod
    def _kotlin(content: str) -> str:
        """Kotlin skeleton."""
        lines: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith(("package ", "import ")):
                lines.append(line)
            elif re.match(r"(?:class|interface|object|enum|data\s+class|sealed\s+class)\s+", stripped):
                lines.append("")
                lines.append(line)
            elif re.match(r"(?:fun|suspend\s+fun|override\s+fun)\s+", stripped):
                sig = stripped.split("{")[0].strip()
                lines.append(f"    {sig} {{ ... }}")
            elif re.match(r"(?:val|var)\s+\w+", stripped):
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _javascript(content: str) -> str:
        """JavaScript skeleton."""
        lines: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith(("import ", "export ", "const ", "let ", "var ")):
                if "=>" in stripped or "function" in stripped:
                    sig = stripped.split("{")[0].split("=>")[0].strip()
                    lines.append(f"{sig} => {{ ... }}")
                elif "=" in stripped:
                    lines.append(stripped.split("=")[0].strip() + " = ...")
                else:
                    lines.append(line)
            elif re.match(r"(?:export\s+)?(?:async\s+)?function\s+", stripped):
                lines.append("")
                sig = stripped.split("{")[0].strip()
                lines.append(f"{sig} {{ ... }}")
            elif re.match(r"(?:export\s+)?class\s+", stripped):
                lines.append("")
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _typescript(content: str) -> str:
        """TypeScript skeleton — includes type declarations."""
        lines: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith(("import ", "export ", "from ")):
                lines.append(line)
            elif re.match(r"(?:export\s+)?(?:interface|type|enum)\s+", stripped):
                lines.append("")
                lines.append(line)
            elif re.match(r"(?:export\s+)?(?:class|abstract\s+class)\s+", stripped):
                lines.append("")
                lines.append(line)
            elif re.match(r"(?:export\s+)?(?:async\s+)?function\s+", stripped):
                lines.append("")
                sig = stripped.split("{")[0].strip()
                lines.append(f"{sig} {{ ... }}")
            elif re.match(r"(?:export\s+)?(?:const|let)\s+\w+", stripped):
                if "=" in stripped:
                    lines.append(stripped.split("=")[0].strip() + " = ...")
                else:
                    lines.append(line)
        return "\n".join(lines)
