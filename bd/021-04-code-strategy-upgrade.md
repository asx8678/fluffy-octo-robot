---
id: "021-04"
title: "Upgrade Existing Code Strategy to Use AST Compressors"
status: open
epic: "021"
labels: ["code-compressor", "strategy-upgrade", "integration", "P1"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Replace the current `MinimalFilter`-based code strategy with the new AST-aware compressors. Wire language detection → compressor selection → compression.

## Deliverables

- Modify existing `code` strategy function to use `LanguageParser.detect()` + route to correct compressor
- Language detection: file extension + shebang + content heuristics
- Fallback: if language not supported, use existing MinimalFilter
- Update strategy registration — no API change, same `(command, stdout, stderr, exit_code, verbosity)` signature
- Content router integration: CODE output → upgraded `code` strategy

## Acceptance Criteria

- [ ] `cat foo.py` → detected Python → PythonCompressor → compressed
- [ ] `cat bar.js` → detected JS → JavaScriptCompressor → compressed
- [ ] `cat main.go` → detected Go → GoCompressor → compressed
- [ ] `cat unknown.xyz` → falls back to MinimalFilter
- [ ] Strategy signature unchanged — no dispatcher changes needed
- [ ] Existing tests for code strategy still pass (output is different but valid)

## Dependencies

- [021-02](021-02-python-ast-compressor.md) — Python compressor
- [021-03](021-03-js-go-compressors.md) — JS/Go compressors
- [019-02](019-02-content-router-integration.md) — content router
- Parent: [Epic 021](021-epic-ast-code-compressor.md)

## Estimated Effort

~70 lines, 1 hour
