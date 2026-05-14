---
id: "027-02"
title: "Pre-compile regex in shell_minimizer primitives (P0)"
status: closed
epic: "027"
labels: ["performance", "regex", "P0"]
created: "2026-06-10"
priority: "P0"
---

## Summary

`shell_minimizer/primitives.py::strip_lines_regex()` and `keep_lines_regex()` compile regex patterns on **every call**. These are called on every shell command output. Move compilation to pipeline build time.

## Current Code

```python
def strip_lines_regex(input: str, patterns: list[str]) -> str:
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]  # Every call!
    lines = input.splitlines()
    kept = [line for line in lines if not any(c.search(line) for c in compiled)]
    return "\n".join(kept)
```

The `patterns` list comes from TOML config — fixed at pipeline compile time. Compiling once in `pipeline.py::compile_pipeline()` eliminates per-call overhead.

## Fix

1. Add `_compiled_strip: list[re.Pattern] | None` and `_compiled_keep: list[re.Pattern] | None` fields to `CompiledPipeline`
2. Compile patterns in `compile_pipeline()`: `_compiled_strip = [re.compile(p, re.IGNORECASE) for p in raw.get("strip_lines_matching", [])]`
3. Pass pre-compiled lists to primitives instead of string patterns
4. Remove per-call `re.compile()` from `strip_lines_regex` and `keep_lines_regex`

## Deliverables

- [ ] `CompiledPipeline` stores pre-compiled regex lists
- [ ] `compile_pipeline()` compiles patters during pipeline build
- [ ] Primitives accept `list[re.Pattern]` not `list[str]`
- [ ] All pipeline tests pass

## Acceptance Criteria

- [ ] `strip_lines_regex` no longer calls `re.compile()` on hot path
- [ ] `keep_lines_regex` no longer calls `re.compile()` on hot path
- [ ] Shell output minimization sees measurable throughput improvement
- [ ] Existing pipeline TOML config continues to work unchanged

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)

## Estimated Effort

~50 lines changed, 1 hour
