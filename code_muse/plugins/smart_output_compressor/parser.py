"""Tree-sitter based code parser for smart compression.

Supports Python (primary), with graceful fallback to heuristics
for other languages. Falls back to stdlib ast when tree-sitter
is unavailable.
"""

from __future__ import annotations

import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Language detection from file extension
_EXT_TO_LANG: dict[str, str] = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "tsx": "tsx",
    "go": "go",
    "rs": "rust",
}


def detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return _EXT_TO_LANG.get(ext, "unknown")


def _parse_with_tree_sitter(code: str, language: str) -> list[dict[str, Any]] | None:
    """Parse code with tree-sitter. Returns list of node dicts or None on failure."""
    try:
        if language == "python":
            from tree_sitter_python import language as lang_fn
        elif language in ("javascript", "typescript", "tsx"):
            try:
                from tree_sitter_typescript import language_typescript as lang_fn
            except ImportError:
                return None
        elif language == "go":
            try:
                from tree_sitter_go import language as lang_fn
            except ImportError:
                return None
        else:
            return None

        import tree_sitter as ts

        lang = ts.Language(lang_fn())
        parser = ts.Parser(lang)
        tree = parser.parse(code.encode("utf-8"))
        root = tree.root_node

        nodes: list[dict[str, Any]] = []
        _walk_root_children(root, code.encode("utf-8"), nodes)
        return nodes

    except Exception as exc:
        logger.debug("Tree-sitter parse failed for %s: %s", language, exc)
        return None


def _walk_root_children(
    root: Any, code_bytes: bytes, nodes: list[dict[str, Any]]
) -> None:
    """Walk top-level children of root to extract structural nodes.

    For each top-level node we extract:
    - import_statement / import_from_statement -> kind="import"
    - decorated_definition -> unwrap to get function/class inside
    - function_definition -> kind="function"
    - class_definition -> kind="class", also walk children for methods
    """
    for child in root.children:
        node_type = child.type

        if node_type in ("import_statement", "import_from_statement"):
            _add_import_node(child, code_bytes, nodes)
        elif node_type == "decorated_definition":
            _add_decorated_node(child, code_bytes, nodes)
        elif node_type == "function_definition":
            _add_func_node(child, code_bytes, nodes)
        elif node_type == "class_definition":
            _add_class_node(child, code_bytes, nodes)


def _node_content(node: Any, code_bytes: bytes) -> str:
    """Extract node text, including any trailing newline."""
    end_byte = node.end_byte
    # Tree-sitter end_byte may not include trailing newline
    if end_byte < len(code_bytes) and code_bytes[end_byte : end_byte + 1] == b"\n":
        end_byte += 1
    return code_bytes[node.start_byte : end_byte].decode("utf-8", errors="replace")


def _add_import_node(node: Any, code_bytes: bytes, nodes: list[dict[str, Any]]) -> None:
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = _node_content(node, code_bytes)
    name = _extract_import_name(node, code_bytes)
    nodes.append(
        {
            "start_line": start_line,
            "end_line": end_line,
            "kind": "import",
            "name": name,
            "content": content,
        }
    )


def _extract_import_name(node: Any, code_bytes: bytes) -> str | None:
    """Extract the primary name from an import node."""
    for child in node.children:
        if child.type == "dotted_name":
            return code_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )
        if child.type == "identifier":
            return code_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )
    return None


def _add_decorated_node(
    node: Any, code_bytes: bytes, nodes: list[dict[str, Any]]
) -> None:
    """Handle decorated_definition: extract the inner function/class."""
    # The decorated_definition spans from first decorator to end of body
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = _node_content(node, code_bytes)

    # Find the inner definition
    inner_kind = "function"
    inner_name: str | None = None
    for child in node.children:
        if child.type in ("function_definition", "class_definition"):
            inner_kind = "class" if child.type == "class_definition" else "function"
            inner_name = _extract_identifier(child, code_bytes)
            break

    nodes.append(
        {
            "start_line": start_line,
            "end_line": end_line,
            "kind": inner_kind,
            "name": inner_name,
            "content": content,
        }
    )


def _add_func_node(node: Any, code_bytes: bytes, nodes: list[dict[str, Any]]) -> None:
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = _node_content(node, code_bytes)
    name = _extract_identifier(node, code_bytes)
    nodes.append(
        {
            "start_line": start_line,
            "end_line": end_line,
            "kind": "function",
            "name": name,
            "content": content,
        }
    )


def _add_class_node(node: Any, code_bytes: bytes, nodes: list[dict[str, Any]]) -> None:
    """Add a class node and also add its methods as child nodes."""
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = _node_content(node, code_bytes)
    name = _extract_identifier(node, code_bytes)
    nodes.append(
        {
            "start_line": start_line,
            "end_line": end_line,
            "kind": "class",
            "name": name,
            "content": content,
        }
    )

    # Also add methods as separate nodes so we can score them individually
    for child in node.children:
        if child.type == "block":
            for stmt in child.children:
                if stmt.type == "function_definition":
                    _add_func_node(stmt, code_bytes, nodes)
                elif stmt.type == "decorated_definition":
                    _add_decorated_node(stmt, code_bytes, nodes)


def _extract_identifier(node: Any, code_bytes: bytes) -> str | None:
    """Extract the first identifier child (typically the name)."""
    for child in node.children:
        if child.type == "identifier":
            return code_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )
    return None


# ---------------------------------------------------------------------------
# Fallback: stdlib ast for Python
# ---------------------------------------------------------------------------


def _parse_with_stdlib(code: str) -> list[dict[str, Any]]:
    """Fallback: parse Python with stdlib ast."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    lines = code.splitlines(keepends=True)
    nodes: list[dict[str, Any]] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            names = [alias.name for alias in node.names]
            content = "".join(lines[start - 1 : end])
            nodes.append(
                {
                    "start_line": start,
                    "end_line": end,
                    "kind": "import",
                    "name": names[0] if names else None,
                    "content": content,
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            content = ast.get_source_segment(code, node) or "".join(
                lines[start - 1 : end]
            )
            nodes.append(
                {
                    "start_line": start,
                    "end_line": end,
                    "kind": "function",
                    "name": node.name,
                    "content": content,
                }
            )
        elif isinstance(node, ast.ClassDef):
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            content = ast.get_source_segment(code, node) or "".join(
                lines[start - 1 : end]
            )
            nodes.append(
                {
                    "start_line": start,
                    "end_line": end,
                    "kind": "class",
                    "name": node.name,
                    "content": content,
                }
            )

    return nodes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_file(code: str, file_path: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse source code and return structured nodes.

    Returns (nodes, used_fallback) where used_fallback is True
    if tree-sitter wasn't available or failed.
    """
    language = detect_language(file_path)

    if language == "python":
        # Try tree-sitter first, fall back to stdlib ast
        nodes = _parse_with_tree_sitter(code, language)
        if nodes is not None:
            return nodes, False
        return _parse_with_stdlib(code), True

    # For non-Python, try tree-sitter if grammar available
    nodes = _parse_with_tree_sitter(code, language)
    if nodes is not None:
        return nodes, False

    # Fallback: heuristic section detection
    return [], True
