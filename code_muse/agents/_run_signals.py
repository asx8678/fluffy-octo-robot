"""Factory helpers for key-listener callbacks used by ``run``.

Provides thread-safe cancel scheduling and steer-injection plumbing
for the agent runtime.

Extracted from ``_runtime.py`` to keep that module focused.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from code_muse.messaging import emit_info, emit_warning


def make_schedule_cancel(
    agent_task: "asyncio.Task[Any]",
    loop: asyncio.AbstractEventLoop,
) -> Callable[[], None]:
    """Build the ``schedule_agent_cancel`` callback for the key listener."""

    def schedule_agent_cancel() -> None:
        from code_muse.tools.command_runner import _RUNNING_PROCESSES

        if _RUNNING_PROCESSES:
            emit_warning(
                "Refusing to cancel Agent while a shell command is running — "
                "press Ctrl+X to cancel the shell command."
            )
            return
        if agent_task.done():
            return
        try:
            from code_muse.tools.agent_tools import _active_subagent_tasks_var

            active_tasks = _active_subagent_tasks_var.get()
        except LookupError:
            active_tasks = set()
        if active_tasks:
            emit_warning(f"Cancelling {len(active_tasks)} active subagent task(s)...")
            for task in list(active_tasks):
                if not task.done():
                    loop.call_soon_threadsafe(task.cancel)
        loop.call_soon_threadsafe(agent_task.cancel)

    return schedule_agent_cancel


def drain_pause_state_on_cancel() -> None:
    """Clear any leftover state when a run is cancelled.

    Stub: pause controller not yet ported to fluffy-octo-robot.
    """
    pass


def reset_pause_state_at_run_start() -> None:
    """Scrub stale state before a fresh agent run.

    Stub: pause controller not yet ported to fluffy-octo-robot.
    """
    pass


__all__ = [
    "drain_pause_state_on_cancel",
    "make_schedule_cancel",
    "reset_pause_state_at_run_start",
]
