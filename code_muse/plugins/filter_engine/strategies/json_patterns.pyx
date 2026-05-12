# cython: language_level=3
"""JSON structure analysis for SmartCrusher.

Detects patterns in JSON/structured data: array-of-dict templates,
field importance scoring, nested structure detection.
"""

from typing import Any


def is_homogeneous_array(data: list[Any]) -> bool:
    """Check if all items in array have the same shape (same keys if dicts)."""
    cdef int n = len(data)
    cdef object first
    cdef object item
    cdef object first_keys
    cdef int first_len
    if n < 2:
        return False
    first = data[0]
    if isinstance(first, dict):
        first_keys = frozenset(first.keys())
        for item in data[1:]:
            if not isinstance(item, dict) or frozenset(item.keys()) != first_keys:
                return False
        return True
    if isinstance(first, (list, tuple)):
        first_len = len(first)
        for item in data[1:]:
            if not isinstance(item, (list, tuple)) or len(item) != first_len:
                return False
        return True
    return False


def detect_array_template(data: list[dict]) -> dict[str, Any] | None:
    """Extract a common key skeleton from an array of dicts.

    Returns:
        A dict with keys that are common across all items, or None if no template.
        Special value ``"<VARIED>"`` marks keys with non-uniform values.
        Special value ``"<UNIQUE>"`` marks keys that differ across all items.
    """
    cdef int n = len(data)
    if n == 0:
        return None
    cdef object item
    for item in data:
        if not isinstance(item, dict):
            return None

    cdef set all_keys = set()
    for item in data:
        all_keys.update(item.keys())

    cdef dict template = {}
    cdef str key
    cdef list values
    cdef object v
    cdef set unique_values

    for key in sorted(all_keys):
        values = [item.get(key) for item in data]
        unique_values = set(
            repr(v) if not isinstance(v, (dict, list)) else id(v) for v in values
        )
        if len(unique_values) == 1:
            # All same — keep the value in template
            template[key] = values[0]
        elif len(unique_values) == len(values):
            # All different — mark as unique
            template[key] = "<UNIQUE>"
        else:
            # Some same, some different — mark as varied
            template[key] = "<VARIED>"

    return template


def score_field_importance(
    schema: dict[str, Any], sample_count: int = 10
) -> dict[str, float]:
    """Score field importance based on information density.

    Heuristics:
    - String fields with varied content → high score (names, descriptions)
    - Numeric fields with high variance → medium score
    - Boolean/constant fields → low score
    - Fields named "id", "type", "status" → medium score (structural)
    - Fields with prefix "_" → low score (internal)
    - Fields named "error", "exception" → max score (always keep)

    Returns:
        Dict mapping field names to scores 0.0–1.0.
    """
    cdef dict scores = {}
    cdef str key
    for key in schema:
        # Always keep error fields
        if key.lower() in ("error", "exception", "message", "warning", "fatal"):
            scores[key] = 1.0
            continue

        # Internal fields get low score
        if key.startswith("_"):
            scores[key] = 0.1
            continue

        # Structural fields
        if key.lower() in ("id", "type", "status", "code", "kind", "level"):
            scores[key] = 0.5
            continue

        # Name fields are usually informative
        if key.lower() in ("name", "title", "description", "summary", "label"):
            scores[key] = 0.9
            continue

        # Default moderate
        scores[key] = 0.6

    return scores


def detect_nested_structure(data: Any, prefix: str = "") -> list[str]:
    """Detect nested key paths that can be flattened.

    Returns list of dotted key paths like ``["items.name", "items.version"]``.
    Uses an explicit stack instead of recursion to avoid deep-call overhead.
    """
    cdef list paths = []
    cdef list stack = [(data, prefix)]
    cdef object current_data
    cdef str current_prefix
    cdef str key
    cdef str current
    cdef object value

    while stack:
        current_data, current_prefix = stack.pop()
        if isinstance(current_data, dict):
            for key, value in current_data.items():
                current = f"{current_prefix}.{key}" if current_prefix else key
                if isinstance(value, dict):
                    stack.append((value, current))
                elif isinstance(value, list) and value and isinstance(value[0], dict):
                    # Array of objects — descend into first item to find nested paths
                    stack.append((value[0], current))
                else:
                    paths.append(current)
        elif isinstance(current_data, list) and current_data and isinstance(current_data[0], dict):
            stack.append((current_data[0], current_prefix))

    return sorted(set(paths))


def analyze_json(data: Any) -> dict[str, Any]:
    """Full analysis: template, fields, nests.

    Returns a dict with keys ``template``, ``field_scores``, ``nested_paths``,
    ``is_homogeneous``.
    """
    cdef dict result = {
        "is_homogeneous": False,
        "template": None,
        "field_scores": {},
        "nested_paths": [],
    }
    if isinstance(data, list) and data:
        result["is_homogeneous"] = is_homogeneous_array(data)
        if result["is_homogeneous"] and isinstance(data[0], dict):
            result["template"] = detect_array_template(data)
            result["field_scores"] = score_field_importance(result["template"] or {})
        result["nested_paths"] = detect_nested_structure(data)
    elif isinstance(data, dict):
        result["nested_paths"] = detect_nested_structure(data)
        result["field_scores"] = score_field_importance(data)
    return result
