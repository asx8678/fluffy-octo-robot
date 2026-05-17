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
    Now model-aware: budgets are calibrated to the actual model context window.
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

    # Proactive budget warning AFTER pruning, WITH model awareness
    from code_muse.plugins.task_context.budget import (
        check_and_warn,
        estimate_current_budget,
    )
    from code_muse.plugins.task_context.config import (
        get_task_budget_critical_at,
        get_task_budget_warn_at,
    )

    # Resolve model name
    try:
        from code_muse.config.models import get_global_model_name

        model_name = get_global_model_name()
    except Exception:
        model_name = None

    # Update protected fact manager context window
    try:
        from code_muse.plugins.task_context._context_utils import (
            get_cached_context_limit,
        )
        from code_muse.plugins.task_context.protected_facts import (
            get_protected_fact_manager,
        )

        ctx = get_cached_context_limit(model_name)
        mgr = get_protected_fact_manager()
        mgr.update_context_window(ctx)
    except Exception:
        pass

    budget_info = estimate_current_budget(message_history, model_name=model_name)
    check_and_warn(
        budget_info,
        warn_at=get_task_budget_warn_at(),
        critical_at=get_task_budget_critical_at(),
        model_name=model_name,
    )

    # Check for long pasted documents in incoming messages
    try:
        from code_muse.plugins.task_context.document_store import (
            is_long_document,
            store_long_document,
        )

        for msg in incoming_messages:
            for part in getattr(msg, "parts", []) or []:
                content = getattr(part, "content", None)
                if isinstance(content, str) and is_long_document(content):
                    doc = store_long_document(content)
                    if doc:
                        from code_muse.messaging import emit_info

                        emit_info(
                            f"📄 Long document detected "
                            f"({doc.word_count:,} words, "
                            f"{doc.section_count} sections). "
                            f"Stored externally. Use "
                            f"/doc get {doc.doc_id[:12]} to retrieve."
                        )
                        # Replace in-place
                        part.content = doc.reference_stub
                        # Add as protected fact
                        from code_muse.plugins.task_context.protected_facts import (
                            ProtectedFact,
                            get_protected_fact_manager,
                        )

                        mgr = get_protected_fact_manager()
                        mgr.add_fact(
                            ProtectedFact(
                                content=f"Document reference: {doc.title} "
                                f"({doc.doc_id[:12]}) - {doc.word_count:,} words",
                                category="document_reference",
                                priority=1,
                                token_cost=50,
                            )
                        )
    except Exception:
        pass

    # Auto-populate cross-references from file overlap
    from code_muse.plugins.task_context.dependencies import (
        sync_cross_references,
    )

    sync_cross_references(manager)


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
    """Detect task completion signals after an agent run.

    When experience retrieval is enabled, also creates an experience
    capsule from the completed task.
    """
    if not success:
        return
    from code_muse.plugins.task_context.completion import detect_completion
    from code_muse.plugins.task_context.config import (
        get_experience_retrieval_enabled,
    )

    manager = _get_task_manager()
    signal = detect_completion(manager, response_text or "")
    if signal.detected and signal.confidence > 0.6:
        manager.complete_current_task(outcome=signal.outcome_summary)

        # Capture experience capsule if enabled
        if get_experience_retrieval_enabled():
            _capture_experience(manager, signal)

    # Reset budget warning flags on task completion so fresh warnings
    # can be emitted as usage climbs again.
    from code_muse.plugins.task_context.budget import reset_warning_flags

    reset_warning_flags()


# ---------------------------------------------------------------------------
# /task slash command family
# ---------------------------------------------------------------------------


def _capture_experience(manager: Any, signal: Any) -> None:
    """Create an experience capsule from a completed task."""
    try:
        from code_muse.plugins.task_context.experience_store import (
            create_capsule_from_task,
        )

        active = manager.get_active_task()
        if not active:
            return

        create_capsule_from_task(
            task_id=active.task_id,
            task_label=active.label,
            outcome_summary=signal.outcome_summary or active.outcome_summary,
            summary=signal.outcome_summary or "",
            token_estimate=active.token_count,
            source_archive_path="",
            metadata={"auto_captured": True},
        )
        logger.debug(
            "Captured experience capsule for task '%s'",
            active.label or active.task_id[:8],
        )
    except Exception as exc:
        logger.warning("Failed to capture experience capsule: %s", exc)


# ---------------------------------------------------------------------------
# Experience injection into message history
# ---------------------------------------------------------------------------

# Track injected queries per session to avoid duplicate injections
_injected_queries: set[int] = set()


def _on_message_history_processor_start_with_experience(
    agent_name: str,
    session_id: str | None,
    message_history: list[Any],
    incoming_messages: list[Any],
) -> None:
    """Inject relevant experience capsules into incoming messages if enabled.

    Precedes the existing pruning logic. When experience retrieval is
    enabled, extracts the user's query from incoming messages, searches
    for similar past capsules, and prepends a compact context note.
    """
    from code_muse.plugins.task_context.config import (
        get_experience_max_results,
        get_experience_retrieval_enabled,
    )

    if not get_experience_retrieval_enabled():
        return

    if not incoming_messages:
        return

    # Extract query text from incoming messages
    query_text = _extract_query_from_messages(incoming_messages)
    if not query_text:
        return

    # Deduplicate injection per query
    query_hash = hash(query_text)
    if query_hash in _injected_queries:
        return
    _injected_queries.add(query_hash)

    # Search for similar capsules
    from code_muse.plugins.task_context.experience_store import search_experience

    results = search_experience(
        query=query_text,
        top_k=get_experience_max_results(),
        min_similarity=0.4,  # Higher threshold for auto-injection
    )

    if not results:
        return

    # Build compact injection message
    injection_lines = ["Relevant past experience capsules:"]
    for capsule, _similarity in results:
        injection_lines.append(
            f"- [{capsule.capsule_id[:8]}] "
            f"{capsule.task_label}: {capsule.outcome_summary[:150]}"
        )
    injection_text = "\n".join(injection_lines)

    # Try to inject as a pydantic-ai UserPromptPart
    try:
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        experience_msg = ModelRequest(parts=[UserPromptPart(content=injection_text)])
        incoming_messages.insert(0, experience_msg)
    except ImportError:
        # Fallback: prepend as a simple dict
        incoming_messages.insert(0, {"role": "user", "content": injection_text})

    logger.debug(
        "Injected %d experience capsule(s) for query '%s'",
        len(results),
        query_text[:50],
    )


def _extract_query_from_messages(messages: list[Any]) -> str:
    """Extract the user's query text from incoming messages."""
    from code_muse.plugins.task_context._text_utils import _extract_text

    parts: list[str] = []
    for msg in messages:
        text = _extract_text(msg)
        if text and len(text) > 5:  # Skip very short messages
            parts.append(text)
    return " ".join(parts)[:500]  # Truncate for perf


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
        # No args: list recent completed tasks
        if len(tokens) < 3:
            completed = manager.get_completed_tasks()
            archived = manager.get_archived_tasks()
            recent = (completed + archived)[-5:]
            lines = [
                "📋 Recent completed/archived tasks (use /task recall <id or label>):"
            ]
            for t in recent:
                lines.append(
                    f"  • {t.task_id[:8]} — {t.label or '(untitled)'}"
                    f": {t.outcome_summary or 'no outcome'}"
                )
            if not recent:
                lines.append("  (none yet)")
            return "\n".join(lines)

        task_id_to_recall = tokens[2].strip()
        task = _fuzzy_match_task(manager, task_id_to_recall)
        if not task:
            emit_warning(f"No task found matching '{task_id_to_recall}'")
            return True

        # Cost preview + dependency info
        from code_muse.plugins.task_context.dependencies import get_task_files

        # Try to get archive metadata for token count
        archive_tokens = task.token_count
        msg_count = task.message_count
        from code_muse.plugins.task_context.archival import _archive_path

        archive_path = _archive_path(task.task_id)
        if archive_path.exists():
            try:
                import json

                with open(archive_path) as f:
                    archive_data = json.load(f)
                msg_count = archive_data.get("message_count", msg_count)
                archive_tokens = archive_data.get("token_count", archive_tokens)
            except json.JSONDecodeError, OSError:
                pass

        # Build recall info with cost preview and cross-references
        xrefs = manager.get_cross_referenced_tasks(task.task_id)
        files_touched = get_task_files(task.task_id)

        lines = [
            f"📂 Recalled task: {task.label or task.task_id[:8]}",
            f"  Status: {task.status.value}",
            f"  Outcome: {task.outcome_summary or 'No outcome recorded'}",
            f"  Messages: {msg_count}, Tokens: ~{archive_tokens:,}",
        ]
        if xrefs:
            lines.append("  Related tasks:")
            for xref in xrefs:
                lines.append(
                    f"    • {xref.label or xref.task_id[:8]}"
                    f" — {xref.outcome_summary or ''}".rstrip(" —")
                )
        if files_touched:
            file_list = sorted(files_touched)[:5]
            suffix = (
                f" (+{len(files_touched) - 5} more)" if len(files_touched) > 5 else ""
            )
            lines.append(f"  Files touched: {', '.join(file_list)}{suffix}")

        emit_info("\n".join(lines))
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


def _fuzzy_match_task(manager: Any, partial_id: str) -> Any | None:
    """Fuzzy match a task by partial ID prefix, label, or outcome.

    Tries in order:
    1. Exact prefix match on task_id
    2. Substring match on label (case-insensitive)
    3. Substring match on outcome_summary (case-insensitive)
    """
    all_tasks = manager.get_all_tasks()
    # 1. Exact prefix match on task_id
    for t in all_tasks:
        if t.task_id.startswith(partial_id):
            return t
    # 2. Label substring match
    lowered = partial_id.lower()
    for t in all_tasks:
        if t.label and lowered in t.label.lower():
            return t
    # 3. Outcome substring match (completed tasks only)
    for t in all_tasks:
        if t.outcome_summary and lowered in t.outcome_summary.lower():
            return t
    return None


def _handle_doc_command(command: str, name: str) -> str | bool | None:
    """Handle /doc get|section|list|summary|clear|help commands."""
    if name != "doc":
        return None

    from code_muse.messaging import emit_error

    tokens = command.strip().split(maxsplit=3)
    sub = tokens[1].strip().lower() if len(tokens) > 1 else "help"

    try:
        from code_muse.plugins.task_context.document_store import (
            get_document_store,
            reset_document_store,
        )

        store = get_document_store()

        if sub == "help":
            return (
                "/doc get <id> — retrieve full document by ID\n"
                "/doc section <id> <n> — retrieve section N of document\n"
                "/doc summary <id> — 3-bullet summary of document\n"
                "/doc list — list stored documents\n"
                "/doc clear — clear all stored documents"
            )

        if sub == "list":
            docs = store.list_documents()
            if not docs:
                return "No documents stored."
            lines = ["Stored documents:"]
            for d in docs:
                lines.append(
                    f"  {d['doc_id']}: {d['title']} "
                    f"({d['words']:,} words, {d['sections']} sections)"
                )
            return "\n".join(lines)

        if sub == "clear":
            reset_document_store()
            return "Document store cleared."

        if sub in ("get", "section", "summary"):
            doc_id = tokens[2].strip() if len(tokens) > 2 else ""
            if not doc_id:
                return "Usage: /doc get|section|summary <id> [section_number]"

            if sub == "get":
                doc = store.get_document(doc_id)
                if doc:
                    # Load content from disk if needed
                    if not doc.content:
                        content_path = store._get_content_path(doc.doc_id)
                        if content_path.exists():
                            doc.content = content_path.read_text()
                    preview = doc.content[:500]
                    suffix = "..." if len(doc.content) > 500 else ""
                    return (
                        f"Document: {doc.title}\n{preview}{suffix}\n\n"
                        f"Full content at: {store._get_content_path(doc.doc_id)}"
                    )
                return f"Document not found: {doc_id}"

            if sub == "section":
                section_num = int(tokens[3]) if len(tokens) > 3 else 1
                section = store.get_section(doc_id, section_num)
                if section:
                    return (
                        f"Section {section.section_number}: "
                        f"{section.heading}\n{section.content[:1000]}"
                    )
                return f"Section {section_num} not found in {doc_id}"

            if sub == "summary":
                summary = store.get_document_summary(doc_id)
                if summary:
                    return f"Summary of document {doc_id}:\n{summary}"
                return f"Document not found: {doc_id}"

        return f"Unknown subcommand: {sub}. Use /doc help."
    except Exception as e:
        emit_error(f"/doc command failed: {e}")
        return True


def _handle_experience_command(command: str, name: str) -> bool | str | None:
    """Handle ``/experience`` subcommands via custom_command hook."""
    if name != "experience":
        return None
    from code_muse.plugins.task_context.experience_commands import (
        handle_experience_command,
    )

    return handle_experience_command(command)


def _on_help() -> list[tuple[str, str]]:
    """Return help entries for /task, /doc, and /experience."""
    from code_muse.plugins.task_context.experience_commands import (
        get_experience_help,
    )

    task_help = [
        ("task new [label]", "Start a new task with optional label"),
        ("task complete [outcome]", "Mark current task as done"),
        ("task status", "Show active task + completed task stats"),
        ("task list", "List all tasks in session"),
        ("task prune-now", "Force immediate pruning pass"),
        ("task recall [id|label]", "Recall archived task context (fuzzy match)"),
        ("task forget <id>", "Delete archived context permanently"),
        ("task config", "Show task pruning configuration"),
        ("task on|off", "Enable/disable task-aware pruning"),
        ("doc get <id>", "Retrieve full stored document by ID"),
        ("doc section <id> <n>", "Retrieve section N of a stored document"),
        ("doc summary <id>", "3-bullet summary of stored document"),
        ("doc list", "List all stored documents"),
    ]
    return task_help + get_experience_help()


# ---------------------------------------------------------------------------
# Load prompt hook — inject task-awareness instructions
# ---------------------------------------------------------------------------


def _get_task_prompt() -> str | None:
    """Return task-awareness + experience instructions for the system prompt."""
    from code_muse.plugins.task_context.config import (
        get_experience_retrieval_enabled,
        get_task_prune_enabled,
    )

    parts: list[str] = []

    if get_task_prune_enabled():
        parts.append("""\
## Task-Aware Context Management

The system automatically tracks conversation tasks to keep context focused.
Each message is tagged with its originating task. When a task is completed,
its associated context is pruned or archived to free tokens for new work.

You can manage tasks explicitly:
- Use `/task new <label>` to start a new task
- Use `/task complete <outcome>` when you finish a task
- The system auto-detects task switches and completion when possible

This keeps your context clean and relevant to the current task.""")

    if get_experience_retrieval_enabled():
        parts.append("""\
## Semantic Experience Store

The system has a memory of past solved problems ("experience capsules").
When you start a new task, similar past solutions may appear as
"Relevant past experience capsules" in your context. Use these as
starting points to avoid re-solving previously solved problems.

Manage experiences:
- `/experience status` — show store configuration & stats
- `/experience search <query>` — search past experiences
- `/experience backfill` — create capsules from existing archives
- `/experience forget <id>` — remove a capsule""")

    return "\n\n".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Public registration entry point
# ---------------------------------------------------------------------------


def register_all_callbacks() -> None:
    """Register all hooks for the task_context plugin.

    Called at module import time by the plugin loader.
    """
    register_callback("startup", _on_startup)
    register_callback(
        "message_history_processor_start",
        _on_message_history_processor_start_with_experience,
    )
    register_callback(
        "message_history_processor_start", _on_message_history_processor_start
    )
    register_callback(
        "message_history_processor_end", _on_message_history_processor_end
    )
    register_callback("agent_run_end", _on_agent_run_end)
    register_callback("custom_command", _handle_task_command)
    register_callback("custom_command", _handle_doc_command)
    register_callback("custom_command", _handle_experience_command)
    register_callback("custom_command_help", _on_help)
    register_callback("load_prompt", _get_task_prompt)

    logger.debug("Task Context plugin callbacks registered")


# Module-level auto-registration (standard plugin pattern)
register_all_callbacks()
