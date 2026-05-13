"""Register history store hooks for persisting compressed history across turns.

Hooks into agent_run_end to save compressed message history keyed by session_id.
The next turn in the same session can reload from this store.
"""

import logging

from code_muse.callbacks import register_callback
from code_muse.plugins.history_store.store import get_history_store

logger = logging.getLogger(__name__)


def _on_agent_run_end(
    agent_name: str | None = None,
    model_name: str | None = None,
    session_id: str | None = None,
    success: bool = True,
    error: BaseException | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Save compressed message history after each agent run."""
    if not success or not session_id:
        return

    try:
        # Get the current agent's message history
        from code_muse.agents.agent_manager import get_current_agent

        agent = get_current_agent()
        if agent is None:
            return

        history = agent.get_message_history()
        if not history:
            return

        # Store by session_id
        store = get_history_store()
        store.set(session_id, history)
        logger.debug(
            "Saved compressed history for session %s (%d messages)",
            session_id,
            len(history),
        )
    except Exception as e:
        logger.debug("Failed to save compressed history: %s", e)


def _on_message_history_processor_start(
    agent_name: str | None = None,
    session_id: str | None = None,
    message_history: list | None = None,
    incoming_messages: list | None = None,
) -> None:
    """No-op — could be used to restore from store in future."""
    pass


# Register callbacks
register_callback("agent_run_end", _on_agent_run_end)
register_callback(
    "message_history_processor_start", _on_message_history_processor_start
)

logger.debug("History Store plugin callbacks registered")
