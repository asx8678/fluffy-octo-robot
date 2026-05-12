"""Shell Minimizer plugin for Muse.

Compresses shell command stdout/stderr before it reaches the LLM,
using per-program intelligent filtering.  Ports the key concepts from
oh-my-pi's minimizer system to a pure-Python pipeline engine.

Public API:
    - apply_pipeline_from_toml(name, toml_def, input, exit_code) -> str
    - parse_pipeline_toml(contents, source_label) -> list[CompiledPipeline]
"""

from code_muse.plugins.shell_minimizer.pipeline import (
    CompiledPipeline,
    PipelineDef,
    apply_pipeline,
    compile_pipeline,
    parse_pipeline_toml,
)
from code_muse.plugins.shell_minimizer.primitives import (
    compact_listing,
    dedup_consecutive_lines,
    group_by_file,
    head_lines_only,
    head_tail_lines,
    keep_lines_regex,
    max_lines,
    strip_ansi,
    strip_lines_regex,
    tail_lines_only,
    truncate_line,
)

__all__ = [
    "CompiledPipeline",
    "PipelineDef",
    "apply_pipeline",
    "compact_listing",
    "compile_pipeline",
    "dedup_consecutive_lines",
    "group_by_file",
    "head_lines_only",
    "head_tail_lines",
    "keep_lines_regex",
    "max_lines",
    "parse_pipeline_toml",
    "strip_ansi",
    "strip_lines_regex",
    "tail_lines_only",
    "truncate_line",
]
