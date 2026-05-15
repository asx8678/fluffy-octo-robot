"""Muse Messaging System.

This package provides both the legacy messaging API and the new structured
messaging system.

Legacy API (backward compatible):
    - emit_info(), emit_warning(), emit_error(), etc.
    - MessageQueue, UIMessage, MessageType
    - Used by existing code throughout the codebase

New Structured Messaging API:
    - MessageBus for bidirectional Agent <-> UI communication
    - Pydantic message models (TextMessage, DiffMessage, etc.)
    - Command models for UI -> Agent communication
    - RichConsoleRenderer for presentation

Example (legacy):
    >>> from code_muse.messaging import emit_info, emit_error
    >>> emit_info("Operation complete")
    >>> emit_error("Something went wrong")

Example (new):
    >>> from code_muse.messaging import (
    ...     MessageBus, get_message_bus,
    ...     TextMessage, MessageLevel,
    ...     RichConsoleRenderer,
    ... )
    >>> bus = get_message_bus()
    >>> bus.emit(TextMessage(level=MessageLevel.INFO, text="Hello"))
"""

# =============================================================================
# Apply Rich Markdown patches (left-justified headers)
# =============================================================================
from .markdown_patches import patch_markdown_headings

patch_markdown_headings()

# =============================================================================
# Legacy API (backward compatible)
# =============================================================================

# Message bus
from .bus import (
    MessageBus,
    emit_shell_line,
    get_message_bus,
    get_session_context,
    reset_message_bus,
    set_session_context,
)
from .bus import emit as bus_emit  # Convenience functions (new API versions)
from .bus import emit_debug as bus_emit_debug
from .bus import emit_error as bus_emit_error
from .bus import emit_info as bus_emit_info
from .bus import emit_success as bus_emit_success
from .bus import emit_warning as bus_emit_warning

# Command types (UI -> Agent)
from .commands import (  # Base; Agent control; User interaction responses; Union type
    AnyCommand,
    BaseCommand,
    CancelAgentCommand,
    ConfirmationResponse,
    InterruptShellCommand,
    SelectionResponse,
    UserInputResponse,
)

# Legacy classes still importable for backward compat with tests
from .message_queue import (
    MessageQueue,
    MessageType,
    UIMessage,
    get_global_queue,
)

# ---- Adapter functions: legacy emit_* API backed by MessageBus ----


def get_buffered_startup_messages():
    return []


def emit_info(content, **metadata):
    bus_emit_info(str(content))


def emit_warning(content, **metadata):
    bus_emit_warning(str(content))


def emit_error(content, **metadata):
    bus_emit_error(str(content))


def emit_success(content, **metadata):
    bus_emit_success(str(content))


def emit_system_message(content, **metadata):
    get_message_bus().emit_text(
        MessageLevel.INFO, str(content), category=MessageCategory.SYSTEM
    )


def emit_divider(content="─" * 100, **metadata):
    get_message_bus().emit(DividerMessage(content=str(content)))


def emit_tool_output(content, tool_name=None, **metadata):
    bus_emit_info(str(content))


def emit_command_output(content, command=None, **metadata):
    bus_emit_info(str(content))


def emit_agent_reasoning(content, **metadata):
    bus_emit_info(str(content))


def emit_planned_next_steps(content, **metadata):
    bus_emit_info(str(content))


def emit_agent_response(content, **metadata):
    from .messages import AgentResponseMessage

    get_message_bus().emit(AgentResponseMessage(content=str(content)))


def emit_prompt(prompt_text, timeout=None):
    return str(prompt_text)


def provide_prompt_response(prompt_id, response):
    pass  # no-op


def emit_message(message_type, content, **metadata):
    """Generic message emitter — maps legacy MessageType to bus."""
    get_message_bus().emit(TextMessage(level=MessageLevel.INFO, text=str(content)))


# Message types and enums
from .messages import (  # Enums, Base, Text, File ops, Diff, Shell, Agent, etc.
    AgentReasoningMessage,
    AgentResponseMessage,
    AnyMessage,
    BaseMessage,
    ConfirmationRequest,
    DiffLine,
    DiffMessage,
    DividerMessage,
    FileContentMessage,
    FileEntry,
    FileListingMessage,
    GrepMatch,
    GrepResultMessage,
    MessageCategory,
    MessageLevel,
    SelectionRequest,
    ShellLineMessage,
    ShellOutputMessage,
    ShellStartMessage,
    SkillActivateMessage,
    SkillBackgroundMessage,
    SkillDeactivateMessage,
    SkillEntry,
    SkillListMessage,
    SpinnerControl,
    StatusPanelMessage,
    SubAgentInvocationMessage,
    SubAgentResponseMessage,
    SubAgentStatusMessage,
    TextMessage,
    UserInputRequest,
    VersionCheckMessage,
)

# Legacy: still importable for backward compat with tests
from .queue_console import QueueConsole, get_queue_console
from .renderers import InteractiveRenderer, SynchronousInteractiveRenderer

# Renderer
from .rich_renderer import (
    DEFAULT_STYLES,
    DIFF_STYLES,
    RendererProtocol,
    RichConsoleRenderer,
)
from .subagent_console import (
    STATUS_STYLES as SUBAGENT_STATUS_STYLES,
)

# Sub-agent console manager
from .subagent_console import (
    AgentState,
    SubAgentConsoleManager,
    get_subagent_console_manager,
)

# =============================================================================
# New Structured Messaging API
# =============================================================================


# =============================================================================
# Export all public symbols
# =============================================================================

__all__ = [
    # -------------------------------------------------------------------------
    # Legacy API (backward compatible)
    # -------------------------------------------------------------------------
    # Message queue
    "MessageQueue",
    "MessageType",
    "UIMessage",
    "get_global_queue",
    # Legacy emit functions
    "emit_message",
    "emit_info",
    "emit_success",
    "emit_warning",
    "emit_divider",
    "emit_error",
    "emit_tool_output",
    "emit_command_output",
    "emit_agent_reasoning",
    "emit_planned_next_steps",
    "emit_agent_response",
    "emit_system_message",
    "emit_prompt",
    "provide_prompt_response",
    "get_buffered_startup_messages",
    # Legacy renderers
    "InteractiveRenderer",
    "SynchronousInteractiveRenderer",
    "QueueConsole",
    "get_queue_console",
    # -------------------------------------------------------------------------
    # New Structured Messaging API
    # -------------------------------------------------------------------------
    # Enums
    "MessageLevel",
    "MessageCategory",
    # Base classes
    "BaseMessage",
    "BaseCommand",
    # Message types
    "TextMessage",
    "FileEntry",
    "FileListingMessage",
    "FileContentMessage",
    "GrepMatch",
    "GrepResultMessage",
    "DiffLine",
    "DiffMessage",
    "ShellStartMessage",
    "ShellLineMessage",
    "ShellOutputMessage",
    "emit_shell_line",
    "AgentReasoningMessage",
    "AgentResponseMessage",
    "SubAgentInvocationMessage",
    "SubAgentResponseMessage",
    "SubAgentStatusMessage",
    "UserInputRequest",
    "ConfirmationRequest",
    "SelectionRequest",
    "SpinnerControl",
    "DividerMessage",
    "StatusPanelMessage",
    "VersionCheckMessage",
    "SkillEntry",
    "SkillListMessage",
    "SkillActivateMessage",
    "SkillDeactivateMessage",
    "SkillBackgroundMessage",
    "AnyMessage",
    # Command types
    "CancelAgentCommand",
    "InterruptShellCommand",
    "UserInputResponse",
    "ConfirmationResponse",
    "SelectionResponse",
    "AnyCommand",
    # Message bus
    "MessageBus",
    "get_message_bus",
    "reset_message_bus",
    # Session context
    "set_session_context",
    "get_session_context",
    # New API convenience functions (prefixed to avoid collision)
    "bus_emit",
    "bus_emit_info",
    "bus_emit_warning",
    "bus_emit_error",
    "bus_emit_success",
    "bus_emit_debug",
    # Renderer
    "RendererProtocol",
    "RichConsoleRenderer",
    "DEFAULT_STYLES",
    "DIFF_STYLES",
    # Markdown patches
    "patch_markdown_headings",
    # Sub-agent console manager
    "AgentState",
    "SubAgentConsoleManager",
    "get_subagent_console_manager",
    "SUBAGENT_STATUS_STYLES",
]
