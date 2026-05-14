---
id: "027-09"
title: "Extend _walk_cython to JS/Go/Rust/C++ compressors (P3)"
status: closed
epic: "027"
labels: ["performance", "cython", "ast-compressor", "P3"]
created: "2026-06-10"
priority: "P3"
---

## Summary

The `ast_compressor.pyx` has a Cython-typed `_walk_cython()` function, but it's only called from `compress_python()`. The `compress_javascript()`, `compress_go()`, `compress_rust()`, `compress_java()`, and `compress_c_cpp()` functions still use pure Python `_walk()` with untyped locals.

## Current State

- `_walk_cython()` — Cython with `cdef int` locals, used by `compress_python()` ✅
- `_walk()` — pure Python recursion, used by `compress_javascript()`, `compress_go()` ❌
- `compress_rust()`, `compress_java()`, `compress_c_cpp()` — call `_collect_lines()` which calls `_walk_cython()` but the extra handler is Python ❌

## Fix

1. Refactor `_walk_cython` to accept a `keep_types` parameter (it already does) and an optional `extra_handler` parameter
2. Make `compress_javascript()` use `_collect_lines(source, ast, JS_KEEP_TYPES, level)` instead of inline `_walk()`
3. The Go compressor's `_extra_handler` lambda needs to stay Python-callable — either:
   a. Keep it as a Python function (minor perf loss for the uncommon handler path)
   b. Or inline the Go-specific logic into `_walk_cython` with an if-branch on language type
4. Verify all compressors call `_collect_lines` → `_walk_cython`

## Expected Gain

- JavaScript: 2-3x (currently pure Python walk)
- Go: 2-3x (mixed — calls _collect_lines but extra_handler is Python)
- Rust/Java/C/C++: Already calling `_collect_lines`, minor gain (1.2x)

## Deliverables

- [ ] `compress_javascript()` uses `_collect_lines()` → `_walk_cython()` instead of inline `_walk()`
- [ ] Go `_extra_handler` logic integrated or optimized for Cython path
- [ ] `compress_rust()`, `compress_java()`, `compress_c_cpp()` verified using Cython walk
- [ ] All filter engine tests pass
- [ ] Benchmark shows improvement for large JS/TS/Go files

## Acceptance Criteria

- [ ] JavaScript 500KB+ file compression is 2x+ faster
- [ ] All existing compression output is identical (line-level bit-exact)
- [ ] No regression in any supported language
- [ ] All tests pass

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)

## Estimated Effort

~80 lines changed, 4 hours
