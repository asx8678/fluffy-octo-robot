"""Tests for plan markdown generation and file persistence."""

from pathlib import Path

from code_muse.plugins.plan_mode.plan_generation import generate_plan_md, save_plan


class TestGeneratePlanMd:
    def test_contains_yaml_front_matter(self):
        md = generate_plan_md("Migrate DB", "notes", "discussion", ["step1", "step2"])
        assert md.startswith("---")
        assert 'goal: "Migrate DB"' in md
        assert "status: draft" in md

    def test_contains_all_sections(self):
        md = generate_plan_md("G", "R", "D", ["S1", "S2"])
        assert "# Plan: G" in md
        assert "## Analysis" in md
        assert "R" in md
        assert "## Discussion" in md
        assert "D" in md
        assert "## Implementation Steps" in md
        assert "1. S1" in md
        assert "2. S2" in md
        assert "## Risks" in md
        assert "(placeholder)" in md

    def test_numbered_steps(self):
        md = generate_plan_md("G", "R", "D", ["a", "b", "c"])
        assert "1. a" in md
        assert "2. b" in md
        assert "3. c" in md


class TestSavePlan:
    def test_creates_directory(self, tmp_path: Path):
        plans_dir = tmp_path / "plans"
        assert not plans_dir.exists()
        content = "# Test Plan"
        path = save_plan(content, plans_dir=plans_dir)
        assert plans_dir.exists()
        assert path.parent == plans_dir

    def test_writes_content(self, tmp_path: Path):
        plans_dir = tmp_path / "plans"
        content = "# Test Plan\n\nSteps here."
        path = save_plan(content, plans_dir=plans_dir)
        assert path.read_text(encoding="utf-8") == content

    def test_returns_path(self, tmp_path: Path):
        plans_dir = tmp_path / "plans"
        path = save_plan("content", plans_dir=plans_dir)
        assert isinstance(path, Path)
        assert path.name.startswith("plan_")
        assert path.suffix == ".md"
