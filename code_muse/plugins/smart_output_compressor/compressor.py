"""Smart compression: elide low-relevance function bodies while keeping
signatures + imports.

Uses tree-sitter parsed nodes + focus areas to decide what to keep.
"""

from __future__ import annotations

import logging
from typing import Any

from code_muse.plugins.smart_output_compressor.models import (
    CompressedNode,
    CompressedOutput,
)

logger = logging.getLogger(__name__)


def compress_source(
    code: str,
    file_path: str,
    nodes: list[dict[str, Any]],
    used_fallback: bool,
    focus_areas: list[str],
    max_lines: int = 200,
) -> CompressedOutput:
    """Compress source code by keeping imports + relevant signatures + eliding bodies.

    Strategy:
    - Imports: ALWAYS kept
    - Functions/classes: keep signature line + docstring, elide body if low relevance
    - Very relevant functions: keep full body
    - Lines between top-level nodes: kept as structural context
    """
    total_lines = code.count("\n") + (
        1 if code and not code.endswith("\n") else (1 if not code else 0)
    )
    if not code.strip():
        total_lines = 0
    lines = code.splitlines(keepends=True)

    # Score each node
    for node in nodes:
        node["score"] = _score_node(node, focus_areas)

    # Sort by score descending for budget allocation (imports go first since score=1.0)
    scored_nodes = sorted(nodes, key=lambda n: -n.get("score", 0.0))

    # Track which lines are kept
    kept_lines_set: set[int] = set()
    kept_nodes: list[CompressedNode] = []
    line_budget = max_lines

    # Phase 1: Always keep imports
    import_nodes = [n for n in nodes if n.get("kind") == "import"]
    for node in import_nodes:
        node_size = node["end_line"] - node["start_line"] + 1
        for ln in range(node["start_line"], node["end_line"] + 1):
            kept_lines_set.add(ln)
        kept_nodes.append(
            CompressedNode(
                start_line=node["start_line"],
                end_line=node["end_line"],
                kind="import",
                name=node.get("name"),
                score=1.0,
                content=node["content"],
                is_kept=True,
            )
        )

    # Phase 2: Process non-import nodes by score
    remaining_budget = line_budget - len(kept_lines_set)
    non_import = [n for n in scored_nodes if n.get("kind") != "import"]

    # Dedup: skip nodes whose lines are already covered by a class node
    # (methods inside a class are both in the class node and as separate method nodes)
    class_covered_lines: set[int] = set()
    for n in nodes:
        if n.get("kind") == "class":
            for ln in range(n["start_line"], n["end_line"] + 1):
                class_covered_lines.add(ln)

    for node in non_import:
        node_start = node["start_line"]
        node_end = node["end_line"]
        node_size = node_end - node_start + 1
        score = node.get("score", 0.5)

        # Skip method nodes that are fully inside a class node
        # (we'll handle class-level compression instead)
        if (
            node.get("kind") == "function"
            and class_covered_lines
            and all(ln in class_covered_lines for ln in range(node_start, node_end + 1))
        ):
            # Check if the parent class node exists in our list
            parent_class = _find_parent_class(node, nodes)
            if parent_class is not None:
                # Don't double-count; skip the method node
                continue

        if node_size <= 3:
            # Small nodes always kept
            _add_node_full(node, kept_nodes, kept_lines_set)
            remaining_budget -= node_size
        elif score >= 0.7 and remaining_budget >= node_size:
            # High relevance: keep full body
            _add_node_full(node, kept_nodes, kept_lines_set)
            remaining_budget -= node_size
        elif score >= 0.4:
            # Medium relevance: keep signature only (first N lines)
            _add_node_signature(node, lines, kept_nodes, kept_lines_set)
            remaining_budget -= 3  # Approximate: sig + elision marker
        else:
            # Low relevance: elide entirely
            kept_nodes.append(
                CompressedNode(
                    start_line=node_start,
                    end_line=node_end,
                    kind=node.get("kind", "other"),
                    name=node.get("name"),
                    score=score,
                    content=_elision_marker(node),
                    is_kept=False,
                )
            )

    # Assemble output in source order
    kept_nodes.sort(key=lambda n: n.start_line)
    output_lines: list[str] = []
    omitted_count = 0
    prev_end = 0

    for node in kept_nodes:
        # Add gap indicator if there's uncovered space before this node
        if node.start_line > prev_end + 1:
            gap = node.start_line - prev_end - 1
            if gap > 2:
                output_lines.append(f"# ... {gap} lines omitted ...\n")

        if node.is_kept:
            output_lines.append(node.content)
        else:
            output_lines.append(node.content)
            omitted_count += node.end_line - node.start_line + 1

        prev_end = max(prev_end, node.end_line)

    # Trailing omitted lines
    if total_lines > prev_end:
        trailing = total_lines - prev_end
        if trailing > 2:
            output_lines.append(f"\n# ... {trailing} trailing lines omitted\n")

    # Final summary
    if omitted_count > 0:
        output_lines.append(
            f"\n# ── {omitted_count} lines omitted by smart compressor ──\n"
        )

    raw_output = "".join(output_lines)
    kept_count = len(raw_output.splitlines())

    return CompressedOutput(
        file_path=file_path,
        total_lines=total_lines,
        kept_lines=kept_count,
        nodes=kept_nodes,
        language=detect_language(file_path),
        used_fallback=used_fallback,
        raw_output=raw_output,
    )


def _score_node(node: dict[str, Any], focus_areas: list[str]) -> float:
    """Score a node's relevance to given focus areas."""
    if node.get("kind") == "import":
        return 1.0

    if not focus_areas or not node.get("name"):
        return 0.5  # Neutral

    name = node.get("name", "").lower()
    content = node.get("content", "").lower()

    max_score = 0.0
    for area in focus_areas:
        area_lower = area.lower()
        if area_lower in name:
            max_score = max(max_score, 1.0)
        if area_lower in content:
            max_score = max(max_score, 0.7)

    return max(max_score, 0.3)  # Floor at 0.3 for named entities


def _add_node_full(
    node: dict[str, Any],
    kept_nodes: list[CompressedNode],
    kept_lines_set: set[int],
) -> None:
    start, end = node["start_line"], node["end_line"]
    for ln in range(start, end + 1):
        kept_lines_set.add(ln)
    kept_nodes.append(
        CompressedNode(
            start_line=start,
            end_line=end,
            kind=node.get("kind", "other"),
            name=node.get("name"),
            score=node.get("score", 0.5),
            content=node["content"],
            is_kept=True,
        )
    )


def _add_node_signature(
    node: dict[str, Any],
    lines: list[str],
    kept_nodes: list[CompressedNode],
    kept_lines_set: set[int],
) -> None:
    """Keep only the signature lines of a node, elide the body."""
    start, end = node["start_line"], node["end_line"]
    # Signature is typically def/class line + decorators + type hints (up to 4 lines)
    sig_end = min(end, start + 3)
    sig_lines = lines[start - 1 : sig_end]  # lines is 0-indexed
    content = "".join(sig_lines)

    for ln in range(start, sig_end + 1):
        kept_lines_set.add(ln)

    elided = end - sig_end
    elision = f"    # ... body elided ({elided} lines)\n" if elided > 0 else ""

    kept_nodes.append(
        CompressedNode(
            start_line=start,
            end_line=end,
            kind=node.get("kind", "other"),
            name=node.get("name"),
            score=node.get("score", 0.5),
            content=content + elision,
            is_kept=True,
        )
    )


def _elision_marker(node: dict[str, Any]) -> str:
    """Generate an elision marker for a low-relevance node."""
    kind = node.get("kind", "block")
    name = node.get("name", "?")
    size = node["end_line"] - node["start_line"] + 1
    return f"# ... {kind} `{name}` elided ({size} lines)\n"


def _find_parent_class(
    node: dict[str, Any], all_nodes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find a class node that fully contains this node."""
    for n in all_nodes:
        if (
            n.get("kind") == "class"
            and n["start_line"] <= node["start_line"]
            and n["end_line"] >= node["end_line"]
            and n is not node
        ):
            return n
    return None


def detect_language(file_path: str) -> str:
    """Re-export detect_language for compressor's use."""
    from code_muse.plugins.smart_output_compressor.parser import detect_language as _dl

    return _dl(file_path)


def compress_file_lines(
    code: str,
    file_path: str,
    focus_areas: list[str],
    max_lines: int = 200,
) -> CompressedOutput:
    """High-level entry point: parse + compress in one call."""
    from code_muse.plugins.smart_output_compressor.parser import parse_file

    nodes, fallback = parse_file(code, file_path)
    return compress_source(code, file_path, nodes, fallback, focus_areas, max_lines)
