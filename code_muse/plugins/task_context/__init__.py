"""Task-Aware Context Management Plugin.

Provides task-partitioned context pruning, lifecycle-aware cleanup,
and dynamic relevance scoring for the Muse Context Governance Service.

This plugin implements the v2.1 design document (DESIGN-TOKEN-CAPS-v2.md).
"""

from code_muse.plugins.task_context import (
    _context_utils,
    archival,
    budget,
    completion,
    config,
    dependencies,
    detector,
    experience_commands,
    experience_models,
    experience_signature,
    experience_store,
    models,
    pruner,
    scorer,
    task_manager,
)
from code_muse.plugins.task_context.register_callbacks import register_all_callbacks

__all__ = [
    "_context_utils",
    "archival",
    "budget",
    "completion",
    "config",
    "dependencies",
    "detector",
    "experience_commands",
    "experience_models",
    "experience_signature",
    "experience_store",
    "models",
    "pruner",
    "scorer",
    "task_manager",
    "register_all_callbacks",
]
