"""Tests for smart_output_compressor.

Covers:
- Tree-sitter parsing for Python (imports, functions, classes, decorators)
- Fallback to stdlib ast when tree-sitter unavailable
- Compression: imports always kept, high-relevance kept, low-relevance elided
- Scoring by focus areas
- Median reduction percentage
- Config: enabled/disabled toggling
- read_smart tool registration
- /smart command handling
- >=25% median reduction acceptance test
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from code_muse.plugins.smart_output_compressor.compressor import (
    _score_node,
    compress_file_lines,
)
from code_muse.plugins.smart_output_compressor.config import (
    get_enabled,
    get_max_lines,
    set_enabled,
)
from code_muse.plugins.smart_output_compressor.metrics import (
    CompressMetrics,
    format_metrics_summary,
    get_metrics,
)
from code_muse.plugins.smart_output_compressor.models import CompressedOutput
from code_muse.plugins.smart_output_compressor.parser import (
    detect_language,
    parse_file,
)

# ---------------------------------------------------------------------------
# Sample code fixtures
# ---------------------------------------------------------------------------

PYTHON_SAMPLE = dedent("""\
    import os
    import sys
    from pathlib import Path
    from collections import defaultdict

    def process_data(items):
        pass

    def calculate_score(data, weights=None):
        pass

    class DataProcessor:
        def __init__(self, config=None):
            self.config = config or {}
            self.cache = {}

        def process(self, data):
            return process_data(data)

        def get_stats(self):
            return self.cache

    def format_output(data, template=None):
        pass

    def validate_input(data):
        pass
""")

# A more realistic Python file with full function bodies
PYTHON_HEAVY = dedent("""\
    import os
    import sys
    import json
    import logging
    from pathlib import Path
    from collections import defaultdict, OrderedDict
    from typing import Any, Optional, Dict, List

    logger = logging.getLogger(__name__)

    def process_data(items):
        \"\"\"Process a list of data items.\"\"\"
        result = defaultdict(list)
        for item in items:
            key = item.get('type', 'unknown')
            result[key].append(item)
        return dict(result)

    def calculate_score(data, weights=None):
        \"\"\"Calculate weighted score from data.\"\"\"
        if weights is None:
            weights = {}
        score = 0.0
        for key, value in data.items():
            weight = weights.get(key, 1.0)
            score += value * weight
        return score

    class DataProcessor:
        \"\"\"Main data processor class.\"\"\"

        def __init__(self, config=None):
            self.config = config or {}
            self.cache = {}

        def process(self, data):
            return process_data(data)

        def get_stats(self):
            return self.cache

    def format_output(data, template=None):
        \"\"\"Format data for output.\"\"\"
        if template:
            return template.format(**data)
        return str(data)

    def validate_input(data):
        \"\"\"Validate input data.\"\"\"
        if not isinstance(data, (list, dict)):
            raise ValueError("Input must be list or dict")
        return True
""")

DECORATED_SAMPLE = dedent("""\
    import click

    @click.command()
    @click.option('--name', default='World')
    def hello(name):
        print(f'Hello {name}')

    @dataclass
    class Config:
        value: int = 42
""")


# ---------------------------------------------------------------------------
# Test: Parser
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_python(self):
        assert detect_language("foo.py") == "python"

    def test_javascript(self):
        assert detect_language("foo.js") == "javascript"

    def test_typescript(self):
        assert detect_language("foo.ts") == "typescript"

    def test_go(self):
        assert detect_language("foo.go") == "go"

    def test_unknown(self):
        assert detect_language("foo.txt") == "unknown"

    def test_no_extension(self):
        assert detect_language("Makefile") == "unknown"


class TestParser:
    def test_parse_python_with_tree_sitter(self):
        nodes, fallback = parse_file(PYTHON_HEAVY, "test.py")
        assert fallback is False, "Should use tree-sitter, not fallback"
        assert len(nodes) > 0
        imports = [n for n in nodes if n["kind"] == "import"]
        assert len(imports) >= 3, f"Expected >=3 imports, got {len(imports)}"
        funcs = [n for n in nodes if n["kind"] == "function"]
        assert len(funcs) >= 3, f"Expected >=3 functions, got {len(funcs)}"
        classes = [n for n in nodes if n["kind"] == "class"]
        assert len(classes) >= 1, f"Expected >=1 class, got {len(classes)}"

    def test_parse_import_names(self):
        nodes, _ = parse_file(PYTHON_HEAVY, "test.py")
        imports = [n for n in nodes if n["kind"] == "import"]
        import_names = [n["name"] for n in imports if n["name"]]
        assert "os" in import_names
        assert "pathlib" in import_names

    def test_parse_function_names(self):
        nodes, _ = parse_file(PYTHON_HEAVY, "test.py")
        func_names = [n["name"] for n in nodes if n["kind"] == "function"]
        assert "process_data" in func_names
        assert "calculate_score" in func_names

    def test_parse_class_name(self):
        nodes, _ = parse_file(PYTHON_HEAVY, "test.py")
        class_names = [n["name"] for n in nodes if n["kind"] == "class"]
        assert "DataProcessor" in class_names

    def test_parse_decorated(self):
        nodes, fallback = parse_file(DECORATED_SAMPLE, "test.py")
        assert fallback is False
        func_names = [n["name"] for n in nodes if n["kind"] == "function"]
        assert "hello" in func_names
        class_names = [n["name"] for n in nodes if n["kind"] == "class"]
        assert "Config" in class_names

    def test_parse_empty_code(self):
        nodes, fallback = parse_file("", "test.py")
        assert isinstance(nodes, list)

    def test_parse_fallback_to_stdlib(self):
        """When tree-sitter fails, should fall back to stdlib ast."""
        with patch(
            "code_muse.plugins.smart_output_compressor.parser._parse_with_tree_sitter",
            return_value=None,
        ):
            nodes, fallback = parse_file(PYTHON_HEAVY, "test.py")
            assert fallback is True
            assert len(nodes) > 0

    def test_node_content_includes_newline(self):
        nodes, _ = parse_file("import os\n", "test.py")
        imports = [n for n in nodes if n["kind"] == "import"]
        assert len(imports) >= 1
        assert imports[0]["content"].endswith("\n")

    def test_non_python_returns_empty_or_parsed(self):
        """Non-Python files without tree-sitter grammar return gracefully."""
        nodes, fallback = parse_file("fn main() {}", "test.rs")
        assert fallback is True


# ---------------------------------------------------------------------------
# Test: Compressor
# ---------------------------------------------------------------------------


class TestCompressor:
    def test_keep_imports(self):
        result = compress_file_lines(
            PYTHON_HEAVY, "test.py", focus_areas=["nonexistent"], max_lines=200
        )
        assert "import os" in result.raw_output
        assert "from pathlib import Path" in result.raw_output

    def test_elide_low_relevance_function(self):
        result = compress_file_lines(
            PYTHON_HEAVY, "test.py", focus_areas=["DataProcessor"], max_lines=200
        )
        # calculate_score should be mentioned in elision marker
        assert "calculate_score" in result.raw_output
        # But its body should NOT be present
        assert "weights.get" not in result.raw_output

    def test_keep_high_relevance_function(self):
        result = compress_file_lines(
            PYTHON_HEAVY, "test.py", focus_areas=["process_data"], max_lines=200
        )
        assert "result[key].append(item)" in result.raw_output

    def test_score_by_focus_area(self):
        node = {"kind": "function", "name": "process_data"}
        assert _score_node(node, ["process_data"]) == 1.0

        node2 = {
            "kind": "function",
            "name": "foo",
            "content": "process_data call",
        }
        assert _score_node(node2, ["process_data"]) == 0.7

        node3 = {"kind": "function", "name": "foo"}
        assert _score_node(node3, []) == 0.5

        node4 = {"kind": "import", "name": "os"}
        assert _score_node(node4, []) == 1.0

    def test_reduction_percentage(self):
        result = compress_file_lines(
            PYTHON_HEAVY, "test.py", focus_areas=["DataProcessor"], max_lines=50
        )
        assert result.reduction_pct > 0
        assert result.total_lines > result.kept_lines

    def test_max_lines_respected(self):
        result = compress_file_lines(
            PYTHON_HEAVY, "test.py", focus_areas=[], max_lines=10
        )
        assert result.kept_lines <= 40  # Some slack for markers

    def test_empty_file(self):
        result = compress_file_lines("", "empty.py", focus_areas=[], max_lines=200)
        assert result.total_lines == 0

    def test_no_focus_areas_neutral_score(self):
        """Without focus areas, nodes get neutral 0.5 score."""
        result = compress_file_lines(
            PYTHON_HEAVY, "test.py", focus_areas=[], max_lines=200
        )
        assert "import os" in result.raw_output


class TestAcceptanceReduction:
    """Acceptance criterion: >=25% median token reduction."""

    def test_median_reduction_above_25_pct(self):
        """Simulate a file-heavy session with diverse Python files."""
        metrics = CompressMetrics()

        # File 1: Heavy module (~50 lines)
        r1 = compress_file_lines(PYTHON_HEAVY, "module1.py", ["DataProcessor"], 50)
        metrics.record(r1)

        # File 2: Config module (~80 lines)
        file2 = dedent("""\
            import os
            import json
            import logging
            from typing import Any, Optional, Dict, List
            from dataclasses import dataclass, field, asdict
            from pathlib import Path
            from collections import OrderedDict

            logger = logging.getLogger(__name__)

            @dataclass
            class AppConfig:
                name: str = "default"
                debug: bool = False
                port: int = 8080
                database_url: str = "sqlite:///db.sqlite3"
                redis_url: str = "redis://localhost:6379"
                log_level: str = "INFO"
                max_connections: int = 100
                timeout_seconds: int = 30

            def load_config(path: str) -> AppConfig:
                \"\"\"Load configuration from a JSON file.\"\"\"
                with open(path) as f:
                    data = json.load(f)
                logger.info("Loaded config from %s", path)
                return AppConfig(**data)

            def save_config(config: AppConfig, path: str) -> None:
                \"\"\"Save configuration to a JSON file.\"\"\"
                with open(path, "w") as f:
                    json.dump(asdict(config), f, indent=2)
                logger.info("Saved config to %s", path)

            def merge_configs(
                base: AppConfig, override: AppConfig
            ) -> AppConfig:
                \"\"\"Merge two configs, override wins.\"\"\"
                result = asdict(base)
                for k, v in asdict(override).items():
                    if v is not None:
                        result[k] = v
                return AppConfig(**result)

            def validate_config(config: AppConfig) -> list[str]:
                \"\"\"Validate config and return list of errors.\"\"\"
                errors: list[str] = []
                if config.port < 1 or config.port > 65535:
                    errors.append("Invalid port number")
                if config.max_connections < 1:
                    errors.append("Max connections must be positive")
                if not config.database_url:
                    errors.append("Database URL required")
                return errors

            def reload_config(
                config: AppConfig, path: str
            ) -> AppConfig:
                \"\"\"Reload config from disk.\"\"\"
                new_config = load_config(path)
                return merge_configs(config, new_config)

            @dataclass
            class CacheConfig:
                backend: str = "redis"
                ttl: int = 3600
                max_size: int = 1000
                key_prefix: str = "app"

            def configure_cache(
                cache_config: CacheConfig,
            ) -> Dict[str, Any]:
                \"\"\"Set up cache from config.\"\"\"
                return {
                    "backend": cache_config.backend,
                    "ttl": cache_config.ttl,
                    "max_size": cache_config.max_size,
                    "key_prefix": cache_config.key_prefix,
                }

            def clear_cache(
                cache_config: CacheConfig,
            ) -> None:
                \"\"\"Clear the cache.\"\"\"
                logger.info(
                    "Clearing cache prefix %s",
                    cache_config.key_prefix,
                )
""")
        r2 = compress_file_lines(file2, "config.py", ["AppConfig"], 50)
        metrics.record(r2)

        # File 3: Utility module (~35 lines)
        file3 = dedent("""\
            import re
            import hashlib
            import unicodedata
            from datetime import datetime, timezone

            def slugify(text: str) -> str:
                \"\"\"Convert text to URL-safe slug.\"\"\"
                text = unicodedata.normalize("NFKD", text)
                text = re.sub(r"[^\\w\\s-]", "", text.lower())
                return re.sub(r"[-\\s]+", "-", text).strip("-")

            def hash_string(
                s: str, algorithm: str = "sha256"
            ) -> str:
                \"\"\"Hash a string with the given algorithm.\"\"\"
                h = hashlib.new(algorithm)
                h.update(s.encode("utf-8"))
                return h.hexdigest()

            def timestamp_now() -> str:
                \"\"\"Return current UTC timestamp.\"\"\"
                return datetime.now(timezone.utc).isoformat()

            def truncate_text(
                text: str, max_length: int = 100,
                suffix: str = "..."
            ) -> str:
                \"\"\"Truncate text to max_length.\"\"\"
                if len(text) <= max_length:
                    return text
                return text[: max_length - len(suffix)] + suffix

            def normalize_whitespace(text: str) -> str:
                \"\"\"Normalize whitespace in text.\"\"\"
                return " ".join(text.split())

            def extract_numbers(text: str) -> list[float]:
                \"\"\"Extract all numbers from text.\"\"\"
                return [
                    float(m)
                    for m in re.findall(
                        r"-?\\d+\\.?\\d*", text
                    )
                ]
""")
        r3 = compress_file_lines(file3, "utils.py", ["slugify", "hash_string"], 50)
        metrics.record(r3)

        assert metrics.median_reduction_pct >= 25.0, (
            f"Median reduction {metrics.median_reduction_pct:.1f}% "
            f"does not meet >=25% target"
        )


# ---------------------------------------------------------------------------
# Test: Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_record_tracks_reductions(self):
        metrics = CompressMetrics()
        output = CompressedOutput(
            file_path="test.py",
            total_lines=100,
            kept_lines=50,
            nodes=[],
            language="python",
            used_fallback=False,
            raw_output="",
        )
        metrics.record(output)
        assert metrics.total_files == 1
        assert metrics.total_lines_before == 100
        assert metrics.total_lines_after == 50
        assert metrics.reductions == [50.0]

    def test_median_reduction_single(self):
        metrics = CompressMetrics()
        metrics.reductions = [50.0]
        assert metrics.median_reduction_pct == 50.0

    def test_median_reduction_even(self):
        metrics = CompressMetrics()
        metrics.reductions = [20.0, 40.0, 60.0, 80.0]
        assert metrics.median_reduction_pct == 50.0

    def test_median_reduction_odd(self):
        metrics = CompressMetrics()
        metrics.reductions = [20.0, 50.0, 80.0]
        assert metrics.median_reduction_pct == 50.0

    def test_median_reduction_empty(self):
        metrics = CompressMetrics()
        assert metrics.median_reduction_pct == 0.0

    def test_format_summary(self):
        # format_metrics_summary uses the global singleton
        global_metrics = get_metrics()
        saved = CompressMetrics(
            total_files=global_metrics.total_files,
            total_lines_before=global_metrics.total_lines_before,
            total_lines_after=global_metrics.total_lines_after,
            reductions=list(global_metrics.reductions),
        )
        try:
            output = CompressedOutput(
                file_path="test.py",
                total_lines=100,
                kept_lines=60,
                nodes=[],
                language="python",
                used_fallback=False,
                raw_output="",
            )
            global_metrics.record(output)
            summary = format_metrics_summary()
            assert "Files processed:" in summary
            assert "Lines before:" in summary
        finally:
            global_metrics.total_files = saved.total_files
            global_metrics.total_lines_before = saved.total_lines_before
            global_metrics.total_lines_after = saved.total_lines_after
            global_metrics.reductions = saved.reductions


# ---------------------------------------------------------------------------
# Test: Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_enabled(self):
        with patch(
            "code_muse.plugins.smart_output_compressor.config.get_value",
            return_value=None,
        ):
            assert get_enabled() is True

    def test_toggle_on_off(self):
        with patch(
            "code_muse.plugins.smart_output_compressor.config.set_config_value"
        ) as mock_set:
            set_enabled(True)
            mock_set.assert_called_with("smart_compressor_enabled", "true")

            set_enabled(False)
            mock_set.assert_called_with("smart_compressor_enabled", "false")

    def test_max_lines_clamp(self):
        with patch(
            "code_muse.plugins.smart_output_compressor.config.get_value",
            return_value=None,
        ):
            assert get_max_lines() == 200

        with patch(
            "code_muse.plugins.smart_output_compressor.config.get_value",
            return_value="5000",
        ):
            assert get_max_lines() == 2000

        with patch(
            "code_muse.plugins.smart_output_compressor.config.get_value",
            return_value="10",
        ):
            assert get_max_lines() == 50


# ---------------------------------------------------------------------------
# Test: Tool registration
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Minimal stub that records calls to agent.tool(...)."""

    def __init__(self) -> None:
        self.registered_tools: list = []

    def tool(self, func) -> None:
        self.registered_tools.append(func)


class TestToolsRegistration:
    def test_register_tools_returns_correct_shape(self):
        from code_muse.plugins.smart_output_compressor.tools import register_tools

        with patch(
            "code_muse.plugins.smart_output_compressor.tools.get_enabled",
            return_value=True,
        ):
            result = register_tools()
            assert isinstance(result, list)
            assert len(result) == 1
            entry = result[0]
            assert "name" in entry
            assert "register_func" in entry
            assert entry["name"] == "read_smart"
            assert callable(entry["register_func"])

    def test_register_func_registers_tool_on_agent(self):
        from code_muse.plugins.smart_output_compressor.tools import register_tools

        with patch(
            "code_muse.plugins.smart_output_compressor.tools.get_enabled",
            return_value=True,
        ):
            result = register_tools()
            register_func = result[0]["register_func"]

            agent = _FakeAgent()
            register_func(agent)

            assert len(agent.registered_tools) == 1

    def test_read_smart_reads_file(self):
        """Test the actual tool function end-to-end."""
        import inspect

        from code_muse.plugins.smart_output_compressor.tools import register_tools

        with patch(
            "code_muse.plugins.smart_output_compressor.tools.get_enabled",
            return_value=True,
        ):
            result = register_tools()
            register_func = result[0]["register_func"]

            agent = _FakeAgent()
            register_func(agent)

            tool_fn = agent.registered_tools[0]
            sig = inspect.signature(tool_fn)
            param_names = list(sig.parameters.keys())
            assert "file_path" in param_names
            assert "focus_areas" in param_names

    def test_read_smart_on_temp_file(self):
        """Integration test: read_smart on a real temp file."""
        from code_muse.plugins.smart_output_compressor.tools import (
            _read_smart_tool_impl,
        )

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(PYTHON_HEAVY)
            f.flush()
            tmp_path = f.name

        try:
            with (
                patch(
                    "code_muse.plugins.smart_output_compressor.tools.get_enabled",
                    return_value=True,
                ),
                patch(
                    "code_muse.plugins.smart_output_compressor.tools"
                    ".check_path_allowed",
                    return_value=type("PD", (), {"allowed": True, "reason": None})(),
                ),
            ):
                result = _read_smart_tool_impl(
                    context=None,
                    file_path=tmp_path,
                    focus_areas=["DataProcessor"],
                )
                assert result.content is not None
                assert result.error is None
                assert "import os" in result.content
                assert "DataProcessor" in result.content
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_read_smart_disabled(self):
        from code_muse.plugins.smart_output_compressor.tools import (
            _read_smart_tool_impl,
        )

        with patch(
            "code_muse.plugins.smart_output_compressor.tools.get_enabled",
            return_value=False,
        ):
            result = _read_smart_tool_impl(
                context=None, file_path="test.py", focus_areas=[]
            )
            assert "disabled" in (result.content or "").lower()

    def test_read_smart_file_not_found(self):
        from code_muse.plugins.smart_output_compressor.tools import (
            _read_smart_tool_impl,
        )

        with (
            patch(
                "code_muse.plugins.smart_output_compressor.tools.get_enabled",
                return_value=True,
            ),
            patch(
                "code_muse.plugins.smart_output_compressor.tools.check_path_allowed",
                return_value=type("PD", (), {"allowed": True, "reason": None})(),
            ),
        ):
            result = _read_smart_tool_impl(
                context=None,
                file_path="/nonexistent/path/test.py",
                focus_areas=[],
            )
            assert result.error is not None
            assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# Test: Callbacks / Commands
# ---------------------------------------------------------------------------


class TestCallbacks:
    def test_register_tools_callback_shape(self):
        from code_muse.plugins.smart_output_compressor.register_callbacks import (
            _register_smart_tool,
        )

        with patch(
            "code_muse.plugins.smart_output_compressor.register_callbacks.get_enabled",
            return_value=True,
        ):
            result = _register_smart_tool()
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["name"] == "read_smart"

    def test_register_tools_returns_empty_when_disabled(self):
        from code_muse.plugins.smart_output_compressor.register_callbacks import (
            _register_smart_tool,
        )

        with patch(
            "code_muse.plugins.smart_output_compressor.register_callbacks.get_enabled",
            return_value=False,
        ):
            result = _register_smart_tool()
            assert result == []

    def test_load_prompt_when_enabled(self):
        from code_muse.plugins.smart_output_compressor.register_callbacks import (
            _load_smart_compressor_prompt,
        )

        with patch(
            "code_muse.plugins.smart_output_compressor.register_callbacks.get_enabled",
            return_value=True,
        ):
            prompt = _load_smart_compressor_prompt()
            assert prompt is not None
            assert "read_smart" in prompt

    def test_load_prompt_when_disabled(self):
        from code_muse.plugins.smart_output_compressor.register_callbacks import (
            _load_smart_compressor_prompt,
        )

        with patch(
            "code_muse.plugins.smart_output_compressor.register_callbacks.get_enabled",
            return_value=False,
        ):
            prompt = _load_smart_compressor_prompt()
            assert prompt is None

    def test_handle_smart_status(self):
        from code_muse.plugins.smart_output_compressor.register_callbacks import (
            _handle_smart_command,
        )

        with patch(
            "code_muse.plugins.smart_output_compressor.register_callbacks.get_enabled",
            return_value=True,
        ):
            result = _handle_smart_command("/smart status", "smart")
            assert "ON" in str(result)

    def test_handle_smart_wrong_command(self):
        from code_muse.plugins.smart_output_compressor.register_callbacks import (
            _handle_smart_command,
        )

        result = _handle_smart_command("/other", "other")
        assert result is None

    def test_custom_command_help(self):
        from code_muse.plugins.smart_output_compressor.register_callbacks import (
            _custom_command_help,
        )

        help_items = _custom_command_help()
        assert isinstance(help_items, list)
        assert any("smart" in item[0].lower() for item in help_items)
