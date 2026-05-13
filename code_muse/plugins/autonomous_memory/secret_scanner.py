"""Secret scanner for the Autonomous Memory Pipeline.

Detects common secret patterns in extracted memory text before it is
written to disk, helping prevent accidental credential leakage.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SCAN_PATTERNS: list[tuple[str, str]] = [
    ("aws_access_key", r"AKIA[0-9A-Z]{16}"),
    ("github_token", r"ghp_[0-9a-zA-Z]{36}"),
    ("openai_api_key", r"sk-(?:proj-)?[0-9a-zA-Z]{20,}"),
    (
        "private_key_header",
        r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----",
    ),
    (
        "jwt_token",
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    ),
    (
        "generic_api_key",
        r"(api[_-]?key|apikey|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9+/=]{20,}['\"]?",
    ),
]


@dataclass
class SecretMatch:
    """A single secret pattern match."""

    pattern_name: str
    line_number: int
    context: str


def scan_for_secrets(text: str) -> list[SecretMatch]:
    """Scan ``text`` for known secret patterns.

    Returns a list of :class:`SecretMatch` objects with line numbers and
    a short context snippet (first 40 characters of the match).
    """
    matches: list[SecretMatch] = []
    lines = text.splitlines()

    for pattern_name, pattern in SCAN_PATTERNS:
        for line_idx, line in enumerate(lines, start=1):
            for match in re.finditer(pattern, line, re.IGNORECASE):
                context = match.group(0)[:40]
                matches.append(
                    SecretMatch(
                        pattern_name=pattern_name,
                        line_number=line_idx,
                        context=context,
                    )
                )

    return matches
