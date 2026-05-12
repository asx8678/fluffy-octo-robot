"""Tests for load_muse_rules() in code_muse.agents._builder.

Covers the .muse/ directory feature (PUP-34):
- Loading from .muse/AGENTS.md (preferred)
- Precedence: .muse/ over project root
- Backwards compatibility with root AGENTS.md
- Combining global + project rules
- Edge cases (dir is file, empty dir, etc.)
"""

from unittest.mock import patch

import pytest


class TestLoadMuseRulesMuseDir:
    """Tests for .muse/ directory support in load_muse_rules()."""

    @pytest.fixture
    def temp_project(self, tmp_path, monkeypatch):
        """Set up a temporary project directory and cd into it."""
        monkeypatch.chdir(tmp_path)
        return tmp_path

    @pytest.fixture
    def mock_config_dir(self, tmp_path):
        """Create a mock global config directory."""
        config_dir = tmp_path / "global_config"
        config_dir.mkdir()
        return config_dir

    def test_load_from_code_muse_dir(self, temp_project, mock_config_dir):
        """Load AGENTS.md from .muse/ directory."""
        from code_muse.agents._builder import load_muse_rules

        # Create .muse/AGENTS.md
        code_muse_dir = temp_project / ".muse"
        code_muse_dir.mkdir()
        agents_file = code_muse_dir / "AGENTS.md"
        agents_file.write_text("# Rules from .muse dir")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        assert result == "# Rules from .muse dir"

    def test_precedence_code_muse_over_root(self, temp_project, mock_config_dir):
        """Files in .muse/ take precedence over project root."""
        from code_muse.agents._builder import load_muse_rules

        # Create both locations
        code_muse_dir = temp_project / ".muse"
        code_muse_dir.mkdir()
        (code_muse_dir / "AGENTS.md").write_text("# Preferred rules")
        (temp_project / "AGENTS.md").write_text("# Root rules")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        # Should use .muse/ version, NOT root
        assert result == "# Preferred rules"
        assert "Root rules" not in (result or "")

    def test_fallback_to_root(self, temp_project, mock_config_dir):
        """Fall back to root AGENTS.md if .muse/ doesn't exist."""
        from code_muse.agents._builder import load_muse_rules

        # Only create root AGENTS.md
        (temp_project / "AGENTS.md").write_text("# Root rules")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        assert result == "# Root rules"

    def test_global_and_code_muse_combined(self, temp_project, mock_config_dir):
        """Global rules and .muse rules are combined."""
        from code_muse.agents._builder import load_muse_rules

        # Create global rules
        (mock_config_dir / "AGENTS.md").write_text("# Global rules")

        # Create .muse rules
        code_muse_dir = temp_project / ".muse"
        code_muse_dir.mkdir()
        (code_muse_dir / "AGENTS.md").write_text("# Project rules")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        # Both should be present, global first
        assert "# Global rules" in result
        assert "# Project rules" in result
        assert result.index("# Global rules") < result.index("# Project rules")

    def test_global_and_root_combined(self, temp_project, mock_config_dir):
        """Global rules + root rules work together."""
        from code_muse.agents._builder import load_muse_rules

        # Create global rules
        (mock_config_dir / "AGENTS.md").write_text("# Global rules")

        # Create root rules
        (temp_project / "AGENTS.md").write_text("# Root rules")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        # Both should be combined
        assert "# Global rules" in result
        assert "# Root rules" in result

    def test_code_muse_is_file_not_dir(self, temp_project, mock_config_dir):
        """If .muse is a file (not directory), fall back to root."""
        from code_muse.agents._builder import load_muse_rules

        # Create .muse as a FILE, not directory
        (temp_project / ".muse").write_text("I'm a file, not a dir!")

        # Create root AGENTS.md as fallback
        (temp_project / "AGENTS.md").write_text("# Root fallback")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        # Should use root fallback
        assert result == "# Root fallback"

    def test_code_muse_dir_exists_but_empty(self, temp_project, mock_config_dir):
        """Empty .muse/ dir falls back to root AGENTS.md."""
        from code_muse.agents._builder import load_muse_rules

        # Create empty .muse directory
        (temp_project / ".muse").mkdir()

        # Create root AGENTS.md as fallback
        (temp_project / "AGENTS.md").write_text("# Root fallback")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        # Should use root fallback
        assert result == "# Root fallback"

    def test_no_agents_files_anywhere(self, temp_project, mock_config_dir):
        """Returns None if no AGENTS.md files exist anywhere."""
        from code_muse.agents._builder import load_muse_rules

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        assert result is None

    def test_agent_md_variant_in_code_muse_dir(self, temp_project, mock_config_dir):
        """Also supports AGENT.md (singular) in .muse/."""
        from code_muse.agents._builder import load_muse_rules

        code_muse_dir = temp_project / ".muse"
        code_muse_dir.mkdir()
        # Use singular AGENT.md instead of AGENTS.md
        (code_muse_dir / "AGENT.md").write_text("# Singular agent rules")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        assert result == "# Singular agent rules"

    def test_agents_md_takes_precedence_over_agent_md(
        self, temp_project, mock_config_dir
    ):
        """AGENTS.md (plural) takes precedence over AGENT.md (singular)."""
        from code_muse.agents._builder import load_muse_rules

        code_muse_dir = temp_project / ".muse"
        code_muse_dir.mkdir()
        (code_muse_dir / "AGENTS.md").write_text("# Plural wins")
        (code_muse_dir / "AGENT.md").write_text("# Singular loses")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        assert result == "# Plural wins"

    def test_only_global_rules(self, temp_project, mock_config_dir):
        """Only global rules loaded when no project rules exist."""
        from code_muse.agents._builder import load_muse_rules

        # Create only global rules
        (mock_config_dir / "AGENTS.md").write_text("# Global only")

        with patch("code_muse.agents._builder.CONFIG_DIR", str(mock_config_dir)):
            result = load_muse_rules()

        assert result == "# Global only"
