"""Checkpointing + Rewind plugin for Muse."""

from code_muse.plugins.checkpointing.checkpoint_hook import (
    on_pre_tool_call_checkpoint,
)
from code_muse.plugins.checkpointing.conversation_snapshots import (
    create_snapshot,
    list_snapshots,
    load_snapshot,
)
from code_muse.plugins.checkpointing.restore_command import (
    _handle_restore_command,
)
from code_muse.plugins.checkpointing.rewind_shortcut import (
    DoublePressDetector,
    RewindKeyListener,
)
from code_muse.plugins.checkpointing.shadow_git import ShadowGit

__all__ = [
    "ShadowGit",
    "create_snapshot",
    "load_snapshot",
    "list_snapshots",
    "on_pre_tool_call_checkpoint",
    "_handle_restore_command",
    "DoublePressDetector",
    "RewindKeyListener",
]
