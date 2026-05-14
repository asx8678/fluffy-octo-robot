"""AST-aware code compressors for Python, JavaScript, TypeScript, Go,
Rust, Java, C, C++, Ruby, Bash, and SQL.

Keeps semantic essentials (signatures, imports, error paths), drops
bodies, docstrings, and whitespace.
"""

import bisect
import logging
from typing import Any

from code_muse.plugins.filter_engine.strategies.ast_parser import (
    ASTNode,
    CodeLanguage,
    LanguageParser,
)
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node importance classification
# ---------------------------------------------------------------------------

# Python node types to KEEP (structural/signature)
PYTHON_KEEP_TYPES: set[str] = {
    "function_definition",
    "class_definition",
    "import_statement",
    "import_from_statement",
    "try_statement",
    "except_clause",
    "raise_statement",
    "return_statement",
    "decorated_definition",
    "parameters",
    "lambda",
}

# JavaScript/TypeScript node types to KEEP
JS_KEEP_TYPES: set[str] = {
    "function_declaration",
    "method_definition",
    "class_declaration",
    "export_statement",
    "import_statement",
    "try_statement",
    "catch_clause",
    "throw_statement",
    "return_statement",
    "arrow_function",
    "variable_declarator",
    "lexical_declaration",
    "interface_declaration",
    "type_alias_declaration",
}

# Go node types to KEEP
GO_KEEP_TYPES: set[str] = {
    "function_declaration",
    "method_declaration",
    "type_declaration",
    "import_declaration",
    "return_statement",
    "if_statement",
    "for_statement",
    "call_expression",
}

# Rust node types to KEEP
RUST_KEEP_TYPES: set[str] = {
    "function_item",
    "impl_item",
    "struct_item",
    "enum_item",
    "trait_item",
    "use_declaration",
    "let_declaration",
    "return_expression",
}

# Java node types to KEEP
JAVA_KEEP_TYPES: set[str] = {
    "method_declaration",
    "class_declaration",
    "interface_declaration",
    "import_declaration",
    "package_declaration",
    "constructor_declaration",
    "return_statement",
    "throw_statement",
    "try_statement",
    "catch_clause",
}

# C/C++ node types to KEEP (shared for C and C++)
CPP_KEEP_TYPES: set[str] = {
    "function_definition",
    "class_specifier",
    "struct_specifier",
    "declaration",
    "preproc_include",
    "preproc_define",
    "return_statement",
    "namespace_definition",
    "template_declaration",
}

# Ruby node types to KEEP
RUBY_KEEP_TYPES: set[str] = {
    "method",
    "singleton_method",
    "class_definition",
    "module_definition",
    "require_call",
    "return",
}


# ---------------------------------------------------------------------------
# Line-collection helpers
# ---------------------------------------------------------------------------


def _build_line_map(source: str) -> list[int]:
    """Return a list of byte offsets for the start of every line."""
    offsets = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def _byte_to_line(byte_offset: int, line_map: list[int]) -> int:
    """Return the 0-based line number for a given byte offset."""
    return bisect.bisect_right(line_map, byte_offset) - 1


cdef int _byte_to_line_c(int byte_offset, list line_map):
    """Cython-typed binary search — logic identical to _byte_to_line."""
    cdef int lo = 0
    cdef int hi = len(line_map)
    cdef int mid
    while lo < hi:
        mid = (lo + hi) // 2
        if line_map[mid] <= byte_offset:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def _walk_cython(
    object node,
    int depth,
    object keep_types,
    int level,
    list lines,
    set kept_lines,
    list line_map,
    object extra_handler,
):
    """Cython-typed AST walker — logic identical to the pure-Python _walk."""
    cdef str node_type
    cdef int start_line
    cdef int end_line
    cdef int i
    cdef int j
    cdef int n_lines = len(lines)

    node_type = node.type
    start_line = _byte_to_line_c(node.start_byte, line_map)
    end_line = _byte_to_line_c(node.end_byte, line_map)

    if node_type in keep_types:
        for i in range(start_line, min(end_line + 1, n_lines)):
            if node_type == "function_definition" and i == start_line:
                kept_lines.add(i)
                if level >= 3:
                    for j in range(start_line + 1, min(start_line + 4, n_lines)):
                        kept_lines.add(j)
                elif level >= 1:
                    kept_lines.add(start_line + 1)
                break
            elif node_type in ("class_definition", "decorated_definition"):
                kept_lines.add(i)
                if level >= 2:
                    for j in range(start_line + 1, min(start_line + 3, n_lines)):
                        kept_lines.add(j)
                break
            elif (
                node_type in ("import_statement", "import_from_statement")
                or node_type == "try_statement"
                or node_type == "except_clause"
                or node_type == "raise_statement"
                or node_type == "return_statement"
            ):
                kept_lines.add(i)
            else:
                kept_lines.add(i)
                break

    if extra_handler is not None:
        extra_handler(node, start_line, end_line, kept_lines, lines, level)

    for child in node.children:
        _walk_cython(child, depth + 1, keep_types, level, lines, kept_lines, line_map, extra_handler)


def _collect_lines(
    source: str,
    ast: ASTNode,
    keep_types: set[str],
    level: int,
    extra_handler: Any | None = None,
) -> set[int]:
    """Walk an AST and collect line numbers to keep."""
    lines = source.split("\n")
    kept_lines: set[int] = set()
    line_map = _build_line_map(source)

    _walk_cython(ast, 0, keep_types, level, lines, kept_lines, line_map, extra_handler)
    return kept_lines


def _build_output(source: str, kept_lines: set[int], comment_prefix: str = "#") -> str:
    """Build compressed output from kept line numbers."""
    lines = source.split("\n")
    if not kept_lines:
        return source[:200] + "..." if len(source) > 200 else source

    result_lines: list[str] = []
    last_kept = -1
    for i in sorted(kept_lines):
        if i >= len(lines):
            continue
        if last_kept >= 0 and i > last_kept + 1:
            gap = i - last_kept - 1
            result_lines.append(f"{comment_prefix} ... {gap} lines omitted ...")
        result_lines.append(lines[i])
        last_kept = i

    if last_kept < len(lines) - 1:
        remaining = len(lines) - 1 - last_kept
        if remaining > 1:
            result_lines.append(f"{comment_prefix} ... {remaining} lines omitted ...")
        elif remaining == 1:
            result_lines.append(lines[-1])

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Compressors
# ---------------------------------------------------------------------------


def compress_python(
    source: str, verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT
) -> str:
    """Compress Python source code — keep signatures, drop bodies.

    Args:
        source: Python source code string.
        verbosity: 0 = signatures only, 4 = keep brief bodies.

    Returns:
        Compressed Python code.
    """
    level = verbosity.value if isinstance(verbosity, VerbosityLevel) else verbosity

    ast = LanguageParser.parse(source, CodeLanguage.PYTHON)
    if ast is None:
        return _fallback_compress(source)

    kept_lines = _collect_lines(source, ast, PYTHON_KEEP_TYPES, level)
    return _build_output(source, kept_lines, comment_prefix="#")


def compress_javascript(
    source: str,
    language: CodeLanguage | None = None,
    verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT,
) -> str:
    """Compress JavaScript/TypeScript — keep signatures, drop bodies."""
    level = verbosity.value if isinstance(verbosity, VerbosityLevel) else verbosity

    if language is None:
        language = CodeLanguage.JAVASCRIPT
    ast = LanguageParser.parse(source, language)
    if ast is None:
        return _fallback_compress(source)

    kept_lines = _collect_lines(source, ast, JS_KEEP_TYPES, level)
    return _build_output(source, kept_lines, comment_prefix="//")


def compress_go(
    source: str, verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT
) -> str:
    """Compress Go source — keep func/method/type signatures, drop bodies."""
    level = verbosity.value if isinstance(verbosity, VerbosityLevel) else verbosity

    ast = LanguageParser.parse(source, CodeLanguage.GO)
    if ast is None:
        return _fallback_compress(source)

    kept_lines: set[int] = set()

    def _extra_handler(
        node: ASTNode,
        start_line: int,
        end_line: int,
        kept: set[int],
        lines: list[str],
        level: int,
    ) -> None:
        if node.type in ("function_declaration", "method_declaration"):
            for i in range(start_line, min(start_line + 2, len(lines))):
                kept.add(i)
            for i in range(start_line, min(end_line + 1, len(lines))):
                if "{" in lines[i]:
                    kept.add(i)
                    break
        if level >= 3:
            for j in range(start_line + 1, min(start_line + 4, len(lines))):
                kept.add(j)

    kept_lines = _collect_lines(
        source, ast, GO_KEEP_TYPES, level, extra_handler=_extra_handler
    )
    return _build_output(source, kept_lines, comment_prefix="//")


def compress_rust(
    source: str, verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT
) -> str:
    """Compress Rust source — keep fn/struct/enum/impl/trait signatures, drop bodies."""
    level = verbosity.value if isinstance(verbosity, VerbosityLevel) else verbosity

    ast = LanguageParser.parse(source, CodeLanguage.RUST)
    if ast is None:
        return _fallback_compress(source)

    kept_lines = _collect_lines(source, ast, RUST_KEEP_TYPES, level)
    return _build_output(source, kept_lines, comment_prefix="//")


def compress_java(
    source: str, verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT
) -> str:
    """Compress Java source — keep method/class/interface signatures, drop bodies."""
    level = verbosity.value if isinstance(verbosity, VerbosityLevel) else verbosity

    ast = LanguageParser.parse(source, CodeLanguage.JAVA)
    if ast is None:
        return _fallback_compress(source)

    kept_lines = _collect_lines(source, ast, JAVA_KEEP_TYPES, level)
    return _build_output(source, kept_lines, comment_prefix="//")


def compress_c_cpp(
    source: str, language: CodeLanguage | None = None, verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT
) -> str:
    """Compress C/C++ source — keep function/struct/class signatures, drop bodies."""
    level = verbosity.value if isinstance(verbosity, VerbosityLevel) else verbosity
    if language is None:
        language = CodeLanguage.CPP

    ast = LanguageParser.parse(source, language)
    if ast is None:
        return _fallback_compress(source)

    kept_lines = _collect_lines(source, ast, CPP_KEEP_TYPES, level)
    return _build_output(source, kept_lines, comment_prefix="//")


def compress_ruby(
    source: str, verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT
) -> str:
    """Compress Ruby source — keep method/class/module signatures, drop bodies."""
    level = verbosity.value if isinstance(verbosity, VerbosityLevel) else verbosity

    ast = LanguageParser.parse(source, CodeLanguage.RUBY)
    if ast is None:
        return _fallback_compress(source)

    kept_lines = _collect_lines(source, ast, RUBY_KEEP_TYPES, level)
    return _build_output(source, kept_lines, comment_prefix="#")


def _fallback_compress(source: str) -> str:
    """Fallback: strip comments when AST parsing fails."""
    lines = source.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        if "#" in line and not line.startswith("#"):
            line = line[: line.index("#")].rstrip()
        if "//" in line and not line.startswith("//"):
            line = line[: line.index("//")].rstrip()
        result.append(line)
    return "\n".join(result)


def compress_ast_code(
    source: str,
    language: CodeLanguage | None = None,
    verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT,
    filename: str | None = None,
) -> str:
    """Compress source code using the appropriate language compressor.

    Args:
        source: Source code string.
        language: Optional pre-detected language.
        verbosity: Compression level.
        filename: Optional filename for language detection.

    Returns:
        Compressed source code.
    """
    if language is None and filename:
        language = LanguageParser.detect_language(source, filename)
    elif language is None:
        language = LanguageParser.detect_language(source)

    compressors = {
        CodeLanguage.PYTHON: compress_python,
        CodeLanguage.JAVASCRIPT: compress_javascript,
        CodeLanguage.TYPESCRIPT: compress_javascript,
        CodeLanguage.GO: compress_go,
        CodeLanguage.RUST: compress_rust,
        CodeLanguage.JAVA: compress_java,
        CodeLanguage.C: compress_c_cpp,
        CodeLanguage.CPP: compress_c_cpp,
        CodeLanguage.RUBY: compress_ruby,
    }

    compressor = compressors.get(language)
    if compressor:
        # Pass the detected language to compressors that accept it;
        # this avoids redundant re-detection inside the compressor.
        if language in (CodeLanguage.JAVASCRIPT, CodeLanguage.TYPESCRIPT):
            return compress_javascript(source, language=language, verbosity=verbosity)
        if language in (CodeLanguage.C, CodeLanguage.CPP):
            return compress_c_cpp(source, language=language, verbosity=verbosity)
        return compressor(source, verbosity)

    return _fallback_compress(source)
