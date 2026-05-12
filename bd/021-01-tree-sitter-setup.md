---
id: "021-01"
title: "Install Tree-Sitter + Language Grammars for AST Compression"
status: open
epic: "021"
labels: ["code-compressor", "tree-sitter", "setup", "P1"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Add tree-sitter as a dependency and install language grammars for Python, JavaScript, Go, and Rust. Verify parsing works for each language.

## Motivation

AST-aware compression requires a parser. Tree-sitter is the standard — fast, incremental, multi-language. We need grammars for the languages muse agents most commonly read.

## Deliverables

- Add `tree-sitter` to project dependencies (pyproject.toml)
- Install `tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-go`, `tree-sitter-rust` packages
- `LanguageParser` wrapper class: `parse(code, language) -> AST`
- Verify: parse a sample Python file, walk the AST, identify function nodes
- Verify: parse sample JS/Go/Rust files

## Acceptance Criteria

- [ ] `pip install tree-sitter tree-sitter-python ...` succeeds
- [ ] `LanguageParser("python").parse(source)` returns valid CST
- [ ] AST node types identified: `function_definition`, `class_definition`, `import_statement`
- [ ] JS: `function_declaration`, `arrow_function` identified
- [ ] Go: `function_declaration`, `import_declaration` identified

## Dependencies

Parent: [Epic 021](021-epic-ast-code-compressor.md)

## Estimated Effort

~60 lines, 1 hour (mostly dependency setup)
