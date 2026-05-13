"""Diff formatting utilities with syntax highlighting."""

try:
    from pygments import lex
    from pygments.lexers import TextLexer, get_lexer_by_name
    from pygments.token import Token

    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False

from rich.text import Text

from code_muse.messaging import emit_warning

# SYNTAX HIGHLIGHTING FOR DIFFS ("syntax" mode)
# ============================================================================

# Monokai color scheme - because we have taste 🎨
TOKEN_COLORS = (
    {
        Token.Keyword: "#f92672" if PYGMENTS_AVAILABLE else "magenta",
        Token.Name.Builtin: "#66d9ef" if PYGMENTS_AVAILABLE else "cyan",
        Token.Name.Function: "#a6e22e" if PYGMENTS_AVAILABLE else "green",
        Token.String: "#e6db74" if PYGMENTS_AVAILABLE else "yellow",
        Token.Number: "#ae81ff" if PYGMENTS_AVAILABLE else "magenta",
        Token.Comment: "#75715e" if PYGMENTS_AVAILABLE else "bright_black",
        Token.Operator: "#f92672" if PYGMENTS_AVAILABLE else "magenta",
    }
    if PYGMENTS_AVAILABLE
    else {}
)

EXTENSION_TO_LEXER_NAME = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".cs": "csharp",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".txt": "text",
}


def _get_lexer_for_extension(extension: str):
    """Get the appropriate Pygments lexer for a file extension.

    Args:
        extension: File extension (with or without leading dot)

    Returns:
        A Pygments lexer instance or None if Pygments not available
    """
    if not PYGMENTS_AVAILABLE:
        return None

    # Normalize extension to have leading dot and be lowercase
    if not extension.startswith("."):
        extension = f".{extension}"
    extension = extension.lower()

    lexer_name = EXTENSION_TO_LEXER_NAME.get(extension, "text")

    try:
        return get_lexer_by_name(lexer_name)
    except Exception:
        # Fallback to plain text if lexer not found
        return TextLexer()


def _get_token_color(token_type) -> str:
    """Get color for a token type from our Monokai scheme.

    Args:
        token_type: Pygments token type

    Returns:
        Hex color string or color name
    """
    if not PYGMENTS_AVAILABLE:
        return "#cccccc"

    for ttype, color in TOKEN_COLORS.items():
        if token_type in ttype:
            return color
    return "#cccccc"  # Default light-grey for unmatched tokens


def _highlight_code_line(code: str, bg_color: str | None, lexer) -> Text:
    """Highlight a line of code with syntax highlighting and optional background color.

    Args:
        code: The code string to highlight
        bg_color: Background color in hex format, or None for no background
        lexer: Pygments lexer instance to use

    Returns:
        Rich Text object with styling applied
    """
    if not PYGMENTS_AVAILABLE or lexer is None:
        # Fallback: just return text with optional background
        if bg_color:
            return Text(code, style=f"on {bg_color}")
        return Text(code)

    text = Text()

    for token_type, value in lex(code, lexer):
        # Strip trailing newlines that Pygments adds
        # Pygments lexer always adds a \n at the end of the last token
        value = value.rstrip("\n")

        # Skip if the value is now empty (was only whitespace/newlines)
        if not value:
            continue

        fg_color = _get_token_color(token_type)
        # Apply foreground color and optional background
        if bg_color:
            text.append(value, style=f"{fg_color} on {bg_color}")
        else:
            text.append(value, style=fg_color)

    return text


def _extract_file_extension_from_diff(diff_text: str) -> str:
    """Extract file extension from diff headers.

    Args:
        diff_text: Unified diff text

    Returns:
        File extension (e.g., '.py') or '.txt' as fallback
    """
    import re

    # Look for +++ b/filename.ext or --- a/filename.ext headers
    pattern = r"^(?:\+\+\+|---) [ab]/.*?(\.[a-zA-Z0-9]+)$"

    for line in diff_text.split("\n")[:10]:  # Check first 10 lines
        match = re.search(pattern, line)
        if match:
            return match.group(1)

    return ".txt"  # Fallback to plain text


# ============================================================================
# COLOR PAIR OPTIMIZATION (for "highlighted" mode)
# ============================================================================


def brighten_hex(hex_color: str, factor: float) -> str:
    """
    Darken a hex color by multiplying each RGB channel by `factor`.
    factor=1.0 -> no change
    factor=0.0 -> black
    factor=0.18 -> good for diff backgrounds (recommended)
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        raise ValueError(f"Expected #RRGGBB, got {hex_color!r}")

    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    r = max(0, min(255, int(r * (1 + factor))))
    g = max(0, min(255, int(g * (1 + factor))))
    b = max(0, min(255, int(b * (1 + factor))))

    return f"#{r:02x}{g:02x}{b:02x}"


def _format_diff_with_syntax_highlighting(
    diff_text: str,
    addition_color: str | None = None,
    deletion_color: str | None = None,
) -> Text:
    """Format diff with full syntax highlighting using Pygments.

    This renders diffs with:
    - Syntax highlighting for code tokens
    - Colored backgrounds for context/added/removed lines
    - Monokai color scheme
    - Optional custom colors for additions/deletions

    Args:
        diff_text: Raw unified diff text
        addition_color: Optional custom color for added lines (default: green)
        deletion_color: Optional custom color for deleted lines (default: red)

    Returns:
        Rich Text object with syntax highlighting (can be passed to emit_info)
    """
    if not PYGMENTS_AVAILABLE:
        return Text(diff_text)

    # Extract file extension from diff headers
    extension = _extract_file_extension_from_diff(diff_text)
    lexer = _get_lexer_for_extension(extension)

    # Generate background colors from foreground colors
    add_fg = brighten_hex(addition_color, 0.6)
    del_fg = brighten_hex(deletion_color, 0.6)

    # Background colors for different line types
    # Context lines have no background (None) for clean, minimal diffs
    bg_colors = {
        "removed": deletion_color,
        "added": addition_color,
        "context": None,  # No background for unchanged lines
    }

    lines = diff_text.split("\n")
    # Remove trailing empty line if it exists (from trailing \n in diff)
    if lines and lines[-1] == "":
        lines = lines[:-1]
    result = Text()

    for i, line in enumerate(lines):
        if not line:
            # Empty line - just add a newline if not the last line
            if i < len(lines) - 1:
                result.append("\n")
            continue

        # Skip diff headers - they're redundant noise since we show the
        # filename in the banner
        if line.startswith(("---", "+++", "@@", "diff ", "index ")):
            continue
        else:
            # Determine line type and extract code content
            if line.startswith("-"):
                line_type = "removed"
                code = line[1:]  # Remove the '-' prefix
                marker_style = f"bold {del_fg} on {bg_colors[line_type]}"
                prefix = "- "
            elif line.startswith("+"):
                line_type = "added"
                code = line[1:]  # Remove the '+' prefix
                marker_style = f"bold {add_fg} on {bg_colors[line_type]}"
                prefix = "+ "
            else:
                line_type = "context"
                code = line[1:] if line.startswith(" ") else line
                # Context lines have no background - clean and minimal
                marker_style = ""  # No special styling for context markers
                prefix = "  "

            # Add the marker prefix
            if marker_style:  # Only apply style if we have one
                result.append(prefix, style=marker_style)
            else:
                result.append(prefix)

            # Add syntax-highlighted code
            highlighted = _highlight_code_line(code, bg_colors[line_type], lexer)
            result.append_text(highlighted)

        # Add newline after each line except the last
        if i < len(lines) - 1:
            result.append("\n")

    return result


def format_diff_with_colors(diff_text: str) -> Text:
    """Format diff text with beautiful syntax highlighting.

    This is the canonical diff formatting function used across the codebase.
    It applies user-configurable color coding with full syntax highlighting
    using Pygments.

    The function respects user preferences from config:
    - get_diff_addition_color(): Color for added lines (markers and backgrounds)
    - get_diff_deletion_color(): Color for deleted lines (markers and backgrounds)

    Args:
        diff_text: Raw diff text to format

    Returns:
        Rich Text object with syntax highlighting
    """
    from code_muse.config import (
        get_diff_addition_color,
        get_diff_deletion_color,
    )

    if not diff_text or not diff_text.strip():
        return Text("-- no diff available --", style="dim")

    addition_base_color = get_diff_addition_color()
    deletion_base_color = get_diff_deletion_color()

    # Always use beautiful syntax highlighting!
    if not PYGMENTS_AVAILABLE:
        emit_warning("Pygments not available, diffs will look plain")
        # Return plain text as fallback
        return Text(diff_text)

    # Return Text object with custom colors - emit_info handles this correctly
    return _format_diff_with_syntax_highlighting(
        diff_text,
        addition_color=addition_base_color,
        deletion_color=deletion_base_color,
    )
