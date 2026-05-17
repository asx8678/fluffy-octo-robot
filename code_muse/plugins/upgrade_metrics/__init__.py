"""Upgrade Metrics plugin for Muse — standard telemetry foundation.

Provides the ``emit_metric`` helper for recording upgrade-related events
(compression, context pruning, review verdicts, task archival) into both
an in-memory buffer and a JSONL log file.  Other upgrade plugins import
``emit_metric`` from this module as their standard integration point.

Architecture
------------
File structure under ``code_muse/plugins/upgrade_metrics/``:

- ``register_callbacks.py`` — Hook registration, token ledger, event system,
  JSONL persistence with rotation, and ``/metrics`` slash commands.

Key Design Decisions
--------------------
1. ``emit_metric(event_name, data)`` is the single public API other plugins
   call — it records events into both the in-memory buffer and JSONL file.
2. Token ledger tracks cumulative counts at each pipeline stage so that
   compression and context plugins can report savings.
3. JSONL file at ``~/.muse/metrics/events.jsonl`` rotates at 5 MB so
   disk usage stays bounded.
4. Plugin can be disabled via ``/metrics off`` — all hooks become no-ops.
"""

from code_muse.plugins.upgrade_metrics.register_callbacks import emit_metric

__all__ = [
    "emit_metric",
]
