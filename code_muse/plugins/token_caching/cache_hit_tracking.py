"""Track Anthropic cache usage from API responses."""

import threading
from dataclasses import dataclass, field


@dataclass
class CacheUsage:
    """Per-turn cache and token usage from an Anthropic API response."""

    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class SessionCacheStats:
    """Thread-safe accumulator for cache usage across a session."""

    # FREE-THREADED: Sync-only stats accumulator; keep threading.Lock.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _total_read_tokens: int = 0
    _total_write_tokens: int = 0
    _total_input_tokens: int = 0
    _total_output_tokens: int = 0

    def record_usage(self, usage: CacheUsage) -> None:
        """Accumulate a single turn's usage."""
        with self._lock:
            self._total_read_tokens += usage.cache_read_tokens
            self._total_write_tokens += usage.cache_write_tokens
            self._total_input_tokens += usage.input_tokens
            self._total_output_tokens += usage.output_tokens

    @property
    def total_read_tokens(self) -> int:
        with self._lock:
            return self._total_read_tokens

    @property
    def total_write_tokens(self) -> int:
        with self._lock:
            return self._total_write_tokens

    @property
    def total_input_tokens(self) -> int:
        with self._lock:
            return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        with self._lock:
            return self._total_output_tokens

    @property
    def hit_rate(self) -> float:
        """Cache hit rate: read tokens / (read tokens + input tokens)."""
        with self._lock:
            denominator = self._total_read_tokens + self._total_input_tokens
            if denominator == 0:
                return 0.0
            return self._total_read_tokens / denominator

    @property
    def estimated_savings_usd(self) -> float:
        """Estimated cost savings from token caching.

        Anthropic pricing (Claude 3.5 Sonnet base):
        - $3 / M input tokens  → base price per token = 3 / 1_000_000
        - Cache read  = 0.1 × base
        - Cache write = 1.25 × base

        Savings = (read_tokens × 0.1 × base) - (write_tokens × 1.25 × base)
        """
        with self._lock:
            base_price_per_token = 3.0 / 1_000_000.0
            savings = (self._total_read_tokens * 0.1 * base_price_per_token) - (
                self._total_write_tokens * 1.25 * base_price_per_token
            )
            return max(0.0, savings)

    def reset(self) -> None:
        """Clear all accumulated counters."""
        with self._lock:
            self._total_read_tokens = 0
            self._total_write_tokens = 0
            self._total_input_tokens = 0
            self._total_output_tokens = 0


def extract_cache_usage(response: dict) -> CacheUsage | None:
    """Parse Anthropic API response dict for cache usage fields.

    Looks for:
    - ``usage.cache_read_input_tokens``
    - ``usage.cache_creation_input_tokens``
    - ``usage.input_tokens``
    - ``usage.output_tokens``

    Returns ``None`` if the response has no ``usage`` block.
    Missing fields default to 0.
    """
    if not isinstance(response, dict):
        return None

    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None

    return CacheUsage(
        cache_read_tokens=_int_or_zero(usage.get("cache_read_input_tokens")),
        cache_write_tokens=_int_or_zero(usage.get("cache_creation_input_tokens")),
        input_tokens=_int_or_zero(usage.get("input_tokens")),
        output_tokens=_int_or_zero(usage.get("output_tokens")),
    )


def _int_or_zero(value: object) -> int:
    """Coerce a value to int, defaulting to 0 on failure."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


# Global singleton for the current session
_session_stats: SessionCacheStats = SessionCacheStats()
