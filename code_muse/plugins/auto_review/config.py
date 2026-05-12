"""Configuration accessors for the Auto-Review plugin."""

from code_muse.config import get_value


def is_auto_review_enabled() -> bool:
    """Check if auto-review is enabled (default: True)."""
    val = get_value("auto_review_enabled")
    if val is None:
        return True
    return str(val).lower() in ("1", "true", "yes", "on")


def get_auto_review_model() -> str | None:
    """Get the model to use for auto-review, or None to use the global model."""
    return get_value("auto_review_model")


def get_auto_review_mode() -> str:
    """Get the review mode: 'background' or 'blocking' (default: 'background')."""
    val = get_value("auto_review_mode")
    if val and val.strip().lower() in ("background", "blocking"):
        return val.strip().lower()
    return "background"


def get_auto_review_min_diff_length() -> int:
    """Minimum diff length (in characters) to trigger a review (default: 10)."""
    val = get_value("auto_review_min_diff_length")
    if val is not None:
        try:
            return max(0, int(val))
        except (ValueError, TypeError):
            pass
    return 10
