"""Dynamic message-count cap computation for history compaction.

Separated from parser.py to keep the 600-line cap and avoid circular imports
(the cap logic needs to know about context window tiers but doesn't need
the full config parser machinery).
"""

# Message-count caps by context-window tier.
# These scale with the model's context so large-window models
# aren't forced to compact prematurely (a 1M model can comfortably
# hold 200+ short messages), while small-window models compact sooner
# (each message is proportionally more expensive).
#
# The tiers mirror compute_effective_history_budget() in config/models.py.
_CONTEXT_CAP_TIERS: list[tuple[int, int]] = [
    # (context_floor, message_cap)
    (1_000_000, 200),  # >= 1M context: generous
    (100_000, 120),  # 100k–1M: relaxed
    (32_000, 50),  # 32k–100k: baseline
    (0, 30),  # < 32k: tight
]

# Absolute minimum — never go below this even if user overrides.
_MIN_CAP = 10


def compute_dynamic_message_cap(
    model_max: int | None = None,
    default: int = 50,
) -> int:
    """Return the max message count before forced compaction.

    When ``model_max`` is provided, the cap scales with the model's
    context window so that large-context models aren't forced to
    compact prematurely. The scaling uses the same tiered fractions
    as ``compute_effective_history_budget``:

    - < 32k:   30 messages  (tight)
    - 32k–100k: 50 messages  (baseline)
    - 100k–1M:  120 messages (relaxed)
    - >= 1M:   200 messages  (generous)

    Falls back to ``default`` when ``model_max`` is not provided
    or is invalid.

    Args:
        model_max: The model's context window in tokens.
        default: Fallback cap when model_max is unavailable.

    Returns:
        Maximum number of messages before forced compaction.
    """
    if model_max is None or model_max <= 0:
        return max(_MIN_CAP, default)

    for floor, cap in _CONTEXT_CAP_TIERS:
        if model_max >= floor:
            return max(_MIN_CAP, cap)

    return max(_MIN_CAP, default)  # unreachable, but defensive
