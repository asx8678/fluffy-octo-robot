"""Mode cycling logic and UI emission.

Provides a ``cycle_mode()`` function that rotates through the three
plan-mode states.  A ``/mode`` slash command exposes this in the UI.

TODO: Shift+Tab key-binding integration requires future prompt_toolkit
hooking (not implemented here to avoid core changes).
"""

from code_muse.messaging import emit_info
from code_muse.plugins.plan_mode.plan_mode_tools import (
    PlanModeState,
    get_current_mode,
    set_plan_mode,
)

# Cyclic ordering: DEFAULT → AUTO_EDIT → PLAN → DEFAULT
_MODE_CYCLE = [
    PlanModeState.DEFAULT,
    PlanModeState.AUTO_EDIT,
    PlanModeState.PLAN,
]


def cycle_mode() -> PlanModeState:
    """Advance to the next mode in the cycle and emit a UI indicator.

    Returns:
        The new active mode.
    """
    current = get_current_mode()
    try:
        idx = _MODE_CYCLE.index(current)
    except ValueError:
        idx = 0
    next_idx = (idx + 1) % len(_MODE_CYCLE)
    new_mode = _MODE_CYCLE[next_idx]
    set_plan_mode(new_mode)
    emit_info(f"🔁 Mode cycled to: {new_mode.value}")
    return new_mode
