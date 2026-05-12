"""Pre-tool-call hook for automatic checkpointing."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def on_pre_tool_call_checkpoint(
    tool_name: str, tool_args: dict[str, Any]
) -> None:
    """Callback registered for pre_tool_call — fires-and-forget checkpoint."""
    if tool_name not in ("write_file", "replace_in_file"):
        return None

    # Fire-and-forget checkpoint (don't await in a way that blocks)
    asyncio.create_task(_create_checkpoint_async(tool_name, tool_args))
    return None


async def _create_checkpoint_async(tool_name: str, tool_args: dict[str, Any]) -> None:
    try:
        import os

        from code_muse.agents import get_current_agent
        from code_muse.plugins.checkpointing.conversation_snapshots import (
            create_snapshot,
        )
        from code_muse.plugins.checkpointing.shadow_git import ShadowGit

        project_root = os.getcwd()

        shadow = ShadowGit(project_root)
        affected_files = _extract_affected_files(tool_name, tool_args)
        commit_hash = shadow.create_checkpoint(tool_name, affected_files)

        agent = get_current_agent()
        snapshot_path = create_snapshot(
            agent, tool_name, str(tool_args.get("tool_call_id", ""))
        )

        logger.info(f"Checkpoint created: {commit_hash}, snapshot: {snapshot_path}")
    except Exception as exc:
        logger.error(f"Checkpoint failed: {exc}")


def _extract_affected_files(tool_name: str, tool_args: dict[str, Any]) -> list[str]:
    if tool_name == "write_file" or tool_name == "replace_in_file":
        return [tool_args.get("file_path", "")]
    return []
