"""User-visible context warnings and controls.

Provides:
- Pre-compaction warnings at 75% and 90% thresholds
- /pin and /unpin commands to mark conversation as protected
- /context command showing current token usage, protected budget, compaction plan
- Non-blocking by default, configurable blocking mode
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Track whether we've warned at each level this session
_warned_75pct = False
_warned_90pct = False
_warned_pre_compact = False


def reset_warning_state() -> None:
    """Reset warning flags (e.g., after compaction or config change)."""
    global _warned_75pct, _warned_90pct, _warned_pre_compact
    _warned_75pct = False
    _warned_90pct = False
    _warned_pre_compact = False


def check_and_emit_context_warnings(
    usage_pct: float,
    budget_tokens: int,
    tokens_used: int,
    model_name: str | None = None,
    message_count: int = 0,
    hard_cap: int = 50,
) -> None:
    """Emit user-visible warnings based on context usage percentage.

    - At 75%: informational warning with tip
    - At 90%: critical warning with urgency
    - Both fire only once per session (until reset)
    """
    global _warned_75pct, _warned_90pct, _warned_pre_compact
    from code_muse.messaging import emit_info, emit_warning

    model_info = f" ({model_name})" if model_name else ""
    remaining = max(0, budget_tokens - tokens_used)

    if usage_pct >= 0.90 and not _warned_90pct:
        emit_warning(
            f"🔴 Context at {usage_pct:.0%}{model_info}! "
            f"~{remaining:,} tokens remaining. "
            f"Compaction is imminent — protected facts will be preserved. "
            f"Use /pin to protect important messages."
        )
        _warned_90pct = True
        _warned_75pct = False  # Reset lower warning so it fires again after compaction
        return

    if usage_pct >= 0.75 and not _warned_75pct:
        emit_info(
            f"⚠️ Context at {usage_pct:.0%}{model_info}. "
            f"~{remaining:,} tokens remaining. "
            f"Compaction may occur soon. "
            f"Use /pin to mark important facts as protected, "
            f"or /context for detailed usage breakdown."
        )
        _warned_75pct = True
        return

    # Check message count approaching hard cap
    if message_count > 0 and hard_cap > 0:
        count_ratio = message_count / hard_cap
        if count_ratio >= 0.80 and not _warned_pre_compact and usage_pct < 0.75:
            remaining_msgs = hard_cap - message_count
            emit_info(
                f"📊 Approaching message limit ({message_count}/{hard_cap}). "
                f"~{remaining_msgs} messages before forced compaction. "
                f"Use /pin to protect key information."
            )
            _warned_pre_compact = True


def get_context_status_report(
    message_history: list[Any],
    model_name: str | None = None,
) -> str:
    """Generate a /context report: token usage, protected budget, compaction plan."""
    lines: list[str] = []

    try:
        from code_muse.agents._history import CompactionCache

        cache = CompactionCache()
        total_tokens = cache.sum_tokens(message_history, model_name=model_name)
        message_count = len(message_history)

        # Get model context
        try:
            from code_muse.plugins.task_context._context_utils import (
                get_cached_context_limit,
            )

            context_window = get_cached_context_limit(model_name)
        except Exception:
            context_window = 128_000

        # Get overhead — approximate since we don't have the live agent's
        # system prompt and tool schemas here
        overhead = 5000

        usage_pct = total_tokens / context_window if context_window > 0 else 0

        model_suffix = f" ({model_name})" if model_name else ""
        lines.append(f"📊 **Context Status**{model_suffix}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total tokens | {total_tokens:,} |")
        lines.append(f"| Context window | {context_window:,} |")
        lines.append(f"| Usage | {usage_pct:.1%} |")
        lines.append(f"| Remaining | {max(0, context_window - total_tokens):,} |")
        lines.append(f"| Messages | {message_count} |")
        lines.append(f"| Overhead (sys+tools) | ~{overhead:,} |")

        # Compaction threshold
        try:
            from code_muse.config.models import get_protected_token_count
            from code_muse.config.parser import (
                get_compaction_strategy,
                get_compaction_threshold,
            )

            threshold = get_compaction_threshold()
            strategy = get_compaction_strategy()
            protected_tokens = get_protected_token_count()
            lines.append(f"| Compaction threshold | {threshold:.0%} |")
            lines.append(f"| Compaction strategy | {strategy} |")
            lines.append(f"| Protected tokens | {protected_tokens:,} |")

            # Compaction plan
            if usage_pct >= threshold:
                lines.append("| **Compaction status** | **⚠️ IMMINENT** |")
                lines.append(f"| Strategy | {strategy} |")
                lines.append(f"| Will protect | ~{protected_tokens:,} recent tokens |")
            else:
                pct_to_threshold = (
                    ((threshold - usage_pct) / usage_pct) * 100 if usage_pct > 0 else 0
                )
                lines.append(
                    f"| To compaction threshold"
                    f" | ~{pct_to_threshold:.0f}% more tokens |"
                )
        except Exception:
            pass

        # Protected facts
        try:
            from code_muse.plugins.task_context.protected_facts import (
                get_protected_fact_manager,
            )

            mgr = get_protected_fact_manager()
            facts = mgr.get_all_facts()
            lines.append("")
            lines.append(f"**Protected Facts ({len(facts)}):**")
            if facts:
                for f in facts:
                    lines.append(f"  - [{f.category}] {f.content[:80]}")
                budget_pct = mgr.budget_used_pct
                lines.append(
                    f"  Budget: {mgr.used_tokens}/"
                    f"{mgr.max_budget_tokens:,} tokens ({budget_pct:.0%})"
                )
            else:
                lines.append("  (none — use /pin to add)")
        except Exception:
            pass

        # Message count cap
        try:
            from code_muse.config._dynamic_cap import compute_dynamic_message_cap

            cap = compute_dynamic_message_cap(model_max=context_window)
            if cap > 0:
                lines.append("")
                lines.append(f"Message cap: {message_count}/{cap}")
                if message_count / cap >= 0.75:
                    lines.append("⚠️ Approaching message count limit")
        except Exception:
            pass

    except Exception as e:
        lines.append(f"Error generating context report: {e}")

    return "\n".join(lines)


def get_pin_help() -> str:
    """Get help text for /pin command."""
    return (
        "/pin [content] — Protect a fact from compaction\n"
        "/pin last — Protect the last user message\n"
        "/pin list — List all protected facts\n"
        "/pin remove <content> — Remove a protected fact\n"
        "/pin clear — Remove all non-immutable protected facts\n"
        "/pin help — Show this help"
    )
