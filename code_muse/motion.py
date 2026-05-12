"""Centralized motion primitives for animated terminal output.

All animated effects (shimmer, spinners, indicators) should go through this
module so callers get a consistent reduced-motion fallback automatically.

Usage:
    from code_muse.motion import MotionMode, activity_indicator, shimmer_text

    mode = MotionMode.from_animations_enabled(True)

    # A shimmering bullet as an activity indicator
    bullet = activity_indicator(start_time, mode)

    # Shimmer text like "Thinking..."
    spans = shimmer_text("Thinking...", mode)
"""

import time
from enum import Enum

from rich.style import Style
from rich.text import Span

from code_muse.messaging.shimmer import shimmer_spans


class MotionMode(Enum):
    """Animation mode: full animation or reduced-motion fallback."""

    ANIMATED = "animated"
    REDUCED = "reduced"

    @classmethod
    def from_animations_enabled(cls, enabled: bool) -> MotionMode:
        """Convert a boolean flag to the corresponding mode."""
        return cls.ANIMATED if enabled else cls.REDUCED


class ReducedMotionIndicator(Enum):
    """Fallback indicator style when animations are disabled."""

    HIDDEN = "hidden"  # nothing shown
    STATIC_BULLET = "static_bullet"  # a plain dimmed bullet


def activity_indicator(
    start_time: float | None = None,
    motion_mode: MotionMode = MotionMode.ANIMATED,
    reduced_fallback: ReducedMotionIndicator = ReducedMotionIndicator.STATIC_BULLET,
) -> Span | None:
    """Return an activity-indicator ``Span`` appropriate for *motion_mode*.

    In ``ANIMATED`` mode this is a shimmering bullet ``•`` (truecolor
    terminal) or a blinking alternate-character effect (basic terminal).

    In ``REDUCED`` mode it follows *reduced_fallback*:
      - ``HIDDEN`` → ``None`` (invisible)
      - ``STATIC_BULLET`` → a dimmed ``•``

    Args:
        start_time: ``time.monotonic()`` value captured when the activity
            began, or ``None``.
        motion_mode: Current animation mode.
        reduced_fallback: What to show in reduced-motion mode.

    Returns:
        A ``Span`` or ``None``.
    """
    if motion_mode == MotionMode.REDUCED:
        if reduced_fallback == ReducedMotionIndicator.HIDDEN:
            return None
        # StaticBullet
        return Span(0, 1, Style(dim=True))

    # Animated mode
    elapsed = time.monotonic() - start_time if start_time else 0.0

    has_truecolor = _has_truecolor()
    if has_truecolor:
        # Use a shimmer bullet — single character through the shimmer pipeline.
        spans = shimmer_spans("•")
        return spans[0] if spans else Span(0, 1, Style())
    else:
        # 600ms blink period: alternate "•" / "◦".
        blink_on = int(elapsed * 1000 / 600) % 2 == 0
        if blink_on:
            return Span(0, 1, Style())
        else:
            return Span(0, 1, Style(dim=True))


def shimmer_text(
    text: str,
    motion_mode: MotionMode = MotionMode.ANIMATED,
) -> list[Span]:
    """Return shimmer-styled spans for *text*, or plain text in reduced mode.

    Args:
        text: The text to style.
        motion_mode: Current animation mode.

    Returns:
        List of ``Span`` objects.
    """
    if motion_mode == MotionMode.REDUCED:
        if not text:
            return []
        return [Span(0, len(text), Style())]
    return shimmer_spans(text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_truecolor_cache: bool | None = None


def _has_truecolor() -> bool:
    """Cached truecolor detection."""
    global _truecolor_cache
    if _truecolor_cache is None:
        from code_muse.terminal_utils import detect_truecolor_support

        _truecolor_cache = detect_truecolor_support()
    return _truecolor_cache
