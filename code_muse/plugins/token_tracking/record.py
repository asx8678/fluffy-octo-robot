"""Record command execution metrics to the tracking database.

Simple, self-contained utility — never raises, never blocks.
"""

import logging

from code_muse.config import get_current_autosave_id
from code_muse.plugins.token_tracking.database import get_tracking_db

logger = logging.getLogger(__name__)


def _count_tokens(text: str) -> int:
    """Count whitespace-delimited tokens in text.

    Simple heuristic — no tiktoken dependency. For empty text returns 0.
    """
    return len(text.split()) if text else 0


def record_command(
    command: str,
    raw_stdout: str,
    raw_stderr: str,
    compressed_stdout: str,
    compressed_stderr: str,
    category: str,
    strategy: str,
    exit_code: int = 0,
    duration_ms: float = 0.0,
) -> None:
    """Insert a tracking record. Never raises — logs and returns on error."""
    try:
        raw_tokens = _count_tokens(f"{raw_stdout}\n{raw_stderr}")
        compressed_tokens = _count_tokens(f"{compressed_stdout}\n{compressed_stderr}")

        if raw_tokens == 0:
            savings_pct = 0.0
        else:
            savings_pct = (raw_tokens - compressed_tokens) / raw_tokens * 100

        get_tracking_db().insert(
            command=command,
            category=category,
            strategy=strategy,
            raw_tokens=raw_tokens,
            compressed_tokens=compressed_tokens,
            savings_pct=savings_pct,
            session_id=get_current_autosave_id(),
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
    except Exception:
        logger.debug("record_command failed", exc_info=True)
