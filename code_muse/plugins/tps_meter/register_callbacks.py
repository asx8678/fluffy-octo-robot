"""TPS Meter — live tokens-per-second display in the Muse prompt bottom toolbar.

Port of the oc-tps OpenCode plugin concept to Muse's Python callback system.
Tracks streaming token deltas and timing via the stream_event hook, then
exposes formatted TPS/AVG/TTFT text for the prompt_toolkit bottom toolbar.
"""

import math
import time
from typing import Any

from code_muse.callbacks import register_callback

# ---------------------------------------------------------------------------
# Constants (mirrors oc-tps)
# ---------------------------------------------------------------------------
_STREAM_WINDOW_MS = 5_000  # sliding window for live TPS
_LIVE_STALE_MS = 1_500  # mark live TPS stale after this silence
_SINGLE_SAMPLE_MS = 1_000  # minimum duration for a single sample

# ---------------------------------------------------------------------------
# Shared state — read by the prompt_toolkit bottom toolbar
# ---------------------------------------------------------------------------


class _TpsState:
    """Thread-safe shared state between stream_event callbacks and toolbar render."""

    def __init__(self) -> None:
        self._lock = __import__("threading").Lock()
        # Sliding-window samples: list of (timestamp_ms, token_count)
        self._samples: list[tuple[float, int]] = []
        # Session totals
        self._total_tokens: int = 0
        self._total_duration_ms: float = 0.0
        self._total_ttft_ms: float = 0.0
        self._message_count: int = 0
        # Per-message timing
        self._request_start: float | None = None
        self._first_response: float | None = None
        self._first_token: float | None = None
        self._last_token: float | None = None
        self._last_tool_call: float | None = None
        # Is the agent currently streaming?
        self._is_streaming: bool = False

    # ------------------------------------------------------------------
    # Called by stream_event callback
    # ------------------------------------------------------------------

    def on_run_start(self) -> None:
        with self._lock:
            self._is_streaming = True
            self._request_start = time.time() * 1000
            self._first_response = None
            self._first_token = None
            self._last_token = None
            self._last_tool_call = None

    def on_run_end(self) -> None:
        with self._lock:
            self._is_streaming = False
            # Finalize current message stats
            self._finalize_message()

    def on_part_delta(self, delta_text: str, now_ms: float | None = None) -> None:
        """Record a text delta from streaming."""
        if now_ms is None:
            now_ms = time.time() * 1000
        tokens = max(1, math.ceil(len(delta_text) / 5))  # ~5 chars/token heuristic

        with self._lock:
            # Mark first response / first token
            if self._first_response is None:
                self._first_response = now_ms
            if self._first_token is None:
                self._first_token = now_ms
            self._last_token = now_ms

            # Append to sliding window, prune old samples
            self._samples.append((now_ms, tokens))
            cutoff = now_ms - _STREAM_WINDOW_MS
            self._samples = [(ts, c) for ts, c in self._samples if ts >= cutoff]

    def on_tool_call_start(self, now_ms: float | None = None) -> None:
        """Mark first response on first tool call start."""
        if now_ms is None:
            now_ms = time.time() * 1000
        with self._lock:
            if self._first_response is None:
                self._first_response = now_ms

    def on_tool_call_end(self, now_ms: float | None = None) -> None:
        """Record tool call end time."""
        if now_ms is None:
            now_ms = time.time() * 1000
        with self._lock:
            self._last_tool_call = now_ms

    def on_message_complete(
        self, total_tokens: int | None = None, finish_reason: str | None = None
    ) -> None:
        """Finalize a completed message and update session averages."""
        with self._lock:
            if self._first_response is not None and self._request_start is not None:
                end_at: float | None
                if finish_reason == "tool-calls" and self._last_tool_call is not None:
                    end_at = self._last_tool_call
                else:
                    end_at = self._last_token or time.time() * 1000

                duration_ms = max(end_at - self._first_response, 1.0)
                ttft_ms = max(self._first_response - self._request_start, 0.0)

                if total_tokens is not None:
                    self._total_tokens += total_tokens
                else:
                    # Estimate from samples
                    self._total_tokens += sum(c for _, c in self._samples)
                self._total_duration_ms += duration_ms
                self._total_ttft_ms += ttft_ms
                self._message_count += 1

            # Reset per-message state
            self._request_start = None
            self._first_response = None
            self._first_token = None
            self._last_token = None
            self._last_tool_call = None

    def _finalize_message(self) -> None:
        """Internal finalize — called on run_end if message wasn't finalized."""
        if self._first_response is not None and self._request_start is not None:
            end_at = self._last_token or time.time() * 1000
            duration_ms = max(end_at - self._first_response, 1.0)
            ttft_ms = max(self._first_response - self._request_start, 0.0)
            total = sum(c for _, c in self._samples)
            self._total_tokens += total
            self._total_duration_ms += duration_ms
            self._total_ttft_ms += ttft_ms
            self._message_count += 1

    # ------------------------------------------------------------------
    # Read by toolbar
    # ------------------------------------------------------------------

    def get_toolbar_text(self) -> str:
        """Return formatted toolbar text: TPS xx | AVG xx | TTFT xx"""
        with self._lock:
            live = self._get_live_tps()
            avg = self._get_avg_tps()
            ttft = self._get_avg_ttft()

        parts = []
        if live is not None:
            parts.append(f"TPS {live}")
        if avg is not None:
            parts.append(f"AVG {avg}")
        if ttft is not None:
            parts.append(f"TTFT {ttft}")

        return " | ".join(parts) if parts else ""

    def _get_live_tps(self) -> str | None:
        """Compute live TPS from sliding window."""
        if not self._is_streaming or not self._samples:
            return None
        now = time.time() * 1000
        cutoff = now - _STREAM_WINDOW_MS
        relevant = [(ts, c) for ts, c in self._samples if ts >= cutoff]
        if not relevant:
            return None
        last_ts = relevant[-1][0]
        if now - last_ts > _LIVE_STALE_MS:
            return None
        total = sum(c for _, c in relevant)
        if len(relevant) == 1:
            duration = max(min(now - relevant[0][0], _SINGLE_SAMPLE_MS), 250)
        else:
            duration = relevant[-1][0] - relevant[0][0]
            if now > last_ts:
                duration += now - last_ts
            duration = max(duration, _SINGLE_SAMPLE_MS)
        tps = total / (duration / 1000)
        return self._format_rate(tps)

    def _get_avg_tps(self) -> str | None:
        """Compute session-wide average TPS."""
        if self._total_tokens <= 0 or self._total_duration_ms <= 0:
            return None
        avg = self._total_tokens / (self._total_duration_ms / 1000)
        return self._format_rate(avg)

    def _get_avg_ttft(self) -> str | None:
        """Compute average TTFT across all messages."""
        if self._message_count <= 0 or self._total_ttft_ms < 0:
            return None
        avg_ms = self._total_ttft_ms / self._message_count
        avg_s = avg_ms / 1000
        return f"{avg_s:.1f}s"

    @staticmethod
    def _format_rate(value: float) -> str | None:
        """Format a TPS value similar to oc-tps."""
        if not math.isfinite(value) or value <= 0:
            return None
        if value >= 100:
            return f"{round(value)}"
        if value >= 10:
            return f"{value:.1f}"
        return f"{value:.2f}"


# ---------------------------------------------------------------------------
# Singleton state instance
# ---------------------------------------------------------------------------
_tps_state = _TpsState()


def get_tps_state() -> _TpsState:
    """Return the shared TPS state singleton (for toolbar integration)."""
    return _tps_state


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def _on_stream_event(
    event_type: str, event_data: Any, agent_session_id: str | None = None
) -> None:
    """React to streaming events — track tokens and timing."""
    if event_type == "part_delta":
        delta = event_data.get("delta", object())
        delta_type = event_data.get("delta_type", "")
        if delta_type in ("TextPartDelta", "ThinkingPartDelta"):
            content_delta = getattr(delta, "content_delta", None)
            if content_delta:
                _tps_state.on_part_delta(content_delta)
    elif event_type == "part_start":
        part_type = event_data.get("part_type", "")
        if part_type == "ToolCallPart":
            _tps_state.on_tool_call_start()
        elif part_type in ("TextPart", "ThinkingPart"):
            # A text/thinking part started — first token is imminent
            # (first_response will be set by on_part_delta)
            pass
    elif event_type == "part_end":
        # Finalize per-message stats when a text/thinking part ends
        # and the next part is something else (tool call or end)
        part_type = event_data.get("part_type", "")
        if part_type in ("TextPart", "ThinkingPart"):
            _tps_state.on_message_complete()


def _on_agent_run_start(
    agent_name: str, model_name: str, session_id: str | None = None
) -> None:
    """Mark streaming session start."""
    _tps_state.on_run_start()


def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Mark streaming session end."""
    _tps_state.on_run_end()


def _on_startup() -> None:
    """Register the TPS meter — no-op, callbacks already registered at import."""
    pass


# ---------------------------------------------------------------------------
# Registration — module-level so callbacks hook in at import time
# ---------------------------------------------------------------------------

register_callback("stream_event", _on_stream_event)
register_callback("agent_run_start", _on_agent_run_start)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("startup", _on_startup)
