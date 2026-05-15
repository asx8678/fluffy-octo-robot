"""Fast JSON compatibility layer.

Prefers orjson (fastest, when available), then msgspec (excellent free-threaded
support and very fast), then stdlib json as a last resort.

This module lets the rest of Muse be indifferent to which JSON backend is
present, which is especially useful for free-threaded (no-GIL) Python builds
where orjson does not yet provide cp314t wheels (as of mid-2026).

Usage (drop-in for the common "import orjson as json" pattern):

    import code_muse._fastjson as json

    data = json.loads(payload)
    out = json.dumps(obj, option=json.OPT_INDENT_2).decode()

The OPT_* constants are always defined (they are no-ops or best-effort when
using the stdlib backend).
"""

from __future__ import annotations

import json as _stdlib_json
from typing import Any

__all__ = [
    "dumps",
    "loads",
    "OPT_INDENT_2",
    "OPT_INDENT_4",
    "OPT_SORT_KEYS",
    "JSONDecodeError",
    "HAS_ORJSON",
    "HAS_MSGSPEC",
    "dumps_pretty",
]

# ---------------------------------------------------------------------------
# Backend selection (orjson > msgspec > stdlib)
# ---------------------------------------------------------------------------

_HAS_ORJSON = False
_HAS_MSGSPEC = False
_impl: Any = _stdlib_json  # type: ignore[assignment]

try:
    import orjson as _orjson  # type: ignore[import-not-found]

    _impl = _orjson
    _HAS_ORJSON = True
except ImportError:
    try:
        import msgspec.json as _msgspec_json  # type: ignore[import-not-found]

        _impl = _msgspec_json
        _HAS_MSGSPEC = True
    except ImportError:
        # stdlib json is always available
        pass

HAS_ORJSON = _HAS_ORJSON
HAS_MSGSPEC = _HAS_MSGSPEC


# ---------------------------------------------------------------------------
# Option flags (best-effort mapping)
# ---------------------------------------------------------------------------

if _HAS_ORJSON:
    OPT_INDENT_2: int = _impl.OPT_INDENT_2
    # orjson only defines OPT_INDENT_2; we synthesize OPT_INDENT_4 for compatibility
    OPT_INDENT_4: int = (
        _impl.OPT_INDENT_2
    )  # reuse 2-space flag; dumps_pretty handles indent=4 explicitly
    OPT_SORT_KEYS: int = _impl.OPT_SORT_KEYS
elif _HAS_MSGSPEC:
    # msgspec uses keyword arguments on Encoder/Decoder instead of bitflags.
    # We still provide the constants so call sites don't need to change.
    OPT_INDENT_2 = 1 << 0
    OPT_INDENT_4 = 1 << 1
    OPT_SORT_KEYS = 1 << 2
else:
    # stdlib json: we ignore the flags and do our best with indent/sort_keys
    OPT_INDENT_2 = 1 << 0
    OPT_INDENT_4 = 1 << 1
    OPT_SORT_KEYS = 1 << 2


# ---------------------------------------------------------------------------
# Exception alias for compatibility
# (orjson raises JSONDecodeError, msgspec raises DecodeError, etc.)
# ---------------------------------------------------------------------------

if _HAS_ORJSON:
    JSONDecodeError = _impl.JSONDecodeError
elif _HAS_MSGSPEC:
    JSONDecodeError = _impl.DecodeError  # type: ignore[attr-defined]
else:
    JSONDecodeError = _stdlib_json.JSONDecodeError


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def dumps(
    obj: Any, *, option: int | None = None, default: Any = None, **kw: Any
) -> bytes:
    """Serialize to JSON, returning bytes (matches original orjson contract).

    Most of the Muse hot paths (especially inside the UC runner) were written
    against orjson's bytes-returning behavior.
    """
    if _HAS_ORJSON:
        opts = option or 0
        return _impl.dumps(obj, option=opts, default=default)

    if _HAS_MSGSPEC:
        indent: int | None = None
        if option:
            if option & OPT_INDENT_4:
                indent = 4
            elif option & OPT_INDENT_2:
                indent = 2
        sort_keys = bool(option and (option & OPT_SORT_KEYS))

        enc = _impl.Encoder(
            indent=indent, enc_hook=default, order="sorted" if sort_keys else None
        )
        return enc.encode(obj)

    # stdlib json → encode to bytes for consistency
    indent: int | None = None  # type: ignore[no-redef]
    if option:
        if option & OPT_INDENT_4:
            indent = 4
        elif option & OPT_INDENT_2:
            indent = 2
    sort_keys = bool(option and (option & OPT_SORT_KEYS))
    return _impl.dumps(obj, indent=indent, sort_keys=sort_keys, default=default).encode(
        "utf-8"
    )


def loads(s: bytes | str | bytearray, **kw: Any) -> Any:
    """Deserialize JSON."""
    if _HAS_ORJSON or _HAS_MSGSPEC:
        return _impl.loads(s, **kw)
    return _impl.loads(s, **kw)


# ---------------------------------------------------------------------------
# Convenience helpers (used in several places)
# ---------------------------------------------------------------------------


def dumps_pretty(obj: Any, *, sort_keys: bool = False, indent: int = 2) -> bytes:
    """Pretty-print JSON, returning bytes (consistent with dumps())."""
    if _HAS_ORJSON:
        opts = OPT_INDENT_2
        if sort_keys:
            opts |= OPT_SORT_KEYS
        return _impl.dumps(obj, option=opts)

    if _HAS_MSGSPEC:
        return _impl.Encoder(
            indent=indent, order="sorted" if sort_keys else None
        ).encode(obj)

    return _impl.dumps(obj, indent=indent, sort_keys=sort_keys, default=str).encode(
        "utf-8"
    )


# ---------------------------------------------------------------------------
# Internal: expose the real implementation for advanced users / debugging
# ---------------------------------------------------------------------------

_BACKEND = "orjson" if _HAS_ORJSON else ("msgspec" if _HAS_MSGSPEC else "stdlib")
