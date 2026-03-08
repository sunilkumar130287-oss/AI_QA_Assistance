"""Build execution tool — auto-detects and runs Maven, Gradle, npm, or Angular CLI.

Parses build output for success/failure, compilation errors with file:line locations,
and warnings.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from core.logger import get_logger
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("build_tool")


class BuildTool(BaseTool):
    """Runs builds and parses output for the detected build system."""

    def __init__(self, workspace: str, timeout: int = 300) -> None:
        self._workspace = Path(workspace).resolve()
        self._timeout = timeout
        self._build_system: str | None = None

    @property
    def name(self) -> str:
        return "build_tool"

    @property
    def description(self) -> str:
        return (
            "Run builds: compile, test, package. Auto-detects Maven/Gradle/npm/Angular. "
            "Actions: detect, compile, test, package, custom."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "compile")
        dispatch = {
            "detect": self._detect,
            "compile": self._compile,
            "test": self._test,
            "package": self._package,
            "custom": self._custom,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        try:
            return handler(**kwargs)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"Build timed out after {self._timeout}s")
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Build error: {exc}")

    # ── Detection ───────────────────────────────────────────────────────

    def detect_build_system(self) -> str:
        """Auto-detect the build system from project files."""
        if self._build_system:
            return self._build_system

        checks = [
            ("pom.xml", "maven"),
            ("build.gradle", "gradle"),
            ("build.gradle.kts", "gradle"),
            ("angular.json", "angular"),
            ("package.json", "npm"),
        ]
        for filename, system in checks:
            if (self._workspace / filename).exists():
                self._build_system = system
                return system

        self._build_system = "unknown"
        return "unknown"

    def _detect(self, **kwargs: Any) -> ToolResult:
        system = self.detect_build_system()
        return ToolResult(
            success=True, output=f"Detected build system: {system}",
            metadata={"build_system": system},
        )

    # ── Build commands ──────────────────────────────────────────────────

    def _compile(self, **kwargs: Any) -> ToolResult:
        system = self.detect_build_system()
        commands = {
            "maven": ["mvn", "compile", "-q"],
            "gradle": ["gradle", "compileJava", "-q"],
            "npm": ["npm", "run", "build"],
            "angular": ["npx", "ng", "build"],
        }
        cmd = commands.get(system)
        if cmd is None:
            return ToolResult(success=False, output="", error=f"Cannot compile: unknown build system '{system}'")
        return self._run_build(cmd, system)

    def _test(self, **kwargs: Any) -> ToolResult:
        system = self.detect_build_system()
        commands = {
            "maven": ["mvn", "test"],
            "gradle": ["gradle", "test"],
            "npm": ["npm", "test", "--", "--watchAll=false"],
            "angular": ["npx", "ng", "test", "--watch=false", "--browsers=ChromeHeadless"],
        }
        cmd = commands.get(system)
        if cmd is None:
            return ToolResult(success=False, output="", error=f"Cannot test: unknown build system '{system}'")
        return self._run_build(cmd, system)

    def _package(self, **kwargs: Any) -> ToolResult:
        system = self.detect_build_system()
        commands = {
            "maven": ["mvn", "package", "-DskipTests"],
            "gradle": ["gradle", "build", "-x", "test"],
            "npm": ["npm", "run", "build"],
            "angular": ["npx", "ng", "build", "--configuration=production"],
        }
        cmd = commands.get(system)
        if cmd is None:
            return ToolResult(success=False, output="", error=f"Cannot package: unknown build system '{system}'")
        return self._run_build(cmd, system)

    def _custom(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs.get("command", "")
        if not command:
            return ToolResult(success=False, output="", error="No command specified")
        # Safety: block dangerous commands
        dangerous = ["rm ", "del ", "format ", "mkfs", "dd "]
        for d in dangerous:
            if d in command.lower():
                return ToolResult(success=False, output="", error=f"Blocked dangerous command: {command}")
        return self._run_build(command.split(), self.detect_build_system())

    # ── Execution ───────────────────────────────────────────────────────

    def _run_build(self, cmd: list[str], system: str) -> ToolResult:
        """Execute build command and parse output."""
        logger.info(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=str(self._workspace),
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )

        combined = result.stdout + "\n" + result.stderr
        success = result.returncode == 0

        # Also check for known failure markers
        if system == "maven" and "BUILD FAILURE" in combined:
            success = False
        if system == "gradle" and "BUILD FAILED" in combined:
            success = False

        # Parse errors and warnings
        errors = self._extract_errors(combined, system)
        warnings = self._extract_warnings(combined, system)

        # Truncate output to keep it manageable
        truncated = combined[-5000:] if len(combined) > 5000 else combined

        metadata = {
            "success": success,
            "return_code": result.returncode,
            "errors": errors,
            "warnings": warnings,
            "build_system": system,
        }

        if success:
            return ToolResult(success=True, output=f"BUILD SUCCESS\n{truncated}", metadata=metadata)
        else:
            error_summary = "\n".join(f"  - {e}" for e in errors[:10])
            return ToolResult(
                success=False,
                output=truncated,
                error=f"BUILD FAILED ({len(errors)} error(s)):\n{error_summary}",
                metadata=metadata,
            )

    # ── Output parsing ──────────────────────────────────────────────────

    @staticmethod
    def _extract_errors(output: str, system: str) -> list[str]:
        """Extract compilation/build errors with file:line info."""
        errors: list[str] = []
        patterns = {
            "maven": [
                r"\[ERROR\]\s+(.+\.java):\[(\d+),\d+\]\s+(.+)",
                r"\[ERROR\]\s+(.+)",
            ],
            "gradle": [
                r"e:\s+(.+\.java):(\d+):\s+(.+)",
                r"FAILURE:\s+(.+)",
            ],
            "npm": [
                r"ERROR in (.+)\((\d+),\d+\):\s+(.+)",
                r"error TS\d+:\s+(.+)",
            ],
            "angular": [
                r"ERROR in (.+)\((\d+),\d+\):\s+(.+)",
                r"Error:\s+(.+)",
            ],
        }
        for pattern in patterns.get(system, [r"(?i)error[:\s]+(.+)"]):
            for match in re.finditer(pattern, output):
                errors.append(match.group(0).strip()[:200])
        return errors[:20]

    @staticmethod
    def _extract_warnings(output: str, system: str) -> list[str]:
        """Extract build warnings."""
        warnings: list[str] = []
        pattern = r"(?i)\[?warn(?:ing)?\]?\s*:?\s*(.+)"
        for match in re.finditer(pattern, output):
            warnings.append(match.group(0).strip()[:200])
        return warnings[:10]
