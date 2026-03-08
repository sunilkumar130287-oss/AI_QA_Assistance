"""Tests for perception module — repo_map, skeleton_generator, context_compressor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from perception.context_compressor import ContextCompressor
from perception.repo_map import RepoMap
from perception.skeleton_generator import SkeletonGenerator


# ── RepoMap Tests ───────────────────────────────────────────────────────


class TestRepoMap:
    """Test RepoMap build and query methods."""

    @pytest.fixture
    def project(self, tmp_path):
        """Create a minimal project structure."""
        # Python files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text(
            "from src.utils import helper\n\n"
            "class App:\n    def run(self):\n        helper()\n"
        )
        (tmp_path / "src" / "utils.py").write_text(
            "def helper():\n    return 42\n\n"
            "def format_output(data):\n    return str(data)\n"
        )
        (tmp_path / "src" / "__init__.py").write_text("")

        # Config files
        (tmp_path / "requirements.txt").write_text("requests\npyyaml\n")
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")

        return tmp_path

    def test_build_repo_map(self, project):
        rm = RepoMap(max_files=100)
        result = rm.build(str(project))

        assert result.file_count >= 2
        assert result.structure_tree != ""
        assert len(result.tech_stack) > 0

    def test_tech_stack_detection(self, project):
        rm = RepoMap()
        result = rm.build(str(project))

        assert "python" in result.tech_stack.get("languages", [])

    def test_get_relevant_files(self, project):
        rm = RepoMap()
        rm.build(str(project))

        files = rm.get_relevant_files("helper function", top_n=5)
        assert isinstance(files, list)

    def test_get_skeleton(self, project):
        rm = RepoMap()
        rm.build(str(project))

        skeleton = rm.get_skeleton("src/utils.py")
        assert "helper" in skeleton or "format_output" in skeleton

    def test_get_dependency_chain(self, project):
        rm = RepoMap()
        rm.build(str(project))

        chain = rm.get_dependency_chain("src/main.py")
        assert isinstance(chain, list)

    def test_ignore_patterns(self, project):
        # Create a node_modules dir that should be ignored
        (project / "node_modules").mkdir()
        (project / "node_modules" / "pkg.js").write_text("module.exports = {}")

        rm = RepoMap(ignore_patterns=["node_modules"])
        result = rm.build(str(project))

        for node in result.dependency_graph.keys():
            assert "node_modules" not in node


# ── SkeletonGenerator Tests ─────────────────────────────────────────────


class TestSkeletonGenerator:
    """Test skeleton generation for multiple languages."""

    @pytest.fixture
    def gen(self):
        return SkeletonGenerator()

    def test_python_skeleton(self, gen):
        code = (
            "import os\n\n"
            "class MyService:\n"
            '    """Handles business logic."""\n\n'
            "    def process(self, data):\n"
            "        result = data.upper()\n"
            "        return result\n\n"
            "    def validate(self, input_data):\n"
            "        if not input_data:\n"
            "            raise ValueError\n"
        )
        skeleton = gen.generate("service.py", code)
        assert "import os" in skeleton
        assert "class MyService" in skeleton
        assert "process" in skeleton
        assert "validate" in skeleton
        # Bodies should not be present
        assert "data.upper()" not in skeleton

    def test_java_skeleton(self, gen):
        code = (
            "package com.example;\n\n"
            "import java.util.List;\n\n"
            "public class UserService {\n"
            "    private String name;\n\n"
            "    public List<User> getUsers() {\n"
            "        return db.findAll();\n"
            "    }\n\n"
            "    public void deleteUser(String id) {\n"
            "        db.delete(id);\n"
            "    }\n"
            "}\n"
        )
        skeleton = gen.generate("UserService.java", code)
        assert "package com.example" in skeleton
        assert "import java.util.List" in skeleton
        assert "UserService" in skeleton
        assert "getUsers" in skeleton
        assert "deleteUser" in skeleton

    def test_typescript_skeleton(self, gen):
        code = (
            "import { Component } from '@angular/core';\n\n"
            "export interface User {\n"
            "  id: string;\n"
            "  name: string;\n"
            "}\n\n"
            "export class UserService {\n"
            "  getUser(id: string): User {\n"
            "    return this.http.get(`/api/users/${id}`);\n"
            "  }\n"
            "}\n"
        )
        skeleton = gen.generate("user.service.ts", code)
        assert "import" in skeleton
        assert "interface User" in skeleton or "User" in skeleton
        assert "UserService" in skeleton

    def test_unknown_extension(self, gen):
        skeleton = gen.generate("data.csv", "a,b,c\n1,2,3\n4,5,6\n")
        assert "a,b,c" in skeleton


# ── ContextCompressor Tests ─────────────────────────────────────────────


class TestContextCompressor:
    """Test context compression to fit token limits."""

    def test_compress_within_budget(self):
        compressor = ContextCompressor(max_tokens=2000)

        result = compressor.compress(
            structure_tree="project/\n  src/\n    main.py\n",
            tech_stack={"languages": ["python"], "frameworks": ["flask"]},
            file_rankings={"src/main.py": 0.8, "src/utils.py": 0.2},
            skeletons={
                "src/main.py": "def main(): ...",
                "src/utils.py": "def helper(): ...",
            },
        )

        assert len(result) > 0
        token_est = compressor.estimate_tokens(result)
        assert token_est <= 2000

    def test_high_priority_always_included(self):
        compressor = ContextCompressor(max_tokens=500)

        result = compressor.compress(
            structure_tree="project/\n  src/\n",
            tech_stack={"languages": ["java"], "build_system": "maven"},
            file_rankings={},
            skeletons={},
        )

        assert "Tech Stack" in result
        assert "java" in result

    def test_low_priority_dropped_when_over_budget(self):
        compressor = ContextCompressor(max_tokens=100)

        result = compressor.compress(
            structure_tree="short tree",
            tech_stack={"languages": ["python"]},
            file_rankings={"big_file.py": 0.1},
            skeletons={"big_file.py": "x" * 5000},  # very large
        )

        # Should not contain the huge skeleton
        assert len(result) < 5000

    def test_estimate_tokens(self):
        compressor = ContextCompressor()
        assert compressor.estimate_tokens("a" * 400) == 100
