"""SmartCrusher JSON compression engine.

Takes analyzed JSON patterns and produces compact output.
"""

import json
from typing import Any

from code_muse.plugins.filter_engine.strategies.json_patterns import analyze_json
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel


def _format_compact(obj: Any) -> str:
    """Format a value as compact JSON-like string (no unnecessary whitespace).

    Uses an explicit stack instead of recursion to avoid deep-call overhead
    and temporary object churn on nested structures.
    """
    cdef list result
    cdef list stack
    cdef str kind
    cdef object data
    cdef object value
    cdef list items
    cdef object k
    cdef object v
    cdef int i
    cdef str first
    cdef str second

    # Scalar fast-paths — return immediately without stack overhead.
    if isinstance(obj, str):
        return json.dumps(obj)
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return str(obj)
    if obj is None:
        return "null"

    # Iterative walk for containers.
    result = []
    # Stack entries: (kind, data)
    #   "val"   -> data is any value to format
    #   "raw"   -> data is a string to append verbatim
    #   "cdict" -> append "}"
    #   "clist" -> append "]"
    stack = [("val", obj)]

    while stack:
        kind, data = stack.pop()
        if kind == "raw":
            result.append(data)
            continue
        if kind == "cdict":
            result.append("}")
            continue
        if kind == "clist":
            result.append("]")
            continue

        # kind == "val"
        value = data
        if isinstance(value, str):
            result.append(json.dumps(value))
        elif isinstance(value, bool):
            result.append("true" if value else "false")
        elif isinstance(value, (int, float)):
            result.append(str(value))
        elif value is None:
            result.append("null")
        elif isinstance(value, dict):
            if not value:
                result.append("{}")
            else:
                result.append("{")
                stack.append(("cdict", None))
                items = list(value.items())
                for i in range(len(items) - 1, -1, -1):
                    k, v = items[i]
                    stack.append(("val", v))
                    stack.append(("raw", f"{json.dumps(k)}:"))
                    if i > 0:
                        stack.append(("raw", ","))
        elif isinstance(value, list):
            if not value:
                result.append("[]")
            elif len(value) <= 3:
                result.append("[")
                stack.append(("clist", None))
                for i in range(len(value) - 1, -1, -1):
                    stack.append(("val", value[i]))
                    if i > 0:
                        stack.append(("raw", ","))
            else:
                # Long list — inline first two items (still iterative).
                first = _format_compact(value[0])
                second = _format_compact(value[1])
                result.append(f"[{first},{second},...{len(value)}items]")
        else:
            result.append(json.dumps(value))

    return "".join(result)


def compress_json(
    data: Any,
    verbosity: VerbosityLevel | int = VerbosityLevel.COMPACT,
    max_output_chars: int = 4000,
) -> str:
    """Compress JSON data using SmartCrusher.

    Args:
        data: Parsed JSON (dict, list, or scalar).
        verbosity: Compression level. 0 = max, 4 = near-original.
        max_output_chars: Hard output limit.

    Returns:
        Compact JSON string.
    """
    if isinstance(verbosity, int):
        level = verbosity
    else:
        level = verbosity.value if hasattr(verbosity, "value") else 1

    if not isinstance(data, (dict, list)):
        # Scalar — just return it compactly
        return json.dumps(data)

    analysis = analyze_json(data)

    # If it's a homogeneous array with template, use template compression
    if analysis["is_homogeneous"] and analysis["template"] and isinstance(data, list):
        return _compress_homogeneous_array(data, analysis, level, max_output_chars)

    # Otherwise, compact formatting
    if isinstance(data, dict):
        return _compress_dict(data, analysis, level, max_output_chars)
    elif isinstance(data, list):
        return _compress_list(data, analysis, level, max_output_chars)

    return json.dumps(data)


def _compress_homogeneous_array(
    data: list[dict],
    analysis: dict[str, Any],
    level: int,
    max_chars: int,
) -> str:
    """Compress array of same-shape dicts using template notation."""
    template = analysis["template"]
    field_scores = analysis["field_scores"]

    # Select fields based on verbosity
    keep_keys = _select_fields(template, field_scores, level)

    if level == 0:
        # Ultra-compact: template + values array only
        key_order = [k for k in keep_keys if k in template]
        values = []
        for item in data:
            row = [item.get(k) for k in key_order]
            values.append(row)
        template_str = ",".join(key_order)
        compact_values = _format_compact(values)
        result = f"{{@{template_str}}}{compact_values}"
        return result[:max_chars]

    # Level 1+: keep some structure
    if level >= 1:
        compact_items = []
        for item in data:
            kept = {k: item.get(k) for k in keep_keys if k in item}
            compact_items.append(_format_compact(kept))
        inner = ",".join(compact_items[:20])  # limit to 20 items shown
        if len(data) > 20:
            inner += f",...{len(data) - 20}more"
        return f"[{inner}]"[:max_chars]

    return json.dumps(data)[:max_chars]


def _compress_dict(
    data: dict,
    analysis: dict[str, Any],
    level: int,
    max_chars: int,
) -> str:
    """Compress a single dict."""
    field_scores = analysis["field_scores"] or {}
    if not field_scores:
        # Simple case: build field scores from data
        field_scores = {}
        for key in data:
            if key.lower() in ("error", "exception"):
                field_scores[key] = 1.0
            elif key.startswith("_"):
                field_scores[key] = 0.1
            else:
                field_scores[key] = 0.6

    keep_keys = _select_fields(data, field_scores, level)

    if level == 0:
        kept = {k: data[k] for k in keep_keys if k in data}
        if not kept:
            # Fallback: keep all keys but format compactly
            kept = {k: data[k] for k in data}
        return _format_compact(kept)[:max_chars]

    if level >= 1:
        return json.dumps(data)[:max_chars]

    return json.dumps(data)[:max_chars]


def _compress_list(
    data: list,
    analysis: dict[str, Any],
    level: int,
    max_chars: int,
) -> str:
    """Compress a generic list (non-homogeneous)."""
    if level == 0:
        if len(data) <= 5:
            return _format_compact(data)[:max_chars]
        return f"[{len(data)} items]"[:max_chars]
    if level >= 1:
        return json.dumps(data)[:max_chars]
    return json.dumps(data)[:max_chars]


def _select_fields(
    schema: dict[str, Any] | None,
    scores: dict[str, float],
    level: int,
) -> list[str]:
    """Select which fields to keep based on verbosity level and scores.

    Level 0: keep only score >= 0.7 (names, errors)
    Level 1: keep score >= 0.5
    Level 2: keep score >= 0.3
    Level 3: keep score >= 0.1
    Level 4: keep all
    """
    thresholds = {0: 0.7, 1: 0.5, 2: 0.3, 3: 0.1, 4: 0.0}
    threshold = thresholds.get(level, 0.3)

    if not schema:
        return []

    return [k for k, v in scores.items() if v >= threshold]
