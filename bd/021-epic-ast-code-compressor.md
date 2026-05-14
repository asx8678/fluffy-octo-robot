---
id: "021"
title: "Epic: AST-Aware Code Compression — Tree-Sitter Semantic Squashing"
status: closed
epic: "021"
labels: ["epic", "code-compressor", "P1", "ast", "tree-sitter", "headroom-port"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Upgrade the existing `code` strategy from regex-based comment stripping to AST-aware semantic compression using tree-sitter. Parse Python/JS/Go/Rust/Java/C++ ASTs, keep signatures + errors, drop docstrings + redundant bodies + whitespace.

## Motivation

Current `MinimalFilter` strips `#`, `//`, `/* */` comments. This saves ~20% but leaves function bodies, decorators, docstrings, and structural whitespace. AST-aware compression drops everything non-essential while guaranteeing the code is still semantically valid for LLM understanding. Target: 60-85% reduction.

## Source

Ported from **headroom**'s `CodeCompressor` — tree-sitter parsing + node-level importance scoring + content-aware truncation.

## Deliverables

1. Tree-sitter integration — install grammars for Python, JS, Go, Rust
2. Python AST compressor (first language, highest impact)
3. JS/TS/Go compressors (follow-on)
4. Upgrade existing `code` strategy in StrategyRegistry
5. Content router routes CODE output → AST compressor

## Acceptance Criteria

- [ ] `cat src/main.py` (500 lines) → compressed to ~80 lines keeping all signatures
- [ ] Function bodies dropped, signatures + return types kept
- [ ] Docstrings dropped
- [ ] Error/exception paths preserved
- [ ] Imports kept (but deduplicated)
- [ ] Compressed code still parseable (valid AST)
- [ ] JS: drops JSX children, keeps component signatures
- [ ] Go: drops function bodies, keeps `func Name(args) returns`

## Dependencies

- Epic 019 (Content Router) — routes CODE output here
- Epic 001 (Core Filter Engine) — strategy registry
- Requires `pip install tree-sitter` + language grammars

## Estimated Effort

~400 lines, 4–5 hours

## Children

- [021-01](021-01-tree-sitter-setup.md)
- [021-02](021-02-python-ast-compressor.md)
- [021-03](021-03-js-go-compressors.md)
- [021-04](021-04-code-strategy-upgrade.md)
