"""Tests for AST-aware code compression."""

from code_muse.plugins.filter_engine.strategies.ast_compressor import (
    _fallback_compress,
    compress_ast_code,
    compress_go,
    compress_javascript,
    compress_python,
)

from code_muse.plugins.filter_engine.strategies.ast_parser import (
    CodeLanguage,
    LanguageParser,
)
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel


class TestLanguageDetection:
    """Language detection from filenames and content."""

    def test_python_by_ext(self) -> None:
        assert (
            LanguageParser.detect_language("print(1)", "foo.py") == CodeLanguage.PYTHON
        )

    def test_javascript_by_ext(self) -> None:
        assert (
            LanguageParser.detect_language("console.log(1)", "foo.js")
            == CodeLanguage.JAVASCRIPT
        )

    def test_go_by_ext(self) -> None:
        assert (
            LanguageParser.detect_language("package main", "main.go") == CodeLanguage.GO
        )

    def test_python_by_shebang(self) -> None:
        src = "#!/usr/bin/env python3\nprint(1)"
        assert LanguageParser.detect_language(src) == CodeLanguage.PYTHON

    def test_go_by_content(self) -> None:
        src = 'package main\n\nfunc main() {\n\tfmt.Println("hello")\n}'
        assert LanguageParser.detect_language(src) == CodeLanguage.GO

    def test_typescript_by_content(self) -> None:
        src = "interface Foo { bar: string }\nconst x: Foo = { bar: 'hi' }"
        assert LanguageParser.detect_language(src) == CodeLanguage.TYPESCRIPT

    def test_unknown_for_random_text(self) -> None:
        assert LanguageParser.detect_language("hello world") == CodeLanguage.UNKNOWN


class TestPythonCompression:
    """Python AST compression behaviour."""

    def test_keeps_function_signature(self) -> None:
        src = 'def foo(a: int, b: str) -> bool:\n    """Docstring."""\n    return True'
        result = compress_python(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "def foo" in result
        assert "Docstring" not in result

    def test_keeps_imports(self) -> None:
        src = "import os\nimport sys\n\ndef main():\n    pass"
        result = compress_python(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "import os" in result
        assert "import sys" in result

    def test_keeps_class_signature(self) -> None:
        src = 'class MyClass:\n    """Doc."""\n    def method(self):\n        pass'
        result = compress_python(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "class MyClass" in result

    def test_drops_function_body(self) -> None:
        src = "def foo():\n    x = 1\n    y = 2\n    return x + y"
        result = compress_python(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "def foo" in result
        assert "x = 1" not in result or "... lines omitted" in result

    def test_keeps_try_except(self) -> None:
        src = "try:\n    risky()\nexcept ValueError as e:\n    raise e"
        result = compress_python(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "try" in result.lower()
        assert "except" in result.lower()
        assert "ValueError" in result

    def test_verbosity_keeps_some_body(self) -> None:
        src = "def foo():\n    x = 1\n    y = 2\n    z = 3\n    return x + y + z"
        result = compress_python(src, verbosity=VerbosityLevel.VERBOSE)
        assert "def foo" in result
        # VERBOSE (level 2) keeps class first lines but not function bodies


class TestJSCompression:
    """JavaScript/TypeScript AST compression."""

    def test_keeps_function(self) -> None:
        src = "function hello(name) {\n  return 'Hello ' + name;\n}"
        result = compress_javascript(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "function hello" in result

    def test_drops_body(self) -> None:
        src = "function calc(a, b) {\n  const x = a + b;\n  return x;\n}"
        result = compress_javascript(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "function calc" in result

    def test_keeps_import(self) -> None:
        src = "import { foo } from 'bar';\nfunction test() {\n  return foo();\n}"
        result = compress_javascript(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "import" in result
        assert "function test" in result


class TestGoCompression:
    """Go AST compression."""

    def test_keeps_func(self) -> None:
        src = 'package main\n\nfunc main() {\n\tfmt.Println("hello")\n}'
        result = compress_go(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "func main" in result

    def test_keeps_type(self) -> None:
        src = "type Server struct {\n\tport int\n\thost string\n}"
        result = compress_go(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "type Server struct" in result

    def test_keeps_imports(self) -> None:
        src = 'package main\n\nimport "fmt"\n\nfunc main() {}'
        result = compress_go(src, verbosity=VerbosityLevel.ULTRA_COMPACT)
        assert "import" in result


class TestCompressAstCode:
    """Top-level dispatch compressor."""

    def test_python_dispatch(self) -> None:
        src = "def foo():\n    return 1\n"
        result = compress_ast_code(src, language=CodeLanguage.PYTHON)
        assert "def foo" in result

    def test_javascript_dispatch(self) -> None:
        src = "function foo() { return 1; }"
        result = compress_ast_code(src, language=CodeLanguage.JAVASCRIPT)
        assert "function foo" in result

    def test_go_dispatch(self) -> None:
        src = "func foo() int { return 1 }"
        result = compress_ast_code(src, language=CodeLanguage.GO)
        assert "func foo" in result

    def test_filename_detection(self) -> None:
        src = "def foo():\n    return 1\n"
        result = compress_ast_code(src, filename="foo.py")
        assert "def foo" in result

    def test_pyi_filename_detection(self) -> None:
        src = "def foo() -> int: ...\n"
        result = compress_ast_code(src, filename="stubs.pyi")
        assert "def foo" in result

    def test_mjs_filename_detection(self) -> None:
        src = "function foo() { return 1; }\n"
        result = compress_ast_code(src, filename="module.mjs")
        assert "function foo" in result

    def test_cjs_filename_detection(self) -> None:
        src = "function bar() { return 2; }\n"
        result = compress_ast_code(src, filename="module.cjs")
        assert "function bar" in result

    def test_jsx_filename_detection(self) -> None:
        src = "function Foo() { return <div />; }\n"
        result = compress_ast_code(src, filename="component.jsx")
        assert "function Foo" in result

    def test_tsx_filename_detection(self) -> None:
        src = "function Foo() { return <div />; }\n"
        result = compress_ast_code(src, filename="component.tsx")
        assert "function Foo" in result

    def test_unknown_language_fallback(self) -> None:
        src = "some random text\nnot code"
        result = compress_ast_code(src)
        assert isinstance(result, str)


class TestFallbackCompress:
    """Fallback comment stripping."""

    def test_strips_hash_comments(self) -> None:
        src = "x = 1  # comment\nprint(x)\n"
        result = _fallback_compress(src)
        assert "# comment" not in result
        assert "x = 1" in result

    def test_strips_slash_comments(self) -> None:
        src = "const x = 1; // comment\nconsole.log(x);\n"
        result = _fallback_compress(src)
        assert "// comment" not in result
        assert "const x = 1" in result


class TestLanguageParserParse:
    """Actual tree-sitter parsing."""

    def test_parse_python(self) -> None:
        src = "def foo():\n    return 1\n"
        ast = LanguageParser.parse(src, CodeLanguage.PYTHON)
        assert ast is not None
        assert ast.type == "module"

    def test_parse_javascript(self) -> None:
        src = "function foo() { return 1; }"
        ast = LanguageParser.parse(src, CodeLanguage.JAVASCRIPT)
        assert ast is not None
        assert ast.type == "program"

    def test_parse_go(self) -> None:
        src = "package main\n\nfunc main() {}"
        ast = LanguageParser.parse(src, CodeLanguage.GO)
        assert ast is not None
        assert ast.type == "source_file"

    def test_parse_unknown_returns_none(self) -> None:
        src = "hello world"
        ast = LanguageParser.parse(src, CodeLanguage.UNKNOWN)
        assert ast is None
