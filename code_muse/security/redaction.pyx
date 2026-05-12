# cython: language_level=3
"""Redaction helpers to prevent secret leakage in logs and output."""

import json
import re
import urllib.parse
from typing import Any

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
cdef object _BEARER_HEADER_RE = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+)\S+"
)
cdef object _BEARER_STANDALONE_RE = re.compile(r"(?i)(bearer\s+)\S+")
cdef object _ENV_ASSIGNMENT_RE = re.compile(
    r"(?i)([A-Z_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|AUTH|CREDENTIALS)[A-Z_]*=)(.+?)(?=[\s&]+[A-Z_][A-Z0-9_]+=|$)"
)


cdef bint _is_sensitive_key(str key):
    return key.lower() in SENSITIVE_KEYS


cpdef str _redact_url_query_params(str value):
    cdef object parsed
    cdef dict qs
    cdef bint redacted = False
    cdef str k
    try:
        parsed = urllib.parse.urlparse(value)
        if not parsed.query:
            return value
        qs = urllib.parse.parse_qs(parsed.query)
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


cpdef str _redact_bearer_tokens(str value):
    value = _BEARER_HEADER_RE.sub(r"\1" + REDACTED, value)
    value = _BEARER_STANDALONE_RE.sub(r"\1" + REDACTED, value)
    return value


cpdef str _redact_env_assignments(str value):
    return _ENV_ASSIGNMENT_RE.sub(r"\1" + REDACTED, value)


cpdef str _redact_json_string(str value):
    cdef str stripped = value.strip()
    if not stripped.startswith(("{", "[")):
        return value
    try:
        parsed = json.loads(stripped)
        redacted = redact_secrets(parsed)
        return json.dumps(redacted, separators=(",", ":"))
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
    cdef str s
    cdef dict d
    cdef list lst
    cdef object k, v

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
        d = {}
        for k, v in value.items():
            if _is_sensitive_key(k):
                d[k] = REDACTED
            else:
                d[k] = redact_secrets(v, k)
        return d
    if isinstance(value, list):
        lst = []
        for v in value:
            lst.append(redact_secrets(v, _parent_key))
        return lst
    return value
