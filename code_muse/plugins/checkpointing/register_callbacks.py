"""Register checkpointing callbacks and commands."""

import logging

from code_muse.callbacks import register_callback
from code_muse.plugins.checkpointing.checkpoint_hook import (
    on_pre_tool_call_checkpoint,
)
from code_muse.plugins.checkpointing.restore_command import (
    _custom_help,
    _handle_custom_command,
)
from code_muse.plugins.checkpointing.rewind_shortcut import RewindKeyListener

logger = logging.getLogger(__name__)

_rewind_listener: RewindKeyListener | None = None


def _start_rewind_listener() -> None:
    global _rewind_listener
    if _rewind_listener is not None:
        return

    def _on_double_esc() -> None:
        from code_muse.plugins.checkpointing.restore_command import (
            _handle_restore_command,
        )

        _handle_restore_command("/restore")

    _rewind_listener = RewindKeyListener(_on_double_esc)
    _rewind_listener.start()


def _stop_rewind_listener() -> None:
    global _rewind_listener
    if _rewind_listener is not None:
        _rewind_listener.stop()
        _rewind_listener = None


def _on_shutdown() -> None:
    _stop_rewind_listener()


# Register callbacks
register_callback("pre_tool_call", on_pre_tool_call_checkpoint)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_custom_command)
register_callback("shutdown", _on_shutdown)
