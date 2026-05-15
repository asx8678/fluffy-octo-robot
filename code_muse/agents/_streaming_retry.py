"""Streaming retry helpers for transient LLM API failures.

Provides retry detection and a decorator that wraps an async callable
with automatic back-off on retryable streaming errors.
"""

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

import httpcore
import httpx
from pydantic_ai import UnexpectedModelBehavior

try:  # pragma: no cover - pydantic-ai version dependent
    from pydantic_ai.exceptions import ModelHTTPError
except ImportError:
    ModelHTTPError = None  # type: ignore[misc,assignment]

try:  # pragma: no cover - optional dependency
    from openai import APIError as OpenAIAPIError
except ImportError:
    OpenAIAPIError = None  # type: ignore[assignment]

from code_muse.messaging import emit_error, emit_warning

# Every entry here is either an explicit provider "please retry" signal or an
# SSE framing / transport artifact that reliably succeeds on the next attempt.
# Keep this list substring-based and lower-case.
_RETRYABLE_SNIPPETS = (
    "streamed response ended without content",
    "malformed streamed sse event",
    "extra json data in sse payload",
    "too many requests",
    "rate limit",
    "rate limited",
    "overloaded",
    "service unavailable",
    "server had an error processing your request",
    "retry your request",
    "internal server error",
)

_RETRYABLE_EXCEPTIONS: tuple = (
    httpx.RemoteProtocolError,
    httpx.ReadTimeout,
    httpcore.RemoteProtocolError,
)


def _matches_retryable_snippet(msg: str) -> bool:
    """Return True if ``msg`` matches any known transient pattern.

    Also accepts the generic ``stream ... ended`` wording variants so we don't
    have to chase every phrasing tweak providers sneak in over time.
    """
    msg = msg.lower()
    if any(s in msg for s in _RETRYABLE_SNIPPETS):
        return True
    return "stream" in msg and "ended" in msg


def should_retry_streaming(exc: Exception) -> bool:
    """Decide whether ``exc`` is a transient streaming hiccup worth retrying."""
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True

    msg = str(exc)
    if isinstance(exc, UnexpectedModelBehavior):
        return _matches_retryable_snippet(msg)

    if OpenAIAPIError is not None and isinstance(exc, OpenAIAPIError):
        if _matches_retryable_snippet(msg):
            return True
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            body_msg = str(body.get("message", ""))
            body_type = str(body.get("type", "")).lower()
            if _matches_retryable_snippet(body_msg):
                return True
            if "rate" in body_type and "limit" in body_type:
                return True
            if body_type in {"server_error", "internal_server_error", "api_error"}:
                return _matches_retryable_snippet(body_msg)

    # Retry on pydantic-ai ModelHTTPError rate limits (e.g. 429 from providers)
    if ModelHTTPError is not None and isinstance(exc, ModelHTTPError):
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True
        # Retry on 5xx server errors as well
        if isinstance(status_code, int) and status_code >= 500:
            return True
        if _matches_retryable_snippet(msg):
            return True

    return False


def streaming_retry(
    max_attempts: int = 3,
    delays: Sequence[float] = (1, 2, 4),
) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
    """Wrap a no-arg async callable with streaming-retry semantics."""

    def decorator(factory: Callable[[], Any]) -> Callable[[], Any]:
        async def runner() -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return await factory()
                except Exception as exc:
                    if not should_retry_streaming(exc):
                        raise
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        delay = delays[attempt] if attempt < len(delays) else delays[-1]
                        emit_warning(
                            f"⚡ Streaming interrupted, auto-retrying in {delay}s... "
                            f"(attempt {attempt + 1}/{max_attempts})"
                        )
                        await asyncio.sleep(delay)
                    else:
                        emit_error(f"❌ Streaming failed after {max_attempts} attempts")
            assert last_exc is not None  # loop always sets this before exiting
            raise last_exc

        return runner

    return decorator
