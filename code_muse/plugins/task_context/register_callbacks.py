"""Callback registrations for the task_context plugin.

Registers hooks into the Muse runtime for task-aware context management:
- message_history_processor_start: evaluate context and prune near limits
- agent_run_end: detect task completion
- custom_command: /task command family
- custom_command_help: help entries for /task
- load_prompt: inject task-awareness instructions into system prompt
- startup: initialize task manager
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback

logger = logging.getLogger(__name__)

# Will be initialized on startup
_task_manager_instance = None


def _get_task_manager():
    """Lazy access to the singleton TaskManager."""
    global _task_manager_instance
    if _task_manager_instance is None:
        from code_muse.plugins.task_context.task_manager import TaskManager

        _task_manager_instance = TaskManager()
    return _task_manager_instance


# ---------------------------------------------------------------------------
# Startup hook
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Initialize the task manager on app boot."""
    _get_task_manager()
    logger.debug("Task Context plugin initialized")


# ---------------------------------------------------------------------------
# Message history hooks — pruning integration
# ---------------------------------------------------------------------------


def _on_message_history_processor_start(
    agent_name: str,
    session_id: str | None,
    message_history: list[Any],
    incoming_messages: list[Any],
) -> None:
    """Evaluate context before processing; trigger pruning if near limits.

    Modifies message_history in-place to remove pruned messages.
    """
    from code_muse.plugins.task_context.pruner import evaluate_and_prune

    manager = _get_task_manager()
    summary = evaluate_and_prune(manager, message_history)

    if summary and summary.decisions:
        # Apply prune decisions: remove archived/deleted messages in-place
        # Process in reverse order to preserve indices
        remove_indices = {
            d.message_index
            for d in summary.decisions
            if d.action in ("archive", "delete")
        }
        if remove_indices:
            # Tag new messages with active task BEFORE pruning
            # so the new task context is preserved
            manager.tag_recent_messages(message_history, count=0)

            # Remove messages in reverse index order
            for idx in sorted(remove_indices, reverse=True):
                if 0 <= idx < len(message_history):
                    del message_history[idx]

            # Tag messages again after pruning to refresh counters
            manager.tag_recent_messages(message_history, count=0)

            from code_muse.messaging import emit_success

            emit_success(
                f"🧹 Removed {len(remove_indices)} "
                f"stale message(s) from completed tasks"
            )

            logger.info(
                "Task pruning removed %d messages in-place",
                len(remove_indices),
            )


def _on_message_history_processor_end(
    agent_name: str,
    session_id: str | None,
    message_history: list[Any],
    messages_added: int,
    messages_filtered: int,
) -> None:
    """Post-processing: tag new messages with current task_id."""
    manager = _get_task_manager()
    if messages_added > 0:
        manager.tag_recent_messages(message_history, count=messages_added)


# ---------------------------------------------------------------------------
# Agent run lifecycle
# ---------------------------------------------------------------------------


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Detect task completion signals after an agent run."""
    if not success:
        return
    from code_muse.plugins.task_context.completion import detect_completion

    manager = _get_task_manager()
    signal = detect_completion(manager, response_text or "")
    if signal.detected and signal.confidence > 0.6:
        manager.complete_current_task(outcome=signal.outcome_summary)


# ---------------------------------------------------------------------------
# /task slash command family
# ---------------------------------------------------------------------------


def _handle_task_command(command: str, name: str) -> bool | str | None:
    """Handle ``/task`` subcommands."""
    if name != "task":
        return None

    from code_muse.messaging import emit_info, emit_success, emit_warning
    from code_muse.plugins.task_context.config import (
        get_task_config_summary,
        get_task_prune_enabled,
        set_task_prune_enabled,
    )

    manager = _get_task_manager()
    tokens = command.strip().split(maxsplit=2)
    sub = tokens[1].strip().lower() if len(tokens) > 1 else "status"

    if sub == "new":
        label = tokens[2].strip() if len(tokens) > 2 else ""
        task_id = manager.start_new_task(label=label or None)
        display = f" '{label}'" if label else ""
        emit_success(f"📋 New task{display} started — ID: {task_id[:8]}")
        return True

    if sub == "complete":
        outcome = tokens[2].strip() if len(tokens) > 2 else None
        summary = manager.complete_current_task(outcome=outcome)
        active = manager.get_active_task()
        if summary:
            emit_success(f"✅ Task completed — {summary}")
        if active:
            emit_info(f"📋 Active task: {active.label or active.task_id[:8]}")
        return True

    if sub == "status":
        active = manager.get_active_task()
        completed = manager.get_completed_tasks()
        lines = ["📋 Task Context Status:"]
        if active:
            lines.append(f"  Active: {active.label or active.task_id[:8]}")
            lines.append(
                f"    Messages: {active.message_count}, Tokens: ~{active.token_count}"
            )
        else:
            lines.append("  Active: (none)")
        if completed:
            lines.append(f"  Completed: {len(completed)} task(s)")
            for t in completed[-3:]:  # Show last 3
                lines.append(
                    f"    • {t.label or t.task_id[:8]}"
                    f" — {t.outcome_summary or 'no summary'}"
                )
        else:
            lines.append("  Completed: (none)")
        lines.append(f"  Pruning: {'ON' if get_task_prune_enabled() else 'OFF'}")
        return "\n".join(lines)

    if sub == "list":
        all_tasks = manager.get_all_tasks()
        lines = ["📋 All Tasks:"]
        for t in all_tasks:
            status_icon = {"active": "▶", "completed": "✓", "archived": "🗄"}
            icon = status_icon.get(t.status.value, "•")
            lines.append(
                f"  {icon} [{t.task_id[:8]}] {t.label or '(untitled)'} "
                f"— {t.status.value}, {t.message_count} msgs"
            )
        return "\n".join(lines)

    if sub == "prune-now":
        from code_muse.plugins.task_context.pruner import force_prune

        summary = force_prune(manager)
        emit_success(
            f"🧹 Pruned {summary.deleted_count + summary.archived_count} messages, "
            f"saved ~{summary.tokens_saved} tokens"
        )
        return True

    if sub == "forget":
        if len(tokens) < 3:
            emit_warning("Usage: /task forget <task_id>")
            return True
        task_id_to_forget = tokens[2].strip()
        from code_muse.plugins.task_context.archival import delete_archive

        deleted = delete_archive(task_id_to_forget)
        if deleted:
            emit_success(
                f"🗑️ Permanently deleted archived context"
                f" for task {task_id_to_forget[:8]}"
            )
        else:
            emit_warning(f"No archive found for task {task_id_to_forget[:8]}")
        return True

    if sub == "recall":
        if len(tokens) < 3:
            emit_warning("Usage: /task recall <task_id>")
            return True
        task_id_to_recall = tokens[2].strip()
        from code_muse.plugins.task_context.archival import recall_task_context

        messages = recall_task_context(task_id_to_recall)
        if messages:
            emit_success(
                f"📂 Recalled {len(messages)} messages"
                f" from task {task_id_to_recall[:8]}"
            )
        else:
            emit_warning(f"No archived context found for task {task_id_to_recall[:8]}")
        return True

    if sub == "config":
        return get_task_config_summary()

    if sub == "on":
        set_task_prune_enabled(True)
        emit_success("Task-aware pruning enabled")
        return True

    if sub == "off":
        set_task_prune_enabled(False)
        emit_info("Task-aware pruning disabled")
        return True

    emit_info(
        "Usage: /task new|complete|status|list|prune-now|recall|forget|config|on|off"
    )
    return True


def _on_help() -> list[tuple[str, str]]:
    """Return help entries for /task."""
    return [
        ("task new [label]", "Start a new task with optional label"),
        ("task complete [outcome]", "Mark current task as done"),
        ("task status", "Show active task + completed task stats"),
        ("task list", "List all tasks in session"),
        ("task prune-now", "Force immediate pruning pass"),
        ("task recall <id>", "Recall archived task context"),
        ("task forget <id>", "Delete archived context permanently"),
        ("task config", "Show task pruning configuration"),
        ("task on|off", "Enable/disable task-aware pruning"),
    ]


# ---------------------------------------------------------------------------
# Load prompt hook — inject task-awareness instructions
# ---------------------------------------------------------------------------


def _get_task_prompt() -> str | None:
    """Return task-awareness instructions for the system prompt."""
    from code_muse.plugins.task_context.config import get_task_prune_enabled

    if not get_task_prune_enabled():
        return None
    return """\
## Task-Aware Context Management

The system automatically tracks conversation tasks to keep context focused.
Each message is tagged with its originating task. When a task is completed,
its associated context is pruned or archived to free tokens for new work.

You can manage tasks explicitly:
- Use `/task new <label>` to start a new task
- Use `/task complete <outcome>` when you finish a task
- The system auto-detects task switches and completion when possible

This keeps your context clean and relevant to the current task."""


# ---------------------------------------------------------------------------
# Public registration entry point
# ---------------------------------------------------------------------------


def register_all_callbacks() -> None:
    """Register all hooks for the task_context plugin.

    Called at module import time by the plugin loader.
    """
    register_callback("startup", _on_startup)
    register_callback(
        "message_history_processor_start", _on_message_history_processor_start
    )
    register_callback(
        "message_history_processor_end", _on_message_history_processor_end
    )
    register_callback("agent_run_end", _on_agent_run_end)
    register_callback("custom_command", _handle_task_command)
    register_callback("custom_command_help", _on_help)
    register_callback("load_prompt", _get_task_prompt)

    logger.debug("Task Context plugin callbacks registered")


# Module-level auto-registration (standard plugin pattern)
register_all_callbacks()
