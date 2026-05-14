"""Configuration accessors for the Task Complete Sound plugin."""

from code_muse.config import get_value, set_value


def is_sound_enabled() -> bool:
    """Check if sound notification is enabled (default: False)."""
    val = get_value("sound_enabled")
    if val is None:
        return False
    return str(val).lower() in ("1", "true", "yes", "on")


def set_sound_enabled(enabled: bool) -> None:
    """Persist the sound toggle to muse.cfg."""
    set_value("sound_enabled", "true" if enabled else "false")


def get_sound_file() -> str | None:
    """Get custom sound file path, or None for default beep."""
    val = get_value("sound_file")
    if val is None or val == "":
        return None
    return val


def set_sound_file(path: str | None) -> None:
    """Set custom sound file path (None resets to default beep)."""
    set_value("sound_file", path if path else "")
