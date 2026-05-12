"""Tests for code_muse.messaging.shimmer and code_muse.motion."""

from rich.text import Span, Text

from code_muse.messaging.shimmer import blend, shimmer_spans
from code_muse.motion import (
    MotionMode,
    ReducedMotionIndicator,
    activity_indicator,
    shimmer_text,
)

# ---------------------------------------------------------------------------
# blend
# ---------------------------------------------------------------------------


def test_blend_identity():
    """Alpha=1.0 returns fg unchanged."""
    assert blend((10, 20, 30), (100, 200, 255), 1.0) == (10, 20, 30)


def test_blend_full_transparent():
    """Alpha=0.0 returns bg unchanged."""
    assert blend((10, 20, 30), (100, 200, 255), 0.0) == (100, 200, 255)


def test_blend_mid():
    """Alpha=0.5 gives midpoint."""
    result = blend((0, 0, 0), (200, 200, 200), 0.5)
    assert result == (100, 100, 100)


def test_blend_clamped():
    """Values are clamped to 0..255."""
    assert blend((300, -10, 128), (0, 500, 0), 0.5) == (150, 245, 64)


# ---------------------------------------------------------------------------
# shimmer_spans
# ---------------------------------------------------------------------------


def test_shimmer_empty():
    """Empty string returns empty list."""
    assert shimmer_spans("") == []


def test_shimmer_single_char():
    """Single character gets one span."""
    spans = shimmer_spans("X")
    assert len(spans) == 1
    assert isinstance(spans[0], Span)
    assert spans[0].start == 0
    assert spans[0].end == 1


def test_shimmer_spans_length_matches_text():
    """Number of spans equals number of characters."""
    for text in ["hello", "a", "12345", "Testing 1 2 3"]:
        spans = shimmer_spans(text)
        assert len(spans) == len(text), f"mismatch for {text!r}"


def test_shimmer_spans_are_contiguous():
    """Spans cover positions 0..N without gaps or overlaps."""
    spans = shimmer_spans("hello")
    for i, s in enumerate(spans):
        assert s.start == i
        assert s.end == i + 1


def test_shimmer_uses_supplied_colors():
    """Custom colors are reflected in span styles."""
    spans = shimmer_spans(
        "ab", base_color=(50, 50, 50), highlight_color=(240, 240, 240)
    )
    # Spans should have RGB styles (not just DIM/BOLD)
    for s in spans:
        assert s.style is not None
        # truecolor style has a color attribute
        if hasattr(s.style, "color") and s.style.color is not None:
            assert s.style.color.triplet is not None


# ---------------------------------------------------------------------------
# MotionMode
# ---------------------------------------------------------------------------


def test_motion_mode_from_bool():
    assert MotionMode.from_animations_enabled(True) == MotionMode.ANIMATED
    assert MotionMode.from_animations_enabled(False) == MotionMode.REDUCED


# ---------------------------------------------------------------------------
# activity_indicator
# ---------------------------------------------------------------------------


def test_activity_reduced_hidden():
    """REDUCED + HIDDEN returns None."""
    result = activity_indicator(
        motion_mode=MotionMode.REDUCED,
        reduced_fallback=ReducedMotionIndicator.HIDDEN,
    )
    assert result is None


def test_activity_reduced_static():
    """REDUCED + STATIC_BULLET returns a dim Span."""
    result = activity_indicator(
        motion_mode=MotionMode.REDUCED,
        reduced_fallback=ReducedMotionIndicator.STATIC_BULLET,
    )
    assert isinstance(result, Span)
    assert result.start == 0
    assert result.end == 1
    assert result.style.dim is True


def test_activity_animated_returns_span():
    """ANIMATED always returns a Span."""
    result = activity_indicator(motion_mode=MotionMode.ANIMATED)
    assert isinstance(result, Span)


# ---------------------------------------------------------------------------
# shimmer_text
# ---------------------------------------------------------------------------


def test_shimmer_text_animated():
    """Animated mode returns spans for each character."""
    spans = shimmer_text("Hi", MotionMode.ANIMATED)
    assert len(spans) == 2
    for s in spans:
        assert isinstance(s, Span)


def test_shimmer_text_reduced():
    """Reduced mode returns a single plain span covering the whole text."""
    spans = shimmer_text("Hi", MotionMode.REDUCED)
    assert len(spans) == 1
    assert spans[0].start == 0
    assert spans[0].end == 2


def test_shimmer_text_empty():
    """Empty text in any mode returns empty list."""
    assert shimmer_text("", MotionMode.ANIMATED) == []
    assert shimmer_text("", MotionMode.REDUCED) == []


# ---------------------------------------------------------------------------
# Integration: Text with shimmer spans
# ---------------------------------------------------------------------------


def test_text_with_shimmer_spans_renders():
    """A Text object with shimmer spans produces markup."""
    t = Text("Hello")
    t.spans = shimmer_spans("Hello")
    markup = t.markup
    assert markup  # non-empty
    assert "[bold" in markup or "[/" in markup  # some styling present
