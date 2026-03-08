"""Context compressor — fits codebase context into LLM token limits.

Takes the full repo map output and compresses it to fit within a target
token budget while preserving the most important structural information.
"""

from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger

logger = get_logger("context_compressor")

# Rough approximation: 1 token ≈ 4 characters for code
CHARS_PER_TOKEN = 4


class ContextCompressor:
    """Compress codebase context to fit within token limits.

    Strategy:
    1. Always include: project structure tree, tech stack, build info
    2. Include skeletons of top-ranked files (by PageRank)
    3. Include full content of directly relevant files
    4. Truncate from lowest-ranked files first
    """

    def __init__(self, max_tokens: int = 8000) -> None:
        self._max_tokens = max_tokens
        self._max_chars = max_tokens * CHARS_PER_TOKEN

    def compress(
        self,
        structure_tree: str,
        tech_stack: dict[str, Any],
        file_rankings: dict[str, float],
        skeletons: dict[str, str],
        relevant_files: list[str] | None = None,
        full_file_contents: dict[str, str] | None = None,
    ) -> str:
        """Build a compressed context string that fits within token limits.

        Parameters
        ----------
        structure_tree:
            Directory tree text.
        tech_stack:
            Detected tech stack dict.
        file_rankings:
            File → PageRank score mapping.
        skeletons:
            File → skeleton text mapping.
        relevant_files:
            Files identified as task-relevant (get full skeletons).
        full_file_contents:
            Files to include in full (e.g., config files).
        """
        sections: list[tuple[int, str]] = []  # (priority, text)

        # Priority 1: Tech stack summary (always included)
        tech_text = self._format_tech_stack(tech_stack)
        sections.append((1, tech_text))

        # Priority 2: Project structure (always included, may truncate)
        struct_text = f"## Project Structure\n```\n{structure_tree}\n```"
        sections.append((2, struct_text))

        # Priority 3: Full file contents (for config files, etc.)
        if full_file_contents:
            for fpath, content in full_file_contents.items():
                text = f"## File: {fpath}\n```\n{content}\n```"
                sections.append((3, text))

        # Priority 4: Skeletons of relevant files
        relevant = set(relevant_files or [])
        for fpath in relevant:
            if fpath in skeletons:
                text = f"## Skeleton: {fpath}\n```\n{skeletons[fpath]}\n```"
                sections.append((4, text))

        # Priority 5: Skeletons of top-ranked non-relevant files
        sorted_files = sorted(file_rankings.items(), key=lambda x: x[1], reverse=True)
        for fpath, rank in sorted_files:
            if fpath not in relevant and fpath in skeletons:
                text = f"## Skeleton: {fpath}\n```\n{skeletons[fpath]}\n```"
                sections.append((5, text))

        # Build output within budget
        return self._assemble(sections)

    def _assemble(self, sections: list[tuple[int, str]]) -> str:
        """Assemble sections into output, dropping lowest priority first."""
        # Sort by priority (lower = higher priority)
        sections.sort(key=lambda x: x[0])

        output_parts: list[str] = []
        chars_used = 0

        for priority, text in sections:
            text_len = len(text)
            if chars_used + text_len <= self._max_chars:
                output_parts.append(text)
                chars_used += text_len
            elif priority <= 2:
                # High priority — truncate rather than skip
                remaining = self._max_chars - chars_used
                if remaining > 200:
                    output_parts.append(text[:remaining] + "\n... (truncated)")
                    chars_used = self._max_chars
            # else: skip (over budget)

        result = "\n\n".join(output_parts)

        token_estimate = len(result) // CHARS_PER_TOKEN
        logger.info(f"Compressed context: ~{token_estimate} tokens ({len(result)} chars)")

        return result

    @staticmethod
    def _format_tech_stack(tech_stack: dict[str, Any]) -> str:
        """Format tech stack as readable text."""
        lines = ["## Tech Stack"]
        if tech_stack.get("languages"):
            lines.append(f"- Languages: {', '.join(tech_stack['languages'])}")
        if tech_stack.get("frameworks"):
            lines.append(f"- Frameworks: {', '.join(tech_stack['frameworks'])}")
        if tech_stack.get("build_system"):
            lines.append(f"- Build system: {tech_stack['build_system']}")
        if tech_stack.get("test_framework"):
            lines.append(f"- Test framework: {tech_stack['test_framework']}")
        versions = tech_stack.get("versions", {})
        if versions:
            lines.append("- Versions:")
            for k, v in versions.items():
                lines.append(f"  - {k}: {v}")
        return "\n".join(lines)

    def estimate_tokens(self, text: str) -> int:
        """Rough token count estimate."""
        return len(text) // CHARS_PER_TOKEN
