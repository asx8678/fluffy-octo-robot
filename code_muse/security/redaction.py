"""Redaction helpers to prevent secret leakage in logs and output.

Pure-Python implementation. Replaces the previous Cython-compiled
redaction module so ``code-muse`` can ship as a ``py3-none-any`` wheel.
The public API (``redact_secrets``, ``SENSITIVE_KEYS``, ``REDACTED``) is
unchanged.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

import orjson as json

# Keys whose values should always be redacted in structured data.
SENSITIVE_KEYS: frozenset = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "code",
        "code_verifier",
        "code_challenge",
        "client_secret",
        "client_id",
        "password",
        "token",
        "secret",
        "authorization",
        "bearer",
        "apikey",
        "auth_token",
        "session_token",
        "csrf_token",
    }
)

REDACTED = "<redacted>"

# Pre-compiled regex patterns for performance.
_BEARER_HEADER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)\S+")
_BEARER_STANDALONE_RE = re.compile(r"(?i)(bearer\s+)\S+")
_ENV_ASSIGNMENT_RE = re.compile(
    r"(?i)([A-Z_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|AUTH|CREDENTIALS)[A-Z_]*=)(.+?)(?=[\s&]+[A-Z_][A-Z0-9_]+=|$)"
)


def _is_sensitive_key(key: str) -> bool:
    return key.lower() in SENSITIVE_KEYS


def _redact_url_query_params(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(value)
        if not parsed.query:
            return value
        qs = urllib.parse.parse_qs(parsed.query)
        redacted = False
        for k in list(qs):
            if _is_sensitive_key(k):
                qs[k] = [REDACTED]
                redacted = True
        if redacted:
            new_query = urllib.parse.urlencode(qs, doseq=True)
            return urllib.parse.urlunparse(parsed._replace(query=new_query))
    except Exception:
        pass
    return value


def _redact_bearer_tokens(value: str) -> str:
    value = _BEARER_HEADER_RE.sub(r"\1" + REDACTED, value)
    value = _BEARER_STANDALONE_RE.sub(r"\1" + REDACTED, value)
    return value


def _redact_env_assignments(value: str) -> str:
    return _ENV_ASSIGNMENT_RE.sub(r"\1" + REDACTED, value)


def _redact_json_string(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith(("{", "[")):
        return value
    try:
        parsed = json.loads(stripped)
        redacted = redact_secrets(parsed)
        return json.dumps(redacted).decode()
    except Exception:
        return value


def redact_secrets(value: Any, _parent_key: str = "") -> Any:
    """Recursively redact secrets from strings, dicts, and lists.

    Covers:
    - URL query parameters containing sensitive keys
    - JSON/dict keys matching known sensitive names
    - ``Authorization: Bearer ...`` headers
    - OAuth response bodies (via recursive dict redaction)
    - Environment-variable-style assignments of sensitive names

    Returns deterministic ``<redacted>`` output; never logs token length.
    """
    if isinstance(value, bytes):
        try:
            return redact_secrets(value.decode("utf-8"))
        except UnicodeDecodeError:
            return REDACTED.encode("utf-8")
    if isinstance(value, str):
        s = value
        s = _redact_bearer_tokens(s)
        s = _redact_url_query_params(s)
        s = _redact_env_assignments(s)
        s = _redact_json_string(s)
        return s
    if isinstance(value, dict):
        d: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_sensitive_key(k):
                d[k] = REDACTED
            else:
                d[k] = redact_secrets(v, k if isinstance(k, str) else "")
        return d
    if isinstance(value, list):
        return [redact_secrets(v, _parent_key) for v in value]
    return value
