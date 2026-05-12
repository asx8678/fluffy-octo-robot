"""
Plugin Example: Hook Monitor
Monitors and logs specific tool hook events to the console.
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info

logger = logging.getLogger(__name__)


async def _on_pre_tool_call(tool_name: str, tool_args: Any, context: Any = None) -> Any:
    # Use emit_info from messaging to show in TUI
    emit_info(f"🚀 About to call tool: {tool_name}")
    return None


async def _on_post_tool_call(
    tool_name: str,
    tool_args: Any,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> Any:
    emit_info(f"✅ Tool {tool_name} finished in {duration_ms:.2f}ms")
    return None


# Register hooks
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("post_tool_call", _on_post_tool_call)

logger.info("Hook Monitor plugin registered")
