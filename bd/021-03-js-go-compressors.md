---
id: "021-03"
title: "Build JavaScript & Go AST Compressors"
status: open
epic: "021"
labels: ["code-compressor", "js", "go", "ast", "P2"]
created: "2025-07-16"
priority: "P2"
---

## Summary

Extend AST compression to JavaScript/TypeScript and Go using tree-sitter grammars. Follow the same pattern as PythonCompressor: keep signatures, drop bodies.

## Motivation

JS/TS and Go are the next most common languages after Python. Completing these covers 90%+ of code that agents read.

## Deliverables

- `JavaScriptCompressor` — keeps `function`, `const`, `class`, `export`, drops bodies + JSX children
- `GoCompressor` — keeps `func`, `type`, `import`, drops bodies
- Both follow same verbosity levels as Python
- Unit tests with sample JS/Go files

## Acceptance Criteria

- [ ] JS: `function foo(a) { return a }` → `function foo(a) { ... }`
- [ ] JSX: `<div>...children...</div>` → `<div />`
- [ ] TS interfaces kept, method bodies dropped
- [ ] Go: `func (s *Server) Handle(req *Request) error { ... }` → signature kept
- [ ] Both produce valid AST after compression

## Dependencies

- [021-01](021-01-tree-sitter-setup.md) — tree-sitter + grammars
- [021-02](021-02-python-ast-compressor.md) — pattern reference
- Parent: [Epic 021](021-epic-ast-code-compressor.md)

## Estimated Effort

~120 lines, 1.5 hours
