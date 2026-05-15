"""Pruning orchestrator for task-aware context management.

Implements the dynamic pruning algorithm that surgically removes
irrelevant completed-task messages before forced summarization runs.

Algorithm (triggered at PRUNE_AT_PERCENT = 85% of token budget):
1. Identify the current active task_id
2. Score all non-active-task messages for relevance
3. Low relevance + completed task → DELETE
4. Medium relevance + completed task → ARCHIVE
5. High relevance + anything → KEEP
6. Always keep active task messages
7. Rebuild prompt with cleaned context
"""

import logging
from typing import Any

from code_muse.messaging import emit_info, emit_success
from code_muse.plugins.task_context._text_utils import _extract_text
from code_muse.plugins.task_context.archival import archive_messages_for_task
from code_muse.plugins.task_context.config import (
    get_task_prune_aggressiveness,
    get_task_prune_enabled,
    get_task_prune_threshold,
)
from code_muse.plugins.task_context.models import (
    PruneAction,
    PruneDecision,
    PruneSummary,
    TaskStatus,
)
from code_muse.plugins.task_context.scorer import score_batch_relevance

logger = logging.getLogger(__name__)

# Default relevance thresholds
_LOW_RELEVANCE_THRESHOLD = 0.3
_MEDIUM_RELEVANCE_THRESHOLD = 0.6


def evaluate_and_prune(
    task_manager: Any,
    message_history: list[Any],
    token_budget: int | None = None,
    context_overhead: int = 0,
) -> PruneSummary | None:
    """Evaluate the current context and prune if near token limits.

    This is the main entry point called from message_history_processor_start.

    Args:
        task_manager: The TaskManager instance.
        message_history: The current message history list.
        token_budget: Optional total token budget (model context window).
        context_overhead: Optional overhead for system prompt + tools.

    Returns:
        PruneSummary if pruning was performed, None if no action needed.
    """
    # Gate: pruning must be enabled
    if not get_task_prune_enabled():
        return None

    # Gate: must have messages to evaluate
    if not message_history or len(message_history) <= 1:
        return None

    # Estimate tokens if budget provided
    if token_budget is not None:
        total_tokens = _estimate_total_tokens(message_history)
        utilization = (total_tokens + context_overhead) / max(token_budget, 1)
        threshold = get_task_prune_threshold()
        if utilization < threshold:
            return None  # No need to prune yet

        emit_info(
            f"🧹 Context at {utilization:.0%} — "
            f"evaluating completed-task messages for pruning..."
        )

    # Perform the pruning evaluation
    return _run_prune_pass(task_manager, message_history)


def force_prune(task_manager: Any) -> PruneSummary:
    """Force an immediate pruning pass regardless of token utilization.

    Called from the /task prune-now slash command.

    Args:
        task_manager: The TaskManager instance.

    Returns:
        PruneSummary with the results.
    """
    # We need message history to prune — this is a best-effort call
    # that returns an empty summary if no messages available
    from code_muse.agents.agent_manager import get_current_agent

    agent = get_current_agent()
    if not agent:
        logger.warning("force_prune: no active agent")
        return PruneSummary()

    message_history = agent.get_message_history()
    if not message_history:
        return PruneSummary()

    return _run_prune_pass(task_manager, message_history)


def _run_prune_pass(
    task_manager: Any,
    message_history: list[Any],
) -> PruneSummary:
    """Execute a single pruning pass on the message history.

    This is the core algorithm implementation.

    Steps:
    1. Get active task and task_id
    2. Build a map of message_index -> task_id from TaskManager
    3. Score each non-active-task message for relevance
    4. Make pruning decisions based on score + task status + aggressiveness
    5. Apply decisions: remove/archive messages
    6. Return summary of what was done
    """
    active_task = task_manager.get_active_task()
    active_task_id = active_task.task_id if active_task else None
    aggressiveness = get_task_prune_aggressiveness()

    # Get task message indices for each task
    completed_task_ids = {t.task_id for t in task_manager.get_completed_tasks()}

    # Build a list of messages with their task info
    message_entries: list[dict] = []
    for idx, msg in enumerate(message_history):
        task_id = task_manager.get_task_for_message(idx)
        task = task_manager.get_task(task_id) if task_id else None
        message_entries.append(
            {
                "index": idx,
                "message": msg,
                "task_id": task_id,
                "task_status": task.status if task else None,
                "is_active": task_id == active_task_id,
                "is_completed": task_id in completed_task_ids if task_id else False,
            }
        )

    # Score relevance for non-active messages
    non_active_entries = [e for e in message_entries if not e["is_active"]]
    active_messages = [
        msg
        for entry in message_entries
        for msg in ([entry["message"]] if entry["is_active"] else [])
    ]

    if non_active_entries:
        active_label = active_task.label if active_task else ""
        scores = score_batch_relevance(
            [e["message"] for e in non_active_entries],
            active_label,
            active_messages,
        )
        for entry, score in zip(non_active_entries, scores, strict=False):
            entry["relevance_score"] = score

    # Make pruning decisions
    decisions: list[PruneDecision] = []
    archived_messages: list[tuple[str, Any, int]] = []  # (task_id, message, index)

    for entry in message_entries:
        # Always keep active task messages
        if entry["is_active"]:
            continue

        task_id = entry["task_id"]
        relevance = entry.get("relevance_score", 0.5)

        # Determine action based on task status + relevance + aggressiveness
        action = _decide_action(
            is_completed=entry["is_completed"],
            relevance=relevance,
            task_status=entry["task_status"],
            aggressiveness=aggressiveness,
        )

        if action == PruneAction.DELETE:
            decisions.append(
                PruneDecision(
                    message_index=entry["index"],
                    action=PruneAction.DELETE,
                    reason=f"Low relevance ({relevance:.2f}) from completed task",
                    task_id=task_id or "",
                    relevance_score=relevance,
                )
            )
        elif action == PruneAction.ARCHIVE:
            decisions.append(
                PruneDecision(
                    message_index=entry["index"],
                    action=PruneAction.ARCHIVE,
                    reason=f"Medium relevance ({relevance:.2f}), archiving for recall",
                    task_id=task_id or "",
                    relevance_score=relevance,
                )
            )
            archived_messages.append((task_id or "", entry["message"], entry["index"]))

    if not decisions:
        logger.debug("Prune pass: no pruning decisions needed")
        return PruneSummary()

    logger.info(
        "Prune pass: %d decisions (%d delete, %d archive)",
        len(decisions),
        sum(1 for d in decisions if d.action == PruneAction.DELETE),
        sum(1 for d in decisions if d.action == PruneAction.ARCHIVE),
    )

    # Execute: archive first, then delete
    archive_paths: dict[str, str] = {}
    if archived_messages:
        # Group archived messages by task_id
        from collections import defaultdict

        task_groups: dict[str, list[Any]] = defaultdict(list)
        for tid, msg, _idx in archived_messages:
            task_groups[tid].append(msg)

        for tid, msgs in task_groups.items():
            task = task_manager.get_task(tid)
            label = task.label if task else tid
            outcome = task.outcome_summary if task else None
            archive_path = archive_messages_for_task(
                task_id=tid,
                task_label=label,
                messages=msgs,
                outcome_summary=outcome,
            )
            if archive_path:
                archive_paths[tid] = str(archive_path)
                task_manager.mark_task_archived(tid)
                logger.debug("Archived %d messages for task %s", len(msgs), tid[:8])

    # Count tokens before/after
    tokens_before = _estimate_total_tokens(message_history)

    # Apply deletes — build new message list excluding deleted indices
    delete_indices = {
        d.message_index for d in decisions if d.action == PruneAction.DELETE
    }
    archive_indices = {
        d.message_index for d in decisions if d.action == PruneAction.ARCHIVE
    }
    remove_indices = delete_indices | archive_indices

    # IMPORTANT: We cannot modify message_history directly here because
    # it's owned by the agent. Instead, we notify the caller via the
    # returned PruneSummary and let the hook in register_callbacks.py
    # handle the actual modification.

    tokens_after = tokens_before - _estimate_tokens_for_indices(
        message_history, remove_indices
    )

    summary = PruneSummary(
        total_messages_before=len(message_history),
        total_messages_after=len(message_history) - len(remove_indices),
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        tokens_saved=max(0, tokens_before - tokens_after),
        decisions=decisions,
        archive_paths=archive_paths,
    )

    delete_count = summary.deleted_count
    archive_count = summary.archived_count

    # Visual feedback
    if archive_count > 0 and delete_count > 0:
        emit_success(
            f"🧹 Pruned "
            f"{summary.total_messages_before - summary.total_messages_after} "
            f"messages (archived {archive_count}, removed {delete_count}) "
            f"— saved ~{summary.tokens_saved} tokens"
        )
    elif archive_count > 0:
        emit_success(
            f"📦 Archived {archive_count} messages from completed tasks "
            f"— saved ~{summary.tokens_saved} tokens"
        )
    elif delete_count > 0:
        emit_success(
            f"🗑️ Removed {delete_count} low-relevance messages "
            f"— saved ~{summary.tokens_saved} tokens"
        )

    # Show which task's archives were created
    if archive_paths:
        for tid, _path in archive_paths.items():
            task = task_manager.get_task(tid)
            label = task.label if task else tid[:8]
            msg_count = sum(
                1
                for d in decisions
                if d.action == PruneAction.ARCHIVE and d.task_id == tid
            )
            emit_info(f"  📁 '{label}' → {msg_count} messages archived")

    logger.info(
        "Prune complete: saved ~%d tokens, archived %d messages for %d task(s)",
        summary.tokens_saved,
        len(archived_messages),
        len(archive_paths),
    )

    return summary


def _decide_action(
    is_completed: bool,
    relevance: float,
    task_status: TaskStatus | None,
    aggressiveness: str,
) -> PruneAction:
    """Decide what action to take for a single message.

    Decision matrix based on:
    - Task status (active/completed/archived)
    - Relevance score (high/medium/low)
    - Aggressiveness setting (conservative/moderate/aggressive)

    Always KEEP for active tasks regardless of other factors.
    """
    # Active messages are always kept (handled by caller)
    if not is_completed and task_status != TaskStatus.ARCHIVED:
        return PruneAction.KEEP

    if relevance >= _MEDIUM_RELEVANCE_THRESHOLD:
        # High relevance: keep (might be useful for current task)
        return PruneAction.KEEP

    if relevance >= _LOW_RELEVANCE_THRESHOLD:
        # Medium relevance: behavior depends on aggressiveness
        if aggressiveness == "aggressive":
            return PruneAction.ARCHIVE
        elif aggressiveness == "conservative":
            return PruneAction.KEEP
        else:  # moderate
            return PruneAction.ARCHIVE

    # Low relevance: behavior depends on aggressiveness
    if aggressiveness == "conservative":
        return PruneAction.ARCHIVE
    elif aggressiveness == "aggressive":
        return PruneAction.DELETE
    else:  # moderate
        return PruneAction.ARCHIVE if is_completed else PruneAction.KEEP


def _estimate_total_tokens(messages: list[Any]) -> int:
    """Estimate total tokens for a list of messages.

    Uses the simple char/3 heuristic for consistency with existing estimates.
    """
    total = 0
    for msg in messages:
        text = _extract_text(msg)
        total += max(1, len(text) // 3)
    return total


def _estimate_tokens_for_indices(
    messages: list[Any],
    indices: set[int],
) -> int:
    """Estimate tokens for specific message indices."""
    total = 0
    for idx in indices:
        if 0 <= idx < len(messages):
            text = _extract_text(messages[idx])
            total += max(1, len(text) // 3)
    return total
