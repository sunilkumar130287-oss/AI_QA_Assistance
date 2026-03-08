"""Test runner tool — runs and parses tests for JUnit/pytest/Karma.

Supports running full suites or individual tests, and parses JUnit XML
reports for structured results.
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from core.logger import get_logger
from tools.base_tool import BaseTool, ToolResult

logger = get_logger("test_tool")


class TestTool(BaseTool):
    """Run tests and parse results across multiple frameworks."""

    def __init__(self, workspace: str, build_system: str = "", timeout: int = 300) -> None:
        self._workspace = Path(workspace).resolve()
        self._build_system = build_system
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "test_tool"

    @property
    def description(self) -> str:
        return (
            "Run tests: run_tests, run_single_test, parse_results. "
            "Supports JUnit/Maven, pytest, Karma/Jasmine."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "run_tests")
        dispatch = {
            "run_tests": self._run_tests,
            "run_single_test": self._run_single_test,
            "parse_results": self._parse_results,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        try:
            return handler(**kwargs)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"Tests timed out after {self._timeout}s")
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Test error: {exc}")

    # ── Detection ───────────────────────────────────────────────────────

    def _detect_framework(self) -> str:
        """Auto-detect test framework from project files."""
        if self._build_system:
            return self._build_system
        if (self._workspace / "pom.xml").exists():
            return "maven"
        if (self._workspace / "build.gradle").exists() or (self._workspace / "build.gradle.kts").exists():
            return "gradle"
        if (self._workspace / "pytest.ini").exists() or (self._workspace / "pyproject.toml").exists():
            return "pytest"
        if (self._workspace / "karma.conf.js").exists():
            return "karma"
        if (self._workspace / "package.json").exists():
            return "npm"
        return "pytest"  # fallback

    # ── Actions ─────────────────────────────────────────────────────────

    def _run_tests(self, **kwargs: Any) -> ToolResult:
        test_path: str | None = kwargs.get("test_path")
        framework = self._detect_framework()

        cmd: list[str]
        match framework:
            case "maven":
                cmd = ["mvn", "test"]
                if test_path:
                    cmd += [f"-Dtest={test_path}"]
            case "gradle":
                cmd = ["gradle", "test"]
                if test_path:
                    cmd += ["--tests", test_path]
            case "pytest":
                cmd = ["python", "-m", "pytest", "-v", "--tb=short", "--junitxml=test-results.xml"]
                if test_path:
                    cmd.append(test_path)
            case "karma":
                cmd = ["npx", "karma", "start", "--single-run", "--browsers=ChromeHeadless"]
            case "npm":
                cmd = ["npm", "test", "--", "--watchAll=false"]
                if test_path:
                    cmd += ["--testPathPattern", test_path]
            case _:
                return ToolResult(success=False, output="", error=f"Unknown test framework: {framework}")

        return self._execute_tests(cmd, framework)

    def _run_single_test(self, **kwargs: Any) -> ToolResult:
        test_class: str = kwargs.get("test_class", "")
        test_method: str = kwargs.get("test_method", "")
        framework = self._detect_framework()

        if not test_class and not test_method:
            return ToolResult(success=False, output="", error="Must specify test_class or test_method")

        cmd: list[str]
        match framework:
            case "maven":
                test_spec = f"{test_class}#{test_method}" if test_method else test_class
                cmd = ["mvn", "test", f"-Dtest={test_spec}"]
            case "gradle":
                test_spec = f"{test_class}.{test_method}" if test_method else test_class
                cmd = ["gradle", "test", "--tests", test_spec]
            case "pytest":
                test_spec = f"{test_class}::{test_method}" if test_method else test_class
                cmd = ["python", "-m", "pytest", "-v", "--tb=long", test_spec]
            case _:
                return ToolResult(success=False, output="", error=f"Single test not supported for: {framework}")

        return self._execute_tests(cmd, framework)

    def _parse_results(self, **kwargs: Any) -> ToolResult:
        """Parse JUnit XML test report (standard format across frameworks)."""
        report_path = kwargs.get("report_path", "")
        if not report_path:
            # Search for common report locations
            candidates = [
                "target/surefire-reports",
                "build/test-results/test",
                "test-results.xml",
            ]
            for c in candidates:
                p = self._workspace / c
                if p.exists():
                    report_path = str(p)
                    break

        if not report_path:
            return ToolResult(success=False, output="", error="No test report found")

        path = Path(report_path)
        if path.is_dir():
            # Parse all XML files in the directory
            xml_files = list(path.glob("*.xml"))
        elif path.is_file():
            xml_files = [path]
        else:
            return ToolResult(success=False, output="", error=f"Report path not found: {report_path}")

        return self._parse_junit_xml(xml_files)

    # ── Execution ───────────────────────────────────────────────────────

    def _execute_tests(self, cmd: list[str], framework: str) -> ToolResult:
        """Run test command and parse output."""
        logger.info(f"Running tests: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=str(self._workspace),
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )

        combined = result.stdout + "\n" + result.stderr
        success = result.returncode == 0

        # Parse structured results from output
        summary = self._parse_output_summary(combined, framework)

        # Try to parse JUnit XML if available
        xml_results = None
        if framework == "maven":
            report_dir = self._workspace / "target" / "surefire-reports"
            if report_dir.exists():
                xml_files = list(report_dir.glob("TEST-*.xml"))
                if xml_files:
                    xml_result = self._parse_junit_xml(xml_files)
                    xml_results = xml_result.metadata

        # Truncate output
        truncated = combined[-5000:] if len(combined) > 5000 else combined

        metadata = {
            "success": success,
            "return_code": result.returncode,
            "framework": framework,
            "summary": summary,
        }
        if xml_results:
            metadata["xml_results"] = xml_results

        status_text = "PASSED" if success else "FAILED"
        summary_text = (
            f"Tests: {summary.get('passed', '?')} passed, "
            f"{summary.get('failed', '?')} failed, "
            f"{summary.get('errors', '?')} errors, "
            f"{summary.get('skipped', '?')} skipped"
        )

        return ToolResult(
            success=success,
            output=f"TEST {status_text} — {summary_text}\n\n{truncated}",
            error="" if success else f"Test failures detected. {summary_text}",
            metadata=metadata,
        )

    # ── Parsing ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_output_summary(output: str, framework: str) -> dict:
        """Extract test counts from console output."""
        summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}

        if framework in ("maven", "gradle"):
            # Maven Surefire: Tests run: 5, Failures: 1, Errors: 0, Skipped: 2
            match = re.search(
                r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
                output,
            )
            if match:
                total, failed, errors, skipped = (int(x) for x in match.groups())
                summary = {
                    "passed": total - failed - errors - skipped,
                    "failed": failed,
                    "errors": errors,
                    "skipped": skipped,
                }

        elif framework == "pytest":
            # pytest: 5 passed, 2 failed, 1 error
            match = re.search(r"(\d+) passed", output)
            if match:
                summary["passed"] = int(match.group(1))
            match = re.search(r"(\d+) failed", output)
            if match:
                summary["failed"] = int(match.group(1))
            match = re.search(r"(\d+) error", output)
            if match:
                summary["errors"] = int(match.group(1))
            match = re.search(r"(\d+) skipped", output)
            if match:
                summary["skipped"] = int(match.group(1))

        elif framework in ("npm", "karma"):
            # Jest / Karma patterns
            match = re.search(r"Tests:\s*(\d+)\s*passed", output)
            if match:
                summary["passed"] = int(match.group(1))
            match = re.search(r"Tests:\s*(\d+)\s*failed", output)
            if match:
                summary["failed"] = int(match.group(1))

        return summary

    @staticmethod
    def _parse_junit_xml(xml_files: list[Path]) -> ToolResult:
        """Parse JUnit XML reports into structured results."""
        total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        failure_details: list[dict] = []

        for xml_file in xml_files:
            try:
                tree = ET.parse(str(xml_file))
                root = tree.getroot()

                # Handle both <testsuite> and <testsuites> roots
                suites = root.findall(".//testsuite") if root.tag == "testsuites" else [root]
                for suite in suites:
                    total["tests"] += int(suite.get("tests", 0))
                    total["failures"] += int(suite.get("failures", 0))
                    total["errors"] += int(suite.get("errors", 0))
                    total["skipped"] += int(suite.get("skipped", 0))

                    for tc in suite.findall("testcase"):
                        failure = tc.find("failure")
                        error = tc.find("error")
                        elem = failure if failure is not None else error
                        if elem is not None:
                            failure_details.append({
                                "class": tc.get("classname", ""),
                                "method": tc.get("name", ""),
                                "type": elem.get("type", ""),
                                "message": (elem.get("message", "") or "")[:300],
                                "stacktrace": (elem.text or "")[:500],
                            })
            except ET.ParseError:
                logger.warning(f"Failed to parse XML: {xml_file}")

        passed = total["tests"] - total["failures"] - total["errors"] - total["skipped"]
        total["passed"] = max(passed, 0)

        output_lines = [
            f"Tests: {total['tests']} | Passed: {total['passed']} | "
            f"Failed: {total['failures']} | Errors: {total['errors']} | Skipped: {total['skipped']}"
        ]
        for fd in failure_details[:10]:
            output_lines.append(f"\n  FAIL: {fd['class']}.{fd['method']}")
            output_lines.append(f"    {fd['message']}")

        success = total["failures"] == 0 and total["errors"] == 0
        return ToolResult(
            success=success,
            output="\n".join(output_lines),
            metadata={"totals": total, "failure_details": failure_details},
        )
