"""Tests for code / read compression strategies."""

from code_muse.plugins.filter_engine.strategies.code import (
    AggressiveFilter,
    MinimalFilter,
    compress_code,
    compress_ls,
    compress_read,
    compress_tree,
    smart_truncate,
)

from code_muse.plugins.filter_engine.verbosity import VerbosityLevel


class TestMinimalFilter:
    """Minimal comment stripping."""

    def test_python_single_line(self) -> None:
        text = "x = 1  # comment\nprint(x)\n"
        result = MinimalFilter.strip_comments(text, "python")
        assert "# comment" not in result
        assert "x = 1" in result
        assert "print(x)" in result

    def test_python_keeps_docstrings(self) -> None:
        text = (
            "def foo():\n"
            '    """Args:\n'
            "        x: int\n"
            "    Returns:\n"
            "        int\n"
            '    """\n'
            "    return 1\n"
        )
        result = MinimalFilter.strip_comments(text, "python")
        assert '"""' in result
        assert "Args:" in result

    def test_javascript(self) -> None:
        text = "const x = 1; // comment\n/* block */\nconsole.log(x);\n"
        result = MinimalFilter.strip_comments(text, "javascript")
        assert "// comment" not in result
        assert "/* block */" not in result
        assert "const x = 1" in result

    def test_rust(self) -> None:
        text = 'let x = 1; // comment\n/* block */\nprintln!("{x}");\n'
        result = MinimalFilter.strip_comments(text, "rust")
        assert "// comment" not in result
        assert "/* block */" not in result
        assert "let x = 1" in result

    def test_bash(self) -> None:
        text = "#!/bin/bash\n# setup\necho hello\n"
        result = MinimalFilter.strip_comments(text, "bash")
        assert "# setup" not in result
        assert "echo hello" in result

    def test_sql(self) -> None:
        text = "SELECT * FROM t; -- get all\n/* multi\nline */\n"
        result = MinimalFilter.strip_comments(text, "sql")
        assert "-- get all" not in result
        assert "/* multi" not in result
        assert "SELECT * FROM t" in result


class TestAggressiveFilter:
    """Aggressive comment stripping."""

    def test_python_strips_all(self) -> None:
        text = 'x = 1  # comment\n    """docstring"""\nprint(x)\n'
        result = AggressiveFilter.strip_comments(text, "python")
        assert "# comment" not in result
        assert '"""docstring"""' not in result
        assert "print(x)" in result

    def test_collapses_blank_lines(self) -> None:
        text = "a\n\n\n\nb\n"
        result = AggressiveFilter.strip_comments(text, "python")
        assert result.count("\n\n") <= 1
        assert "a" in result
        assert "b" in result


class TestSmartTruncate:
    """Smart truncation behaviour."""

    def test_short_text_preserved(self) -> None:
        text = "line1\nline2\nline3\n"
        assert smart_truncate(text, max_lines=10) == text

    def test_truncates_long_text(self) -> None:
        text = "\n".join(f"line{i}" for i in range(100))
        result = smart_truncate(text, max_lines=20)
        assert len(result.splitlines()) <= 21  # + "... more" line

    def test_preserves_imports(self) -> None:
        text = "import os\n" + "\n".join(f"line{i}" for i in range(100))
        result = smart_truncate(text, max_lines=10)
        assert "import os" in result

    def test_preserves_signatures(self) -> None:
        text = "def foo():\n" + "\n".join(f"line{i}" for i in range(100))
        result = smart_truncate(text, max_lines=10)
        assert "def foo():" in result

    def test_drops_boilerplate(self) -> None:
        text = "# TODO fix me\n" + "\n".join(f"line{i}" for i in range(50))
        result = smart_truncate(text, max_lines=20)
        assert "# TODO fix me" not in result


class TestTreeCompression:
    """ls / tree output compression."""

    SAMPLE = ".:\ncore.py\nutils.py\ntests:\ntest_core.py\ntest_utils.py\n"

    def test_compact_counts(self) -> None:
        out = compress_tree(self.SAMPLE, "", VerbosityLevel.COMPACT)
        assert ".:" in out.stdout or "." in out.stdout
        assert "tests" in out.stdout

    def test_empty_directory(self) -> None:
        out = compress_tree("", "", VerbosityLevel.COMPACT)
        assert "Empty directory" in out.stdout


class TestReadCompression:
    """Read command compression."""

    CODE = (
        "import os\n"
        "# This is a module\n"
        "\n"
        "def foo():\n"
        "    # helper\n"
        "    return 1\n"
        "\n" * 50  # make it long enough to trigger truncation
    )

    def test_compact_strips_comments_and_truncates(self) -> None:
        out = compress_read("cat file.py", self.CODE, "", 0, VerbosityLevel.COMPACT)
        assert "# This is a module" not in out.stdout
        assert "import os" in out.stdout
        assert "def foo():" in out.stdout

    def test_very_verbose_passthrough(self) -> None:
        out = compress_read(
            "cat file.py", self.CODE, "", 0, VerbosityLevel.VERY_VERBOSE
        )
        assert out.stdout == self.CODE

    def test_head_command(self) -> None:
        out = compress_read(
            "head -20 file.py", "line1\n" * 30, "", 0, VerbosityLevel.COMPACT
        )
        assert out.stdout is not None

    def test_ast_compression_for_pyi(self) -> None:
        out = compress_read(
            "cat stubs.pyi", "def foo() -> int: ...\n", "", 0, VerbosityLevel.COMPACT
        )
        assert "def foo" in out.stdout

    def test_ast_compression_for_mjs(self) -> None:
        out = compress_read(
            "cat module.mjs",
            "function foo() { return 1; }\n",
            "",
            0,
            VerbosityLevel.COMPACT,
        )
        assert "function foo" in out.stdout

    def test_ast_compression_for_cjs(self) -> None:
        out = compress_read(
            "cat module.cjs",
            "function bar() { return 2; }\n",
            "",
            0,
            VerbosityLevel.COMPACT,
        )
        assert "function bar" in out.stdout

    def test_ast_compression_for_jsx(self) -> None:
        out = compress_read(
            "cat component.jsx",
            "function Foo() { return <div />; }\n",
            "",
            0,
            VerbosityLevel.COMPACT,
        )
        assert "function Foo" in out.stdout

    def test_ast_compression_for_tsx(self) -> None:
        out = compress_read(
            "cat component.tsx",
            "function Foo() { return <div />; }\n",
            "",
            0,
            VerbosityLevel.COMPACT,
        )
        assert "function Foo" in out.stdout


class TestLsCompression:
    """ls command compression routing."""

    def test_routes_to_tree(self) -> None:
        out = compress_ls("ls -R", ".:\na.py\n", "", 0, VerbosityLevel.COMPACT)
        assert out is not None
        assert "." in out.stdout


class TestCodeDispatcher:
    """Main code dispatcher routing."""

    def test_cat_route(self) -> None:
        out = compress_code("cat file.py", "import os\n", "", 0, VerbosityLevel.COMPACT)
        assert out is not None
        assert "import os" in out.stdout

    def test_sed_route(self) -> None:
        out = compress_code(
            "sed 's/a/b/' file.py", "content\n", "", 0, VerbosityLevel.COMPACT
        )
        assert out is not None

    def test_ls_route(self) -> None:
        out = compress_code("ls", "a.py\nb.py\n", "", 0, VerbosityLevel.COMPACT)
        assert out is not None
        assert "a.py" in out.stdout or "2 files" in out.stdout

    def test_generic_command_with_supported_filename(self) -> None:
        out = compress_code(
            "sed 's/a/b/' file.go",
            "package main\n\nfunc main() {}\n",
            "",
            0,
            VerbosityLevel.COMPACT,
        )
        assert out is not None
        assert "func main" in out.stdout

    def test_generic_command_with_unsupported_filename(self) -> None:
        out = compress_code(
            "sed 's/a/b/' file.rs",
            'let x = 1; // comment\nprintln!("{x}");\n',
            "",
            0,
            VerbosityLevel.COMPACT,
        )
        assert out is not None
        assert "// comment" not in out.stdout
        assert "let x = 1" in out.stdout
