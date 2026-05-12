from pathlib import Path

import pytest

from code_muse.plugins.custom_commands.command_toml_schema import parse_command_toml


class TestParseCommandTOML:
    def test_valid_toml(self, tmp_path: Path) -> None:
        path = tmp_path / "fix.toml"
        path.write_text('prompt = "Fix this bug"\ndescription = "A helpful command"')
        result = parse_command_toml(path)
        assert result.name == "fix"
        assert result.prompt == "Fix this bug"
        assert result.description == "A helpful command"

    def test_missing_prompt_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text('description = "No prompt here"')
        with pytest.raises(ValueError, match="missing required field 'prompt'"):
            parse_command_toml(path)

    def test_empty_prompt_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text('prompt = ""')
        with pytest.raises(ValueError, match="'prompt' must be a non-empty string"):
            parse_command_toml(path)

    def test_prompt_whitespace_only_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text('prompt = "   "')
        with pytest.raises(ValueError, match="'prompt' must be a non-empty string"):
            parse_command_toml(path)

    def test_invalid_prompt_type_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text("prompt = 42")
        with pytest.raises(ValueError, match="'prompt' must be a string"):
            parse_command_toml(path)

    def test_multiline_prompt(self, tmp_path: Path) -> None:
        path = tmp_path / "multi.toml"
        path.write_text('prompt = """Line one\nLine two\nLine three"""\n')
        result = parse_command_toml(path)
        assert result.prompt == "Line one\nLine two\nLine three"
        assert result.description == ""

    def test_description_optional(self, tmp_path: Path) -> None:
        path = tmp_path / "minimal.toml"
        path.write_text('prompt = "Do something"')
        result = parse_command_toml(path)
        assert result.description == ""

    def test_warns_on_unknown_fields(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "extra.toml"
        path.write_text('prompt = "Hello"\nfoo = "bar"\nbaz = 1')
        with caplog.at_level("WARNING"):
            parse_command_toml(path)
        assert "Unknown fields" in caplog.text
        assert "foo" in caplog.text
        assert "baz" in caplog.text
