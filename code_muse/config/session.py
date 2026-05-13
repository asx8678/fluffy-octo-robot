"""Config: autosave session management and command history."""

import contextlib
import datetime

import code_muse.config.parser as _parser
import code_muse.config.paths as paths

# Runtime-only autosave session ID (per-process)
_CURRENT_AUTOSAVE_ID: str | None = None

# Autosave throttle: only persist to disk every N calls
# Combined with the dirty-flag hash check in save_session(), this
# eliminates redundant full-history JSON serialization on consecutive
# agent turns where the user has not added new messages.
_AUTOSAVE_THROTTLE = 4
_autosave_counter: int = 0


def get_current_autosave_id() -> str:
    """Get or create the current autosave session ID for this process."""
    global _CURRENT_AUTOSAVE_ID
    if not _CURRENT_AUTOSAVE_ID:
        # Use a full timestamp so tests and UX can predict the name if needed
        _CURRENT_AUTOSAVE_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CURRENT_AUTOSAVE_ID


def rotate_autosave_id() -> str:
    """Force a new autosave session ID and return it."""
    global _CURRENT_AUTOSAVE_ID
    _CURRENT_AUTOSAVE_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CURRENT_AUTOSAVE_ID


def get_current_autosave_session_name() -> str:
    """Return the full session name used for autosaves (no file extension)."""
    return f"auto_session_{get_current_autosave_id()}"


def set_current_autosave_from_session_name(session_name: str) -> str:
    """Set the current autosave ID based on a full session name.

    Accepts names like 'auto_session_YYYYMMDD_HHMMSS' and extracts the ID part.
    Returns the ID that was set.
    """
    global _CURRENT_AUTOSAVE_ID
    prefix = "auto_session_"
    if session_name.startswith(prefix):
        _CURRENT_AUTOSAVE_ID = session_name[len(prefix) :]
    else:
        _CURRENT_AUTOSAVE_ID = session_name
    return _CURRENT_AUTOSAVE_ID


def get_auto_save_session() -> bool:
    """
    Checks muse.cfg for 'auto_save_session' (case-insensitive in value only).
    Defaults to True if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    """
    true_vals = {"1", "true", "yes", "on"}
    cfg_val = _parser.get_value("auto_save_session")
    if cfg_val is not None:
        return str(cfg_val).strip().lower() in true_vals
    return True


def set_auto_save_session(enabled: bool):
    """Sets the auto_save_session configuration value.

    Args:
        enabled: Whether to enable auto-saving of sessions
    """
    _parser.set_config_value("auto_save_session", "true" if enabled else "false")


def get_max_saved_sessions() -> int:
    """
    Gets the maximum number of sessions to keep.
    Defaults to 20 if not set.
    """
    cfg_val = _parser.get_value("max_saved_sessions")
    if cfg_val is not None:
        try:
            val = int(cfg_val)
            return max(0, val)  # Ensure non-negative
        except (ValueError, TypeError):
            pass
    return 20


def set_max_saved_sessions(max_sessions: int):
    """Sets the max_saved_sessions configuration value.

    Args:
        max_sessions: Maximum number of sessions to keep (0 for unlimited)
    """
    _parser.set_config_value("max_saved_sessions", str(max_sessions))


def auto_save_session_if_enabled() -> bool:
    """Automatically save the current session if auto_save_session is enabled."""
    if not get_auto_save_session():
        return False

    # Throttle: only write to disk every N autosaves to avoid
    # rewriting the entire session history as JSON on every turn.
    global _autosave_counter
    _autosave_counter += 1
    if _autosave_counter % _AUTOSAVE_THROTTLE != 0:
        return True

    try:
        import pathlib

        from code_muse.agents.agent_manager import get_current_agent
        from code_muse.messaging import emit_info
        from code_muse.session_storage import save_session

        current_agent = get_current_agent()
        history = current_agent.get_message_history()
        if not history:
            return False

        now = datetime.datetime.now()
        session_name = get_current_autosave_session_name()
        autosave_dir = pathlib.Path(paths.AUTOSAVE_DIR)

        metadata = save_session(
            history=history,
            session_name=session_name,
            base_dir=autosave_dir,
            timestamp=now.isoformat(),
            token_estimator=current_agent.estimate_tokens_for_message,
            auto_saved=True,
        )

        emit_info(
            f"[Done] Auto-saved session: "
            f"{metadata.message_count} messages ({metadata.total_tokens} tokens)"
        )

        # Clean up old sessions after successful save
        try:
            from code_muse.session_storage import cleanup_sessions

            max_sessions = get_max_saved_sessions()
            if max_sessions > 0:
                removed = cleanup_sessions(autosave_dir, max_sessions)
                if removed:
                    emit_info(f"Cleaned up {len(removed)} old session(s)")
        except Exception:
            pass  # Non-critical; don't let cleanup failure affect the user

        return True

    except Exception as exc:  # pragma: no cover - defensive logging
        from code_muse.messaging import emit_error

        emit_error(f"Failed to auto-save session: {exc}")
        return False


def finalize_autosave_session() -> str:
    """Persist the current autosave snapshot and rotate to a fresh session."""
    auto_save_session_if_enabled()
    return rotate_autosave_id()


def normalize_command_history():
    """
    Normalize the command history file by converting old format
    timestamps to the new format.

    Old format example:
    - "# 2025-08-04 12:44:45.469829"

    New format example:
    - "# 2025-08-05T10:35:33" (ISO)
    """
    import os
    import re

    # Skip implementation during tests
    import sys

    if "pytest" in sys.modules:
        return

    # Skip normalization if file doesn't exist
    command_history_exists = paths.COMMAND_HISTORY_FILE.is_file()
    if not command_history_exists:
        return

    try:
        # Read the entire file with encoding error handling for Windows
        with open(
            paths.COMMAND_HISTORY_FILE, encoding="utf-8", errors="surrogateescape"
        ) as f:
            content = f.read()

        # Sanitize any surrogate characters that might have slipped in
        with contextlib.suppress(UnicodeEncodeError, UnicodeDecodeError):
            content = content.encode("utf-8", errors="surrogatepass").decode(
                "utf-8", errors="replace"
            )

        # Skip empty files
        if not content.strip():
            return

        # Define regex pattern for old timestamp format
        # Format: "# YYYY-MM-DD HH:MM:SS.ffffff"
        old_timestamp_pattern = r"# (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\.(\d+)"

        # Function to convert matched timestamp to ISO format
        def convert_to_iso(match):
            date = match.group(1)
            time = match.group(2)
            # Create ISO format (YYYY-MM-DDThh:mm:ss)
            return f"# {date}T{time}"

        # Replace all occurrences of the old timestamp format with the new ISO format
        updated_content = re.sub(old_timestamp_pattern, convert_to_iso, content)

        # Write the updated content back to the file only if changes were made
        if content != updated_content:
            import tempfile

            fd, tmp_path = tempfile.mkstemp(
                dir=str(paths.COMMAND_HISTORY_FILE.parent), suffix=".tmp"
            )
            try:
                with os.fdopen(
                    fd, "w", encoding="utf-8", errors="surrogateescape"
                ) as f:
                    f.write(updated_content)
                os.replace(tmp_path, paths.COMMAND_HISTORY_FILE)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
    except Exception as e:
        from code_muse.messaging import emit_error

        emit_error(
            f"An unexpected error occurred while normalizing command history: {str(e)}"
        )


def initialize_command_history_file():
    """Create the command history file if it doesn't exist.
    Handles migration from the old history file location for backward compatibility.
    Also normalizes the command history format if needed.
    """
    from pathlib import Path

    # Ensure the state directory exists before trying to create the history file
    if not paths.STATE_DIR.exists():
        paths.STATE_DIR.mkdir(parents=True, exist_ok=True)

    command_history_exists = paths.COMMAND_HISTORY_FILE.is_file()
    if not command_history_exists:
        try:
            paths.COMMAND_HISTORY_FILE.touch()

            # For backwards compatibility, copy the old history file, then remove it
            old_history_file = Path.home() / ".muse_history.txt"
            old_history_exists = old_history_file.is_file()
            if old_history_exists:
                import shutil

                shutil.copy2(old_history_file, paths.COMMAND_HISTORY_FILE)
                old_history_file.unlink(missing_ok=True)

                # Normalize the command history format if needed
                normalize_command_history()
        except Exception as e:
            from code_muse.messaging import emit_error

            emit_error(
                f"An unexpected error occurred while trying to "
                f"initialize history file: {str(e)}"
            )


def save_command_to_history(command: str):
    """Save a command to the history file with an ISO format timestamp.

    Args:
        command: The command to save
    """
    import datetime

    try:
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")

        # Sanitize command to remove any invalid surrogate characters
        # that could cause encoding errors on Windows
        try:
            command = command.encode("utf-8", errors="surrogatepass").decode(
                "utf-8", errors="replace"
            )
        except (UnicodeEncodeError, UnicodeDecodeError):
            # If that fails, do a more aggressive cleanup
            command = "".join(
                char if ord(char) < 0xD800 or ord(char) > 0xDFFF else "\ufffd"
                for char in command
            )

        with open(
            paths.COMMAND_HISTORY_FILE, "a", encoding="utf-8", errors="surrogateescape"
        ) as f:
            f.write(f"\n# {timestamp}\n{command}\n")
    except Exception as e:
        from code_muse.messaging import emit_error

        emit_error(
            f"An unexpected error occurred while saving command history: {str(e)}"
        )
