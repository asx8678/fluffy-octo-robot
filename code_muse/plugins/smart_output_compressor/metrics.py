"""Compression metrics tracking.

Tracks compression ratios across calls and provides
aggregate stats for command display.
"""

from __future__ import annotations

from code_muse.plugins.smart_output_compressor.models import (
    CompressMetrics,
)
from code_muse.plugins.smart_output_compressor.models import (
    get_metrics as _get_global_metrics,
)


def get_metrics() -> CompressMetrics:
    """Return the global compression metrics singleton."""
    return _get_global_metrics()


def format_metrics_summary() -> str:
    """Human-readable metrics summary for /smart status command."""
    m = get_metrics()
    return (
        f"Smart Compressor Metrics:\n"
        f"  Files processed: {m.total_files}\n"
        f"  Lines before: {m.total_lines_before}\n"
        f"  Lines after: {m.total_lines_after}\n"
        f"  Median reduction: {m.median_reduction_pct:.1f}%\n"
    )
