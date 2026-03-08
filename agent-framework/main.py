"""CLI entry point for the agent framework.

Usage:
    python main.py --jira PROJ-1234 --repo https://git.company.com/team/service.git --branch main --task spring_boot_upgrade
    python main.py --jira PROJ-5678 --repo https://git.company.com/team/service.git --branch main --task story_implementation
    python main.py --jira PROJ-9999 --repo https://git.company.com/team/service.git --branch main --task write_tests
    python main.py --config custom-config.yaml --jira PROJ-1234 ...
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.logger import setup_logging
from core.orchestrator import Orchestrator

console = Console()


def load_config(config_path: str) -> dict:
    """Load YAML config with environment variable interpolation.

    Replaces ``${VAR_NAME}`` with the corresponding environment variable.
    """
    path = Path(config_path)
    if not path.is_file():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        sys.exit(1)

    content = path.read_text(encoding="utf-8")

    # Interpolate ${ENV_VAR} patterns
    def _replace_env(match: re.Match) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name, "")
        if not value:
            console.print(f"[yellow]Warning: environment variable {var_name} is not set[/yellow]")
        return value

    interpolated = re.sub(r"\$\{(\w+)\}", _replace_env, content)
    return yaml.safe_load(interpolated)


def print_summary(state) -> None:
    """Print a rich summary table of the pipeline result."""
    summary = state.summary()

    status = "[green]PASSED[/green]" if state.review_passed else "[red]FAILED[/red]"

    table = Table(title="Pipeline Result", show_header=False, border_style="blue")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Correlation ID", summary["correlation_id"])
    table.add_row("Jira", summary["jira_id"])
    table.add_row("Task Type", summary["task_type"])
    table.add_row("Review", status)
    table.add_row("PR URL", state.pr_url or "N/A")
    table.add_row("Files Modified", str(summary["files_modified"]))
    table.add_row("Files Created", str(summary["files_created"]))
    table.add_row("Tests Created", str(summary["test_files_created"]))
    table.add_row("LLM Calls", str(summary["total_llm_calls"]))
    table.add_row("Tokens Used", f"{summary['total_tokens_used']:,}")
    table.add_row("Duration", f"{summary['elapsed_seconds']}s")
    table.add_row("Errors", str(summary["errors"]))

    console.print()
    console.print(table)

    if state.errors:
        console.print()
        console.print("[red]Errors encountered:[/red]")
        for err in state.errors:
            console.print(f"  [{err['agent']}] {err['error']}")

    if state.review_comments:
        console.print()
        console.print("[yellow]Review comments:[/yellow]")
        for comment in state.review_comments:
            console.print(f"  - {comment}")


def main() -> None:
    """Parse arguments, load config, run pipeline."""
    parser = argparse.ArgumentParser(
        description="Autonomous AI Coding Agent Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --jira PROJ-1234 --repo https://git.company.com/team/service.git --branch main --task spring_boot_upgrade
  python main.py --jira PROJ-5678 --repo https://git.company.com/team/service.git --branch main --task story_implementation
  python main.py --jira PROJ-9999 --repo https://git.company.com/team/service.git --branch main --task write_tests
        """,
    )
    parser.add_argument("--jira", required=True, help="Jira story ID (e.g., PROJ-1234)")
    parser.add_argument("--repo", required=True, help="Git repository URL")
    parser.add_argument("--branch", required=True, help="Git branch name")
    parser.add_argument("--task", required=True, help="Task type / skill name (e.g., spring_boot_upgrade)")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML (default: config.yaml)")
    parser.add_argument("--env", default=".env", help="Path to .env file (default: .env)")

    args = parser.parse_args()

    # Load environment variables
    env_path = Path(args.env)
    if env_path.is_file():
        load_dotenv(str(env_path))
    else:
        console.print(f"[yellow]No .env file at {args.env} — using system environment[/yellow]")

    # Load config
    config = load_config(args.config)

    # Setup logging
    setup_logging(config.get("logging", {}))

    # Banner
    console.print(Panel.fit(
        "[bold blue]Autonomous AI Coding Agent Framework[/bold blue]\n"
        f"Jira: {args.jira} | Task: {args.task} | Branch: {args.branch}",
        border_style="blue",
    ))
    console.print()

    # Run
    orchestrator = Orchestrator(config)
    state = orchestrator.run({
        "jira_id": args.jira,
        "repo_url": args.repo,
        "branch": args.branch,
        "task_type": args.task,
    })

    # Print results
    print_summary(state)

    # Exit code
    sys.exit(0 if state.review_passed else 1)


if __name__ == "__main__":
    main()
