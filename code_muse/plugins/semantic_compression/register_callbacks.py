"""Semantic Compression Plugin — callback registrations.

Wires the semantic compression engine into the Fast Puppy runtime:
- ``post_tool_call``: compress large string tool outputs
- ``load_prompt``: append compression-format instructions to the system prompt
- ``custom_command`` / ``custom_command_help``: ``/compress`` and
  ``/semantic-compression`` slash commands
- ``custom_command``: ``/show original`` to view last uncompressed output
"""

import logging
import re
from typing import Any

from code_muse.agents._history import estimate_tokens
from code_muse.callbacks import register_callback
from code_muse.config import get_value
from code_muse.messaging import emit_error, emit_info, emit_success

from .config import (
    get_compression_allowlist,
    get_compression_blocklist,
    get_default_compression_tools,
    get_semantic_compression_enabled,
    is_tool_allowed,
    set_compression_allowlist,
    set_compression_blocklist,
    set_semantic_compression_enabled,
)

logger = logging.getLogger(__name__)

# Threshold in characters: only compress tool results longer than this
_MIN_COMPRESS_LENGTH = 200

# Safety rail: never compress below this many content words
_MIN_CONTENT_WORDS = 700

# Zero-width marker appended to compressed output to prevent double compression
_COMPRESSION_MARKER = "\u200b\u200c\u200d"

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_last_original_output: str | None = None
_compression_stats: dict[str, int] = {
    "total_compressed": 0,
    "total_original_tokens": 0,
    "total_compressed_tokens": 0,
    "total_original_chars": 0,
    "total_compressed_chars": 0,
}


# ---------------------------------------------------------------------------
# post_tool_call — compress large text results (opt-out model)
# ---------------------------------------------------------------------------


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> Any:
    """Intercept tool results and apply semantic compression to string outputs.

    Compression is **enabled by default** for high-impact tools
    (``read_file``, ``grep``, ``run_shell_command``, ``list_files``,
    ``agent_run_shell_command``, ``invoke_agent``, ``read_relevant_code``).
    Other tools can be added via the allowlist; any tool can be blocked
    via the blocklist.

    Only compresses string results longer than *_MIN_COMPRESS_LENGTH*
    characters.  Returns the compressed string to replace the result,
    or ``None`` to leave it untouched.
    """
    global _last_original_output

    # Gate 1: plugin must be enabled
    if not get_semantic_compression_enabled():
        return None

    # Gate 2: tool must pass allowlist/blocklist checks
    if not is_tool_allowed(tool_name):
        return None

    # Only interested in string results of substantial length
    if not isinstance(result, str):
        return None
    if len(result) < _MIN_COMPRESS_LENGTH:
        return None

    # Gate 3: never double-compress — check for marker
    if result.endswith(_COMPRESSION_MARKER):
        return None

    # Gate 4: already-compressed heuristic
    if _looks_already_compressed(result):
        return None

    try:
        from .compressor import compress_semantic

        compressed = compress_semantic(result, aggressive=False)

        # Safety rail: never compress below _MIN_CONTENT_WORDS content words
        content_words = len(re.findall(r"\b\w+\b", compressed))
        if content_words < _MIN_CONTENT_WORDS:
            return None

        # Append marker to prevent double compression
        compressed = compressed + _COMPRESSION_MARKER

        # Compute token counts for metrics and visibility
        original_tokens = estimate_tokens(result)
        compressed_tokens = estimate_tokens(compressed)
        reduction_pct = (1 - compressed_tokens / max(original_tokens, 1)) * 100

        # Compute character counts for visibility
        original_chars = len(result)
        compressed_chars = len(compressed)

        # Store original for /show original
        _last_original_output = result

        # Update stats
        _compression_stats["total_compressed"] += 1
        _compression_stats["total_original_tokens"] += original_tokens
        _compression_stats["total_compressed_tokens"] += compressed_tokens
        _compression_stats["total_original_chars"] += original_chars
        _compression_stats["total_compressed_chars"] += compressed_chars

        # Visibility indicator
        if reduction_pct > 0:
            emit_info(
                f"\U0001f4e6 compressed {reduction_pct:.0f}% "
                f"({original_tokens:,} \u2192 {compressed_tokens:,} tokens)"
            )

        # Emit metric to upgrade_metrics (graceful fallback)
        _emit_compression_metric(
            tool_name, original_tokens, compressed_tokens, reduction_pct
        )

        logger.debug(
            "Compressed %s output: %d \u2192 %d chars (%.1f%% reduction)",
            tool_name,
            len(result),
            len(compressed),
            reduction_pct,
        )
        return compressed
    except Exception as exc:
        logger.warning("Semantic compression failed for %s: %s", tool_name, exc)
        return None


def _emit_compression_metric(
    tool_name: str,
    original_tokens: int,
    compressed_tokens: int,
    reduction_pct: float,
) -> None:
    """Emit a ``compression_applied`` event to upgrade_metrics.

    Fails silently if upgrade_metrics is unavailable.
    """
    try:
        from code_muse.plugins.upgrade_metrics import emit_metric

        emit_metric(
            "compression_applied",
            {
                "tool_name": tool_name,
                "original_tokens": original_tokens,
                "compressed_tokens": compressed_tokens,
                "strategy": "semantic",
                "reduction_pct": round(reduction_pct, 1),
            },
        )
    except Exception:
        pass

    try:
        from code_muse.plugins.upgrade_metrics.register_callbacks import (
            record_tokens,
        )

        record_tokens("after_compression", compressed_tokens)
    except Exception:
        pass


def _looks_already_compressed(text: str) -> bool:
    """Quick heuristic to skip text that's already telegraphic/compressed.

    Returns ``True`` if the text appears to already be compressed
    (very few function words relative to content words).
    """
    # Count common function words
    func_words = re.findall(
        r"\b(the|a|an|is|are|was|were|am|be|been|being|very|quite|"
        r"rather|really|extremely|somewhat|have|has|had|do|does|"
        r"did|will|would|can|could|may|might|should|it|this|that|"
        r"these|those|he|she|they|which|who|whom|in order to|"
        r"due to)\b",
        text,
        re.IGNORECASE,
    )
    total_words = len(re.findall(r"\b\w+\b", text))
    if total_words < 10:
        return True  # too short to judge
    func_ratio = len(func_words) / max(total_words, 1)
    # If fewer than 8% of words are function words, text likely already compressed
    return func_ratio < 0.08


# ---------------------------------------------------------------------------
# load_prompt — inject compression instructions into the system prompt
# ---------------------------------------------------------------------------


def _get_compression_prompt() -> str | None:
    """Return compression-format instructions for the system prompt.

    Tells the LLM it may use compressed/telegraphic communication style,
    referencing the same rules the compressor uses.
    """
    # Gate compression prompt on config flag (default: on)
    cfg_val = get_value("semantic_compression_enabled")
    if cfg_val is not None and str(cfg_val).strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return None  # Explicitly disabled — don't inject compression instructions
    return """\
## Semantic Compression Format

You may communicate in compressed form when appropriate. The system
understands semantic compression — grammar-light, content-dense
text that drops predictable function words.

### Compression Rules

**Drop (always safe):**
- Articles: a, an, the
- Copulas: is, are, was, were, am, be, been, being
- Filler phrases: "in order to" → "to", "due to the fact that" → "because"
- Pure intensifiers: very, quite, rather, really, extremely, somewhat
- Complementizer "that" after bridge verbs

**Drop when meaning unchanged (aggressive):**
- Auxiliary verbs: have/has/had, do/does/did, will/would
- Modal verbs: can/could/may/might/should (keep "must")
- Pronouns when referent obvious
- Relative pronouns: which, that, who, whom

**Structural compression:**
- Passive → active when agent known
- Nominalization → verb: "made a decision" → "decided"
- Redundant pairs → single: "each and every" → "every"
- Clause → modifier: "anomaly that was reported" → "reported anomaly"

**Always preserve:**
- Nouns, main verbs, meaning-bearing modifiers
- Numbers, quantifiers, uncertainty markers
- Negation (not, no, never)
- Temporal markers, causality, conditionals
- Requirements/permissions: must, required, prohibited, allowed
- Proper nouns, technical terms, code

Output should remain readable — prefer fragments over broken grammar."""


# ---------------------------------------------------------------------------
# /compress slash command
# ---------------------------------------------------------------------------


def _compress_command_help() -> list[tuple[str, str]]:
    return [
        (
            "compress",
            "Compress text with semantic compression (Tier 1 safe mode)",
        ),
        (
            "compress-aggressive",
            "Compress text with aggressive semantic compression (Tier 1+2)",
        ),
        (
            "semantic-compression",
            "Configure automatic semantic compression of tool output",
        ),
        (
            "show original",
            "Show the last uncompressed tool output",
        ),
    ]


def _handle_compress_command(command: str, name: str) -> bool | str | None:
    """Handle ``/compress`` and ``/compress-aggressive``.

    Returns the compressed text as a string for display, or ``True``
    to signal the command was handled.
    """
    if name not in ("compress", "compress-aggressive"):
        return None

    aggressive = name == "compress-aggressive"

    # Extract text after the command name
    parts = command.split(maxsplit=1)
    text = parts[1] if len(parts) > 1 else ""

    if not text.strip():
        return "Usage: /compress <text> or /compress-aggressive <text>"

    try:
        from .compressor import compress_semantic

        compressed = compress_semantic(text, aggressive=aggressive)
        mode = "aggressive" if aggressive else "safe"
        header = f"[Semantic compression ({mode}): "
        header += f"{len(text)} \u2192 {len(compressed)} chars]"
        return f"{header}\n{compressed}"
    except Exception as exc:
        logger.error("Compress command failed: %s", exc)
        return f"Compression error: {exc}"


# ---------------------------------------------------------------------------
# /show original command
# ---------------------------------------------------------------------------


def _handle_show_command(command: str, name: str) -> bool | str | None:
    """Handle ``/show original`` — display the last uncompressed output."""
    if name != "show":
        return None

    tokens = command.strip().split()
    if len(tokens) < 2 or tokens[1].lower() != "original":
        return None

    if _last_original_output is None:
        emit_info("No compressed output stored yet.")
        return True

    max_preview = 5000
    output = _last_original_output
    if len(output) > max_preview:
        output = (
            output[:max_preview]
            + f"\n... (truncated, {len(_last_original_output):,} total chars)"
        )
    return f"\U0001f4c4 Original (uncompressed) output:\n{output}"


# ---------------------------------------------------------------------------
# /semantic-compression slash command
# ---------------------------------------------------------------------------


def _handle_semantic_compression_command(command: str, name: str) -> bool | str | None:
    """Handle ``/semantic-compression`` configuration commands.

    Subcommands:
        on|off|true|false|enable|disable  — toggle automatic compression
        status                            — show current config
        stats                             — show compression statistics
        allowlist [tool1,tool2,...]       — set or clear allowlist
        blocklist [tool1,tool2,...]       — set or clear blocklist
    """
    if name != "semantic-compression":
        return None

    tokens = command.strip().split()
    if len(tokens) < 2:
        return _show_semantic_compression_status()

    sub = tokens[1].lower()

    # Toggle commands
    if sub in ("on", "true", "1", "yes", "enable"):
        set_semantic_compression_enabled(True)
        emit_success("\U0001f4e6 Semantic compression of tool output: ON")
        return True
    if sub in ("off", "false", "0", "no", "disable"):
        set_semantic_compression_enabled(False)
        emit_success("\U0001f4e6 Semantic compression of tool output: OFF")
        return True

    # Status
    if sub == "status":
        return _show_semantic_compression_status()

    # Stats
    if sub == "stats":
        return _show_compression_stats()

    # Allowlist
    if sub == "allowlist":
        if len(tokens) > 2:
            raw = " ".join(tokens[2:])
            tools = {t.strip() for t in raw.replace(",", " ").split() if t.strip()}
            set_compression_allowlist(tools)
            emit_success(
                f"\U0001f4e6 Compression allowlist set: {sorted(tools) or '(empty)'}"
            )
        else:
            set_compression_allowlist(set())
            emit_success("\U0001f4e6 Compression allowlist cleared")
        return True

    # Blocklist
    if sub == "blocklist":
        if len(tokens) > 2:
            raw = " ".join(tokens[2:])
            tools = {t.strip() for t in raw.replace(",", " ").split() if t.strip()}
            set_compression_blocklist(tools)
            emit_success(
                f"\U0001f4e6 Compression blocklist set: {sorted(tools) or '(empty)'}"
            )
        else:
            set_compression_blocklist(set())
            emit_success("\U0001f4e6 Compression blocklist cleared")
        return True

    emit_error(
        f"Unknown /semantic-compression subcommand: '{sub}'.\n"
        "Usage: /semantic-compression "
        "[on|off|status|stats|allowlist|blocklist]"
    )
    return True


# ---------------------------------------------------------------------------
# Status and stats display
# ---------------------------------------------------------------------------


def _show_semantic_compression_status() -> str:
    """Return a human-readable status string."""
    enabled = get_semantic_compression_enabled()
    allowlist = get_compression_allowlist()
    blocklist = get_compression_blocklist()
    default_tools = get_default_compression_tools()
    lines = [
        "\U0001f4e6 Semantic Compression Status:",
        f"  Enabled: {'yes' if enabled else 'no'}",
        f"  Default tools: {', '.join(sorted(default_tools))}",
    ]
    if allowlist:
        lines.append(f"  Extra allowlist: {', '.join(sorted(allowlist))}")
    else:
        lines.append("  Extra allowlist: (none)")
    if blocklist:
        lines.append(f"  Blocklist: {', '.join(sorted(blocklist))}")
    else:
        lines.append("  Blocklist: (none)")
    return "\n".join(lines)


def _show_compression_stats() -> str:
    """Return a human-readable compression stats string."""
    total = _compression_stats["total_compressed"]
    orig_tok = _compression_stats["total_original_tokens"]
    comp_tok = _compression_stats["total_compressed_tokens"]
    saved_tok = orig_tok - comp_tok
    pct_tok = (saved_tok / orig_tok * 100) if orig_tok else 0.0
    orig_ch = _compression_stats["total_original_chars"]
    comp_ch = _compression_stats["total_compressed_chars"]
    saved_ch = orig_ch - comp_ch
    pct_ch = (saved_ch / orig_ch * 100) if orig_ch else 0.0
    lines = [
        "\U0001f4e6 Semantic Compression Stats:",
        f"  Compressions applied: {total}",
        f"  Original tokens:     {orig_tok:,}",
        f"  Compressed tokens:   {comp_tok:,}",
        f"  Tokens saved:        {saved_tok:,} ({pct_tok:.1f}%)",
        f"  Original chars:      {orig_ch:,}",
        f"  Compressed chars:    {comp_ch:,}",
        f"  Chars saved:         {saved_ch:,} ({pct_ch:.1f}%)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Register callbacks
# ---------------------------------------------------------------------------

register_callback("post_tool_call", _on_post_tool_call, priority=0)
register_callback("load_prompt", _get_compression_prompt)
register_callback("custom_command_help", _compress_command_help)
register_callback("custom_command", _handle_compress_command)
register_callback("custom_command", _handle_semantic_compression_command)
register_callback("custom_command", _handle_show_command)

logger.info("Semantic Compression Plugin loaded")
