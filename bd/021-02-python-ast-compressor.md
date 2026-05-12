---
id: "021-02"
title: "Build Python AST Compressor — Signature Extraction + Body Dropping"
status: open
epic: "021"
labels: ["code-compressor", "python", "ast", "P1", "headroom-port"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Build the Python-specific AST compressor: parse Python source, walk the tree, keep only semantically essential nodes (function/class signatures, imports, error handling), drop bodies and docstrings.

## Motivation

Python is the most common language muse agents encounter. Starting here gives immediate value. The universal constructor sandbox already uses Python's `ast` module — tree-sitter extends this to more languages.

## Deliverables

- `PythonCompressor` class with `compress(source, verbosity) -> str`
- Node importance classification: KEEP (signatures, imports, raises), DROP (bodies, docstrings, comments, decorators), TRUNCATE (long bodies → `...`)
- AST walker that reconstructs source from kept nodes only
- Verbosity control: level 0 = signatures only, level 4 = keep brief bodies

## Acceptance Criteria

- [ ] `def foo(a, b):\n    """doc"""\n    return a + b` → `def foo(a, b): ...`
- [ ] Class with methods: keeps `class Foo:` + method signatures, drops bodies
- [ ] Imports: `import os, sys` → kept
- [ ] `try/except` blocks: keeps `try:`, `except ErrorType:`, drops body
- [ ] Decorators dropped unless verbosity ≥ 3
- [ ] Output is still syntactically valid Python (parseable)

## Dependencies

- [021-01](021-01-tree-sitter-setup.md) — tree-sitter + Python grammar
- Parent: [Epic 021](021-epic-ast-code-compressor.md)

## Estimated Effort

~150 lines, 2 hours
