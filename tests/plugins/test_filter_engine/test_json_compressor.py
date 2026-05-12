"""Tests for SmartCrusher JSON compression."""

import json

from code_muse.plugins.filter_engine.strategies.json_compressor import compress_json
from code_muse.plugins.filter_engine.strategies.json_patterns import (
    analyze_json,
    detect_array_template,
    detect_nested_structure,
    is_homogeneous_array,
    score_field_importance,
)

from code_muse.plugins.filter_engine.verbosity import VerbosityLevel


class TestPatternDetection:
    def test_homogeneous_dict_array(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5, "b": 6}]
        assert is_homogeneous_array(data) is True

    def test_mixed_shape_array(self):
        data = [{"a": 1}, {"a": 2, "b": 3}]
        assert is_homogeneous_array(data) is False

    def test_empty_array(self):
        assert is_homogeneous_array([]) is False

    def test_single_item_array(self):
        assert is_homogeneous_array([{"a": 1}]) is False

    def test_detect_template(self):
        data = [
            {"name": "foo", "version": "1.0"},
            {"name": "bar", "version": "2.0"},
        ]
        template = detect_array_template(data)
        assert template is not None
        assert template["version"] == "<UNIQUE>" or template["version"] == "1.0"
        assert template["name"] == "<UNIQUE>"

    def test_detect_template_all_same(self):
        data = [{"type": "node", "lang": "py"}, {"type": "node", "lang": "py"}]
        template = detect_array_template(data)
        assert template is not None
        assert template["type"] == "node"
        assert template["lang"] == "py"

    def test_field_scoring(self):
        scores = score_field_importance(
            {
                "name": "<UNIQUE>",
                "version": "<UNIQUE>",
                "error": "<UNIQUE>",
                "_internal": "<UNIQUE>",
                "id": "<UNIQUE>",
            }
        )
        assert scores["error"] == 1.0
        assert scores["name"] >= 0.8
        assert scores["_internal"] <= 0.2
        assert scores["id"] <= 0.6

    def test_nested_detection(self):
        data = {
            "items": [
                {"name": "a", "meta": {"ver": 1}},
                {"name": "b", "meta": {"ver": 2}},
            ]
        }
        paths = detect_nested_structure(data)
        assert "items.name" in paths or "items.meta.ver" in paths

    def test_analyze_json(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        result = analyze_json(data)
        assert result["is_homogeneous"] is True
        assert result["template"] is not None


class TestCompression:
    def test_compress_homogeneous_array_max(self):
        data = [
            {"name": "foo", "version": "1.0"},
            {"name": "bar", "version": "2.0"},
        ]
        result = compress_json(data, verbosity=0)
        assert len(result) < len(json.dumps(data))
        assert "@" in result or "name" in result

    def test_compress_homogeneous_array_normal(self):
        data = [
            {"name": "foo", "version": "1.0"},
            {"name": "bar", "version": "2.0"},
        ]
        result = compress_json(data, verbosity=2)
        assert "name" in result

    def test_compress_single_dict(self):
        data = {
            "name": "test-package",
            "version": "1.0.0",
            "dependencies": {"a": "^1.0"},
        }
        result = compress_json(data, verbosity=0)
        assert "name" in result
        assert "test-package" in result

    def test_compress_scalar(self):
        assert compress_json("hello", verbosity=0) == '"hello"'
        assert compress_json(42, verbosity=0) == "42"

    def test_compress_nested(self):
        data = {"a": {"b": {"c": 1}}}
        result = compress_json(data, verbosity=0)
        assert "c" in result or "1" in result

    def test_error_field_preserved(self):
        data = {"error": "something broke", "name": "test"}
        result = compress_json(data, verbosity=0)
        assert "error" in result.lower()


class TestIntegration:
    """Simulate what the registry strategy does."""

    def test_strategy_signature(self):
        """Verify the smartcrusher works like a strategy function."""
        stdout = json.dumps([{"a": 1}, {"a": 2}])
        from code_muse.plugins.filter_engine.registry import get_registry

        registry = get_registry()
        strategy = registry.get_strategy("json")
        assert strategy is not None
        from code_muse.tools.command_runner import ShellCommandOutput

        result = strategy("cat foo.json", stdout, "", 0, VerbosityLevel.ULTRA_COMPACT)
        # Should return ShellCommandOutput or None
        if result is not None:
            assert isinstance(result, ShellCommandOutput)
            assert len(result.stdout) < len(stdout)
