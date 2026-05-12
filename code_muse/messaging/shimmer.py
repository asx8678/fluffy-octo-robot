"""Time-synchronized shimmer / sparkle text effect.

Port of the Codex `shimmer_spans` effect (Rust/ratatui) to Python/Rich.
Produces a cosine-based highlight band that sweeps across text characters
so all shimmer text on screen animates in lockstep.

Works with truecolor (RGB blending) and degrades gracefully on terminals
without truecolor support (uses DIM/BOLD modifiers).
"""

import math
import time

from rich.style import Style
from rich.text import Span

from code_muse.terminal_utils import detect_truecolor_support

# ---------------------------------------------------------------------------
# Process-start anchor so every shimmer instance is synchronized
# ---------------------------------------------------------------------------

_process_start: float | None = None


def _elapsed_since_start() -> float:
    """Seconds since the first shimmer call in this process."""
    global _process_start
    if _process_start is None:
        _process_start = time.monotonic()
    return time.monotonic() - _process_start


# ---------------------------------------------------------------------------
# RGB helpers
# ---------------------------------------------------------------------------

RGB = tuple[int, int, int]

# Sensible defaults for terminals whose true fg/bg we cannot query.
_DEFAULT_BASE: RGB = (160, 160, 160)  # medium gray — typical dimmed foreground
_DEFAULT_HIGHLIGHT: RGB = (255, 255, 255)  # white — background highlight


def blend(fg: RGB, bg: RGB, alpha: float) -> RGB:
    """Linear alpha-blend between two RGB colours.

    Returns components clamped to 0..255.
    """
    inv = 1.0 - alpha
    return (
        min(255, max(0, int(fg[0] * alpha + bg[0] * inv))),
        min(255, max(0, int(fg[1] * alpha + bg[1] * inv))),
        min(255, max(0, int(fg[2] * alpha + bg[2] * inv))),
    )


# ---------------------------------------------------------------------------
# Shimmer spans
# ---------------------------------------------------------------------------

# Cosine half-width of the highlight band in character positions.
_BAND_HALF_WIDTH = 5.0

# Padding added to each side of the text so the band can enter/exit smoothly.
_PADDING = 10

# Period of the sweep in seconds.
_SWEEP_SECONDS = 2.0


def shimmer_spans(
    text: str,
    *,
    base_color: RGB | None = None,
    highlight_color: RGB | None = None,
) -> list[Span]:
    """Return a list of Rich ``Span`` objects with a shimmer highlight band.

    The highlight sweeps across *text* once every ``_SWEEP_SECONDS`` seconds,
    synchronized to the first call anywhere in the process so multiple
    shimmer texts animate in lockstep.

    Args:
        text: The string to shimmer-ify.
        base_color: RGB tuple for dimmed characters.  Defaults to
            ``_DEFAULT_BASE``.
        highlight_color: RGB tuple for the highlight peak.  Defaults to
            ``_DEFAULT_HIGHLIGHT``.

    Returns:
        List of ``Span`` objects styled appropriately.
    """
    chars = list(text)
    if not chars:
        return []

    base = base_color or _DEFAULT_BASE
    highlight = highlight_color or _DEFAULT_HIGHLIGHT

    has_truecolor = detect_truecolor_support()

    period = len(chars) + _PADDING * 2
    elapsed = _elapsed_since_start()
    # Fractional position of the band centre (0 .. period).
    pos_f = (elapsed % _SWEEP_SECONDS) / _SWEEP_SECONDS * float(period)

    spans: list[Span] = []

    for i, _ch in enumerate(chars):
        # Signed distance from band centre (padding-adjusted).
        i_pos = float(i + _PADDING)
        dist = abs(i_pos - pos_f)

        # Cosine intensity: 1.0 at the centre, 0.0 beyond half-width.
        if dist <= _BAND_HALF_WIDTH:
            x = math.pi * (dist / _BAND_HALF_WIDTH)
            t = 0.5 * (1.0 + math.cos(x))
        else:
            t = 0.0

        if has_truecolor:
            alpha = t * 0.9  # peak blend strength
            r, g, b = blend(highlight, base, alpha)
            from rich.color import Color

            style = Style(color=Color.from_rgb(r, g, b), bold=True)
        else:
            style = _color_for_level(t)

        spans.append(Span(i, i + 1, style))

    return spans


# ---------------------------------------------------------------------------
# Fallback for terminals without truecolor
# ---------------------------------------------------------------------------


def _color_for_level(intensity: float) -> Style:
    """Map a cosine intensity to a Rich Style using modifiers only.

    This keeps the shimmer readable on basic terminals:
      - < 0.2 → DIM (faint)
      - 0.2–0.6 → NORMAL
      - > 0.6 → BOLD (bright)
    """
    if intensity < 0.2:
        return Style(dim=True)
    elif intensity < 0.6:
        return Style()
    else:
        return Style(bold=True)
