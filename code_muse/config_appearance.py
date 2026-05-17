"""Config: appearance settings."""

import code_muse.config.parser as _parser


def set_diff_highlight_style(style: str):
    """Set the diff highlight style.

    Note: Text mode has been removed. This function is kept for backwards compatibility
    but does nothing. All diffs use beautiful syntax highlighting now!

    Args:
        style: Ignored (always uses 'highlight' mode)
    """
    # Do nothing - we always use highlight mode now!
    pass


_DEFAULT_DIFF_ADDITION_HEX = "#0b1f0b"  # darker green
_DEFAULT_DIFF_DELETION_HEX = "#390e1a"  # wine


def _coerce_to_hex(value: str | None, fallback: str) -> str:
    """Normalize any color string to '#RRGGBB'.

    Accepts:
      - '#RRGGBB' hex strings (any case) — returned lowercased.
      - Rich color names like 'green', 'orange1', 'bright_red'.
      - 'rgb(r,g,b)' forms that Rich understands.

    Anything Rich can't parse (including None/empty) falls back to ``fallback``.
    This keeps downstream consumers like ``brighten_hex`` happy — they only
    ever see a well-formed #RRGGBB string.
    """
    if not value:
        return fallback
    candidate = value.strip()
    # Fast-path: already a valid #RRGGBB.
    if (
        len(candidate) == 7
        and candidate.startswith("#")
        and all(c in "0123456789abcdefABCDEF" for c in candidate[1:])
    ):
        return candidate.lower()
    # Otherwise try Rich's parser (handles named colors, rgb(), etc.).
    try:
        from rich.color import Color  # local import keeps module import cheap

        triplet = Color.parse(candidate).get_truecolor()
        return f"#{triplet.red:02x}{triplet.green:02x}{triplet.blue:02x}"
    except Exception:
        return fallback


def get_diff_addition_color() -> str:
    """Get the base color for diff additions, always as a valid '#RRGGBB' hex.

    Falls back to the default darker green if the configured value is missing
    or unparseable.
    """
    return _coerce_to_hex(
        _parser.get_value("highlight_addition_color"), _DEFAULT_DIFF_ADDITION_HEX
    )


def set_diff_addition_color(color: str):
    """Set the color for diff additions.

    Accepts '#RRGGBB' hex, Rich color names ('green', 'bright_green', ...), or
    'rgb(r,g,b)'. The value is normalized to '#RRGGBB' before being written so
    downstream renderers never see a raw name.
    """
    _parser.set_config_value(
        "highlight_addition_color",
        _coerce_to_hex(color, _DEFAULT_DIFF_ADDITION_HEX),
    )


def get_diff_deletion_color() -> str:
    """Get the base color for diff deletions, always as a valid '#RRGGBB' hex.

    Falls back to the default wine if the configured value is missing or
    unparseable.
    """
    return _coerce_to_hex(
        _parser.get_value("highlight_deletion_color"), _DEFAULT_DIFF_DELETION_HEX
    )


def set_diff_deletion_color(color: str):
    """Set the color for diff deletions.

    Accepts '#RRGGBB' hex, Rich color names ('red', 'orange1', ...), or
    'rgb(r,g,b)'. The value is normalized to '#RRGGBB' before being written so
    downstream renderers never see a raw name.
    """
    _parser.set_config_value(
        "highlight_deletion_color",
        _coerce_to_hex(color, _DEFAULT_DIFF_DELETION_HEX),
    )


DEFAULT_BANNER_COLORS = {
    "thinking": "dark_violet",  # Violet - contemplation
    "agent_response": "purple4",  # Deep Purple - main AI output
    "shell_command": "deeppink3",  # Deep Pink - system commands
    "read_file": "dark_magenta",  # Magenta - reading files
    "edit_file": "purple4",  # Purple - modifications
    "create_file": "purple4",  # Purple - file creation
    "replace_in_file": "purple4",  # Purple - file modifications
    "delete_snippet": "dark_violet",  # Violet - snippet removal
    "grep": "medium_purple3",  # Light Purple - search results
    "directory_listing": "deeppink4",  # Deep Pink - navigation
    "agent_reasoning": "dark_violet",  # Violet - deep thought
    "invoke_agent": "deeppink3",  # Deep Pink - agent invocation
    "subagent_response": "purple3",  # Purple - sub-agent success
    "list_agents": "dark_magenta",  # Magenta - neutral listing
    "universal_constructor": "dark_violet",  # Violet - constructing tools
    # Browser/Terminal tools
    "terminal_tool": "purple4",  # Purple - browser terminal operations
    # User-initiated shell pass-through
    "shell_passthrough": "deeppink4",  # Deep Pink - user's own shell commands
}


def get_banner_color(banner_name: str) -> str:
    """Get the background color for a specific banner.

    Args:
        banner_name: The banner identifier (e.g., 'thinking', 'agent_response')

    Returns:
        Rich color name or hex code for the banner background
    """
    config_key = f"banner_color_{banner_name}"
    val = _parser.get_value(config_key)
    if val:
        return val
    return DEFAULT_BANNER_COLORS.get(banner_name, "blue")


def set_banner_color(banner_name: str, color: str):
    """Set the background color for a specific banner.

    Args:
        banner_name: The banner identifier (e.g., 'thinking', 'agent_response')
        color: Rich color name or hex code
    """
    config_key = f"banner_color_{banner_name}"
    _parser.set_config_value(config_key, color)


def get_all_banner_colors() -> dict:
    """Get all banner colors (configured or default).

    Returns:
        Dict mapping banner names to their colors
    """
    return {name: get_banner_color(name) for name in DEFAULT_BANNER_COLORS}


def reset_banner_color(banner_name: str):
    """Reset a banner color to its default.

    Args:
        banner_name: The banner identifier to reset
    """
    default_color = DEFAULT_BANNER_COLORS.get(banner_name, "blue")
    set_banner_color(banner_name, default_color)


def reset_all_banner_colors():
    """Reset all banner colors to their defaults."""
    for name, color in DEFAULT_BANNER_COLORS.items():
        set_banner_color(name, color)


def get_diff_context_lines() -> int:
    """
    Returns the user-configured number of context lines for diff display.
    This controls how many lines of surrounding context are shown in diffs.
    Defaults to 6 if unset or misconfigured.
    Configurable by 'diff_context_lines' key.
    """
    val = _parser.get_value("diff_context_lines")
    try:
        context_lines = int(val) if val else 6
        # Apply reasonable bounds: minimum 0, maximum 50
        return max(0, min(context_lines, 50))
    except ValueError, TypeError:
        return 6


def get_suppress_thinking_messages() -> bool:
    """
    Checks muse.cfg for 'suppress_thinking_messages' (case-insensitive in value only).
    Defaults to False if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    When enabled, thinking messages (agent_reasoning,
    planned_next_steps) will be hidden.
    """
    true_vals = {"1", "true", "yes", "on"}
    cfg_val = _parser.get_value("suppress_thinking_messages")
    if cfg_val is not None:
        return str(cfg_val).strip().lower() in true_vals
    return False


def set_suppress_thinking_messages(enabled: bool):
    """Sets the suppress_thinking_messages configuration value.

    Args:
        enabled: Whether to suppress thinking messages
    """
    _parser.set_config_value(
        "suppress_thinking_messages", "true" if enabled else "false"
    )


def get_suppress_informational_messages() -> bool:
    """
    Checks muse.cfg for 'suppress_informational_messages'
    (case-insensitive in value only).
    Defaults to False if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    When enabled, informational messages (info, success, warning) will be hidden.
    """
    true_vals = {"1", "true", "yes", "on"}
    cfg_val = _parser.get_value("suppress_informational_messages")
    if cfg_val is not None:
        return str(cfg_val).strip().lower() in true_vals
    return False


def set_suppress_informational_messages(enabled: bool):
    """Sets the suppress_informational_messages configuration value.

    Args:
        enabled: Whether to suppress informational messages
    """
    _parser.set_config_value(
        "suppress_informational_messages", "true" if enabled else "false"
    )
