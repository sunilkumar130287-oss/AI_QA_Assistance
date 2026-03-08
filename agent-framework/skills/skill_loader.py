"""YAML skill parser and validator.

Skills are data files (YAML) that define step-by-step playbooks for
specific task types.  Adding a new capability means writing a new YAML
file — no Python code changes required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.exceptions import SkillNotFoundError
from core.logger import get_logger

logger = get_logger("skill_loader")

_REQUIRED_FIELDS = {"name", "description", "steps"}


@dataclass
class Skill:
    """Parsed representation of a YAML skill file."""

    name: str
    description: str
    steps: list[dict[str, Any]]
    applicable_when: dict[str, Any] = field(default_factory=dict)
    context: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class SkillLoader:
    """Load and validate YAML skill files from a directory.

    Usage::

        loader = SkillLoader("./skills")
        skill = loader.get("spring_boot_upgrade")
        print(skill.steps)
    """

    def __init__(self, skills_dir: str = "./skills") -> None:
        self._dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Scan the skills directory and load all YAML files."""
        if not self._dir.is_dir():
            logger.warning(f"Skills directory not found: {self._dir}")
            return

        for path in self._dir.glob("*.yaml"):
            try:
                skill = self._parse_file(path)
                self._skills[skill.name] = skill
                logger.info(f"Loaded skill: {skill.name} ({path.name})")
            except Exception as exc:
                logger.warning(f"Failed to load skill {path.name}: {exc}")

        for path in self._dir.glob("*.yml"):
            try:
                skill = self._parse_file(path)
                if skill.name not in self._skills:
                    self._skills[skill.name] = skill
                    logger.info(f"Loaded skill: {skill.name} ({path.name})")
            except Exception as exc:
                logger.warning(f"Failed to load skill {path.name}: {exc}")

    def get(self, name: str) -> Skill:
        """Retrieve a skill by name.

        Raises
        ------
        SkillNotFoundError
            If the requested skill does not exist.
        """
        skill = self._skills.get(name)
        if skill is None:
            available = list(self._skills.keys())
            raise SkillNotFoundError(
                f"Skill '{name}' not found. Available: {available}"
            )
        return skill

    def list_skills(self) -> list[str]:
        """Return all loaded skill names."""
        return list(self._skills.keys())

    def find_skill_for_task(self, story_type: str, tech_stack: dict) -> Skill | None:
        """Find the best matching skill for a given story type and tech stack."""
        for skill in self._skills.values():
            conditions = skill.applicable_when
            if not conditions:
                continue

            # Check story_type match
            required_type = conditions.get("story_type")
            if required_type:
                if isinstance(required_type, list):
                    if story_type not in required_type:
                        continue
                elif story_type != required_type:
                    continue

            # Check tech_stack match
            required_tech = conditions.get("tech_stack_contains")
            if required_tech:
                frameworks = tech_stack.get("frameworks", [])
                languages = tech_stack.get("languages", [])
                all_tech = [t.lower() for t in frameworks + languages]
                if required_tech.lower() not in all_tech:
                    continue

            return skill

        return None

    def reload(self) -> None:
        """Reload all skills from disk."""
        self._skills.clear()
        self._load_all()

    @staticmethod
    def _parse_file(path: Path) -> Skill:
        """Parse and validate a single YAML skill file."""
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        if not isinstance(data, dict):
            raise ValueError(f"Skill file must be a YAML mapping: {path}")

        missing = _REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise ValueError(f"Skill file missing fields {missing}: {path}")

        steps = data["steps"]
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"Skill must have at least one step: {path}")

        # Validate each step
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"Step {i} is not a mapping: {path}")
            if "name" not in step:
                raise ValueError(f"Step {i} missing 'name': {path}")

        return Skill(
            name=data["name"],
            description=data["description"],
            steps=steps,
            applicable_when=data.get("applicable_when", {}),
            context=data.get("context", ""),
            raw=data,
        )
