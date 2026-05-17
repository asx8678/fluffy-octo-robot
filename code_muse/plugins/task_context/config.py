"""Configuration helpers for the task_context plugin.

Reads from the main muse.cfg using the existing config parser.
All config keys are prefixed with 'task_' to avoid collision.
"""

import logging

from code_muse.config.parser import get_value, set_config_value

logger = logging.getLogger(__name__)

# Config key constants
_KEY_ENABLED = "task_prune_enabled"
_KEY_PRUNE_THRESHOLD = "task_prune_threshold"
_KEY_AUTO_COMPLETE_TIMEOUT = "task_auto_complete_timeout"
_KEY_AUTO_DETECT = "task_auto_detect"
_KEY_MAX_ARCHIVE = "task_max_archive_contexts"
_KEY_PRUNE_AGGRESSIVENESS = "task_prune_aggressiveness"
_KEY_EMBEDDING_ENABLED = "task_embedding_enabled"

_TRUTHY = ("true", "1", "yes", "on")


def get_task_prune_enabled() -> bool:
    """Whether task-aware pruning is active. Default: True."""
    val = get_value(_KEY_ENABLED)
    if val is None:
        return True
    return str(val).strip().lower() in _TRUTHY


def set_task_prune_enabled(enabled: bool) -> None:
    set_config_value(_KEY_ENABLED, "true" if enabled else "false")
    logger.info("Task-aware pruning %s", "enabled" if enabled else "disabled")


def get_task_prune_threshold() -> float:
    """Proportion of token budget that triggers pruning (0.0–1.0). Default: 0.85."""
    val = get_value(_KEY_PRUNE_THRESHOLD)
    try:
        threshold = float(val) if val else 0.85
        return max(0.5, min(0.95, threshold))
    except (ValueError, TypeError):
        return 0.85


def set_task_prune_threshold(threshold: float) -> None:
    clamped = max(0.5, min(0.95, threshold))
    set_config_value(_KEY_PRUNE_THRESHOLD, str(clamped))
    logger.info("Task prune threshold set to %.2f", clamped)


def get_task_auto_complete_timeout() -> int:
    """Seconds of inactivity before auto-completing a task. Default: 600 (10 min)."""
    val = get_value(_KEY_AUTO_COMPLETE_TIMEOUT)
    try:
        timeout = int(val) if val else 600
        return max(30, min(3600, timeout))
    except (ValueError, TypeError):
        return 600


def set_task_auto_complete_timeout(seconds: int) -> None:
    clamped = max(30, min(3600, seconds))
    set_config_value(_KEY_AUTO_COMPLETE_TIMEOUT, str(clamped))
    logger.info("Task auto-complete timeout set to %d seconds", clamped)


def get_task_auto_detect() -> bool:
    """Whether task shift auto-detection is enabled. Default: True."""
    val = get_value(_KEY_AUTO_DETECT)
    if val is None:
        return True
    return str(val).strip().lower() in _TRUTHY


def set_task_auto_detect(enabled: bool) -> None:
    set_config_value(_KEY_AUTO_DETECT, "true" if enabled else "false")
    logger.info("Task auto-detection %s", "enabled" if enabled else "disabled")


def get_task_max_archive_contexts() -> int:
    """Maximum number of archived task contexts to retain. Default: 20."""
    val = get_value(_KEY_MAX_ARCHIVE)
    try:
        n = int(val) if val else 20
        return max(1, min(500, n))
    except (ValueError, TypeError):
        return 20


def set_task_max_archive_contexts(count: int) -> None:
    clamped = max(1, min(500, count))
    set_config_value(_KEY_MAX_ARCHIVE, str(clamped))
    logger.info("Max archived task contexts set to %d", clamped)


def get_task_prune_aggressiveness() -> str:
    """Prune aggressiveness: 'conservative', 'moderate', or 'aggressive'.

    Conservative: only prune completed tasks, keep all medium-relevance items archived.
    Moderate: prune completed tasks, archive medium, delete low relevance.
    Aggressive: archive completed tasks entirely, delete medium+low.
    Default: 'moderate'.
    """
    val = get_value(_KEY_PRUNE_AGGRESSIVENESS)
    if val and val.lower() in ("conservative", "moderate", "aggressive"):
        return val.lower()
    return "moderate"


def set_task_prune_aggressiveness(level: str) -> None:
    normalized = level.lower()
    if normalized not in ("conservative", "moderate", "aggressive"):
        logger.warning("Invalid prune aggressiveness: %s, using 'moderate'", level)
        normalized = "moderate"
    set_config_value(_KEY_PRUNE_AGGRESSIVENESS, normalized)
    logger.info("Task prune aggressiveness set to '%s'", normalized)


def get_task_embedding_enabled() -> bool:
    """Whether embedding-based relevance scoring is enabled. Default: False (opt-in)."""
    val = get_value(_KEY_EMBEDDING_ENABLED)
    if val is None:
        return False
    return str(val).strip().lower() in _TRUTHY


def set_task_embedding_enabled(enabled: bool) -> None:
    set_config_value(_KEY_EMBEDDING_ENABLED, "true" if enabled else "false")
    logger.info("Task embedding scoring %s", "enabled" if enabled else "disabled")


def get_task_config_summary() -> str:
    """Return a human-readable summary of all task config values."""
    lines = [
        "Task Context Configuration:",
        f"  Prune enabled: {get_task_prune_enabled()}",
        f"  Prune threshold: {get_task_prune_threshold():.0%} of token budget",
        f"  Prune aggressiveness: {get_task_prune_aggressiveness()}",
        f"  Auto-detect task shifts: {get_task_auto_detect()}",
        f"  Auto-complete timeout: {get_task_auto_complete_timeout()}s",
        f"  Max archived contexts: {get_task_max_archive_contexts()}",
        f"  Embedding scoring: {get_task_embedding_enabled()}",
    ]
    return "\n".join(lines)
