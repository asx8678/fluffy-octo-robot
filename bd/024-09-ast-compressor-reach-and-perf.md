---
id: "024-09"
title: "AST Compressor: Language Reach, O(n²) Perf & Double-Detection (P1)"
status: open
epic: "024"
labels: ["bug", "performance", "ast-compressor", "P1", "correctness"]
created: "2026-05-18"
priority: "P1"
---

## Summary

Three fixes to `code.pyx`/`ast_compressor.pyx`:
1. `_language_str_to_code_language` only handles python/javascript/typescript/go — Rust/Java/C/Ruby/Bash/SQL fall back to regex stripping. Fix: remove restrictive map, pass filename to `compress_ast_code`, use `LanguageParser`.
2. `_collect_lines` does `source[:node.start_byte].count("\n")` per node — O(n²). Precompute line-offset array, use bisect for O(log n).
3. `compress_code` → `compress_ast_code` double-detection — single path through `LanguageParser`.

## What

Remove hardcoded language map; let `LanguageParser` infer from filename. Precompute cumulative newline offsets once per source, replace per-node `count("\n")` with `bisect_left(offsets, node.start_byte)`. Unify detection so `compress_code` delegates directly to `compress_ast_code` without re-parsing.

## Deliverables

- [ ] All extensions get AST compression (Rust, Java, C, Ruby, Bash, SQL)
- [ ] O(n²) line collection → O(n log n)
- [ ] Single detection path from `compress_code` to `compress_ast_code`
- [ ] All tests pass

## Acceptance Criteria

- [ ] Files with `.rs`, `.java`, `.c`, `.rb`, `.sh`, `.sql` extensions compressed via AST
- [ ] Line collection benchmarked at O(n log n) or better
- [ ] No duplicate parsing / language detection
- [ ] `ruff check` and all tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~150 lines changed, 2 hours
