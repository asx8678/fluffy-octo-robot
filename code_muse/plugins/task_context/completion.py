"""Task completion detection module.

Detects when the current task has reached completion using multi-signal analysis:

1. **Explicit signals** — User says "task done", "finished", "completed", etc.
2. **Agent self-assessment** — Agent's response contains success indicators
   (PR merged, tests passing, deployment successful, etc.)
3. **Inactivity timeout** — No activity on the current task for too long
   (configurable via task_auto_complete_timeout)

Conservative by design: prefers false negatives over false positives.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Any

from code_muse.messaging import emit_success
from code_muse.plugins.task_context.config import get_task_auto_complete_timeout
from code_muse.plugins.task_context.models import CompletionSignal, TaskContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Explicit completion signals
# ---------------------------------------------------------------------------

# High-confidence user completion phrases
_HIGH_CONFIDENCE_USER_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:task|work)\s+(?:done|complete|finished)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:that'?s|that\s+is)\s+(?:done|it|all|complete|finished)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i'?m|i\s+am)\s+(?:done|finished)\s+(?:with|for)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\ball\s+(?:done|set|good|finished)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:completed|finished|accomplished)\s+(?:the\s+)?(?:task|work|feature|implementation)\b",
        re.IGNORECASE,
    ),
]

# Medium-confidence user completion phrases
_MEDIUM_CONFIDENCE_USER_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:next|what'?s\s+next|moving\s+on)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:thats?\s+)?(?:all\s+for\s+now|enough\s+for\s+now)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:great|perfect|awesome|excellent),?\s+(?:that'?s|that\s+is)\s+(?:it|all|done)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ship|deploy|merge|publish|release)\s+(?:it|this|the)\b",
        re.IGNORECASE,
    ),
]

# ---------------------------------------------------------------------------
# Agent self-assessment patterns
# ---------------------------------------------------------------------------

# Agent signals that it has completed a task (found in response_text)
_AGENT_SUCCESS_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"\b(?:PR|pull\s+request)\s+#?\d+\s+(?:merged|created|submitted|opened)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:successfully|completed)\s+(?:implemented|refactored|fixed|deployed|migrated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:all\s+)?tests?\s+(?:pass|passing|succeed|succeeded|green)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:deployed|shipped|released|published)\s+(?:to|on)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:implementation|feature|task)\s+(?:is\s+)?(?:now\s+)?(?:complete|done|finished)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:merged|deployed)\s+(?:into|to)\s+(?:main|master|production)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:task|ticket|issue)\s+#?\d+\s+(?:closed|resolved|completed|done)\b",
        re.IGNORECASE,
    ),
]

# ---------------------------------------------------------------------------
# Outcome extraction patterns
# ---------------------------------------------------------------------------

_OUTCOME_EXTRACTION_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(?:PR|pull\s+request)\s+#?(\d+)\s+(?:merged|created|submitted)\s*(?:—|–|-)?\s*(.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:successfully|completed)\s+(implemented|refactored|fixed|deployed)\s+(.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:tests?\s+)?(?:passing|green|succeeding)\s*(?:—|–|-)?\s*(.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:deployed|shipped|released)\s+(.+?)(?:\s+to|\s+on|\.|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:closed|resolved|completed)\s+(?:ticket|issue|task)\s+#?(\d+)\s*(?:—|–|-)?\s*(.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_completion(
    task_manager: Any,
    response_text: str,
    user_message: str | None = None,
    active_task: TaskContext | None = None,
) -> CompletionSignal:
    """Detect whether the current task has reached completion.

    Analyzes multiple signals and returns a CompletionSignal with
    confidence score. Only returns detected=True when confidence > 0.5.

    Args:
        task_manager: The TaskManager instance (for metadata like timestamps).
        response_text: The agent's response text to analyze.
        user_message: Optional user message to analyze for explicit signals.
        active_task: Optional current task context for inactivity checks.

    Returns:
        CompletionSignal with detection result.
    """
    # Signal 1: Explicit user completion phrases
    if user_message:
        for pattern in _HIGH_CONFIDENCE_USER_PATTERNS:
            match = pattern.search(user_message)
            if match:
                outcome = _extract_outcome(response_text)
                logger.debug("Completion detected (user, high): '%s'", match.group())
                emit_success(
                    f"✅ Task completion detected — {outcome or 'user signalled done'}"
                )
                return CompletionSignal(
                    detected=True,
                    confidence=0.9,
                    signal_source="explicit",
                    outcome_summary=outcome,
                )

        for pattern in _MEDIUM_CONFIDENCE_USER_PATTERNS:
            match = pattern.search(user_message)
            if match:
                outcome = _extract_outcome(response_text)
                logger.debug("Completion detected (user, medium): '%s'", match.group())
                emit_success(
                    f"✅ Possible task completion — {outcome or 'moving to next item'}"
                )
                return CompletionSignal(
                    detected=True,
                    confidence=0.7,
                    signal_source="explicit",
                    outcome_summary=outcome,
                )

    # Signal 2: Agent self-assessment (in response text)
    if response_text:
        for pattern in _AGENT_SUCCESS_PATTERNS:
            match = pattern.search(response_text)
            if match:
                outcome = _extract_outcome(response_text)
                logger.debug("Completion detected (agent): '%s'", match.group())
                emit_success(f"✅ Task complete — {outcome or match.group()}")
                return CompletionSignal(
                    detected=True,
                    confidence=0.75,
                    signal_source="agent_self_assessment",
                    outcome_summary=outcome or match.group(),
                )

    # Signal 3: Inactivity timeout
    if active_task:
        timeout = _check_inactivity_timeout(active_task, task_manager)
        if timeout.detected:
            return timeout

    return CompletionSignal(detected=False, confidence=0.0)


def _check_inactivity_timeout(
    active_task: TaskContext,
    task_manager: Any,
) -> CompletionSignal:
    """Check if the active task has been inactive for too long.

    Uses the configurable task_auto_complete_timeout setting.
    Only fires if there are completed tasks (meaning work has been done
    and the user has moved on) or if the task was auto-detected.
    """
    timeout_seconds = get_task_auto_complete_timeout()
    if timeout_seconds <= 0:
        return CompletionSignal(detected=False, confidence=0.0)

    now = datetime.now()
    if active_task.last_accessed is None:
        # Use created_at as fallback
        last_active = active_task.created_at
    else:
        last_active = active_task.last_accessed

    # Ensure both are timezone-aware for comparison
    if last_active.tzinfo is None:
        last_active = last_active.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    elapsed = (now - last_active).total_seconds()
    if elapsed >= timeout_seconds:
        logger.debug(
            "Task '%s' inactive for %.0f seconds (timeout: %d)",
            active_task.task_id[:8],
            elapsed,
            timeout_seconds,
        )
        return CompletionSignal(
            detected=True,
            confidence=0.5,
            signal_source="inactivity_timeout",
            outcome_summary="auto-completed (timeout)",
        )

    return CompletionSignal(detected=False, confidence=0.0)


def _extract_outcome(text: str) -> str | None:
    """Extract a one-line outcome summary from the agent's response.

    Returns the first meaningful outcome found, or None.
    """
    if not text:
        return None

    for pattern in _OUTCOME_EXTRACTION_PATTERNS:
        match = pattern.search(text)
        if match:
            # Take the last meaningful group
            groups = [g for g in match.groups() if g]
            if groups:
                result = groups[-1].strip()
                if len(result) < 200:  # Sanity check
                    return result

    # Fallback: take the first sentence if it's short and seems like a summary
    first_sentence = text.split(".")[0] if "." in text else text
    if first_sentence and len(first_sentence) < 150:
        # Check it doesn't look like boilerplate
        boilerplate = ("i'll", "let me", "here's", "i can", "i have", "i've")
        if not first_sentence.lower().startswith(boilerplate):
            return first_sentence.strip()

    return None
