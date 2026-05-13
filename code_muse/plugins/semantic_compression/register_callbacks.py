"""Semantic Compression Plugin — callback registrations.

Wires the semantic compression engine into the Fast Puppy runtime:
- ``post_tool_call``: compress large string tool outputs
- ``load_prompt``: append compression-format instructions to the system prompt
- ``custom_command`` / ``custom_command_help``: ``/compress`` slash command
"""

import logging
import re
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.config import get_value
from code_muse.messaging import emit_error, emit_success

from .config import (
    get_compression_allowlist,
    get_compression_blocklist,
    get_semantic_compression_enabled,
    is_tool_allowed,
    set_compression_allowlist,
    set_compression_blocklist,
    set_semantic_compression_enabled,
)

logger = logging.getLogger(__name__)

# Threshold in characters: only compress tool results longer than this
_MIN_COMPRESS_LENGTH = 200


# ---------------------------------------------------------------------------
# post_tool_call — compress large text results (gated, opt-in)
# ---------------------------------------------------------------------------


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> Any:
    """Intercept tool results and apply semantic compression to string outputs.

    Compression is **opt-in** via ``semantic_compression_enabled`` config
    and can be scoped to specific tools via allowlist/blocklist.

    Only compresses string results longer than *_MIN_COMPRESS_LENGTH*
    characters.  Returns ``None`` so the tool result is left untouched
    (we don't modify in-place — the caller uses the return to *replace*
    the result).

    Code blocks inside results are detected and preserved verbatim.
    """
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

    # Skip results that look like they're already compressed
    # (heuristic: very high ratio of content words to function words)
    if _looks_already_compressed(result):
        return None

    try:
        from .compressor import compress_semantic

        compressed = compress_semantic(result, aggressive=False)
        logger.debug(
            "Compressed %s output: %d → %d chars (%.1f%% reduction)",
            tool_name,
            len(result),
            len(compressed),
            (1 - len(compressed) / max(len(result), 1)) * 100,
        )
        return compressed
    except Exception as exc:
        logger.warning("Semantic compression failed for %s: %s", tool_name, exc)
        return None


def _looks_already_compressed(text: str) -> bool:
    """Quick heuristic to skip text that's already telegraphic/compressed.

    Returns ``True`` if the text appears to already be compressed
    (very few function words relative to content words).
    """
    # Count common function words
    func_words = re.findall(
        r"\b(the|a|an|is|are|was|were|am|be|been|being|very|quite|rather|really"
        r"|extremely|somewhat|have|has|had|do|does|did|will|would|can|could"
        r"|may|might|should|it|this|that|these|those|he|she|they|which|who"
        r"|whom|in order to|due to)\b",
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
    # Gate compression prompt on config flag (default: off)
    cfg_val = get_value("semantic_compression_enabled")
    if not cfg_val or str(cfg_val).strip().lower() not in ("1", "true", "yes"):
        return None  # Don't inject compression instructions
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
        return f"[Semantic compression ({mode}): {len(text)} → {len(compressed)} chars]\n{compressed}"
    except Exception as exc:
        logger.error("Compress command failed: %s", exc)
        return f"Compression error: {exc}"


# ---------------------------------------------------------------------------
# /semantic-compression slash command
# ---------------------------------------------------------------------------


def _handle_semantic_compression_command(command: str, name: str) -> bool | str | None:
    """Handle ``/semantic-compression`` configuration commands.

    Subcommands:
        on|off|true|false|enable|disable  — toggle automatic compression
        status                            — show current config
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
        emit_success("[Run] Semantic compression of tool output: ON")
        return True
    if sub in ("off", "false", "0", "no", "disable"):
        set_semantic_compression_enabled(False)
        emit_success("[Run] Semantic compression of tool output: OFF")
        return True

    # Status
    if sub == "status":
        return _show_semantic_compression_status()

    # Allowlist
    if sub == "allowlist":
        if len(tokens) > 2:
            raw = " ".join(tokens[2:])
            tools = {t.strip() for t in raw.replace(",", " ").split() if t.strip()}
            set_compression_allowlist(tools)
            emit_success(
                f"[Run] Compression allowlist set: {sorted(tools) or '(empty)'}"
            )
        else:
            set_compression_allowlist(set())
            emit_success("[Run] Compression allowlist cleared")
        return True

    # Blocklist
    if sub == "blocklist":
        if len(tokens) > 2:
            raw = " ".join(tokens[2:])
            tools = {t.strip() for t in raw.replace(",", " ").split() if t.strip()}
            set_compression_blocklist(tools)
            emit_success(
                f"[Run] Compression blocklist set: {sorted(tools) or '(empty)'}"
            )
        else:
            set_compression_blocklist(set())
            emit_success("[Run] Compression blocklist cleared")
        return True

    emit_error(
        f"Unknown /semantic-compression subcommand: '{sub}'.\n"
        "Usage: /semantic-compression [on|off|status|allowlist|blocklist]"
    )
    return True


def _show_semantic_compression_status() -> str:
    """Return a human-readable status string."""
    enabled = get_semantic_compression_enabled()
    allowlist = get_compression_allowlist()
    blocklist = get_compression_blocklist()
    lines = [
        "Semantic Compression Status:",
        f"  Enabled: {'yes' if enabled else 'no (opt-in)'}"
        if not enabled
        else "  Enabled: yes",
    ]
    if allowlist:
        lines.append(f"  Allowlist: {', '.join(sorted(allowlist))}")
    else:
        lines.append("  Allowlist: (none — all tools allowed)")
    if blocklist:
        lines.append(f"  Blocklist: {', '.join(sorted(blocklist))}")
    else:
        lines.append("  Blocklist: (none)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Register callbacks
# ---------------------------------------------------------------------------

register_callback("post_tool_call", _on_post_tool_call, priority=0)
register_callback("load_prompt", _get_compression_prompt)
register_callback("custom_command_help", _compress_command_help)
register_callback("custom_command", _handle_compress_command)
register_callback("custom_command", _handle_semantic_compression_command)

logger.info("Semantic Compression Plugin loaded")
