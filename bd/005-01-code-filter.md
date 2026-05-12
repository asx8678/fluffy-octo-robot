---
id: "005-01"
title: "MinimalFilter and AggressiveFilter — Language-Aware Comment Stripping"
status: closed
epic: "005"
labels: ["code", "filter", "comments", "languages", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Port RTK's `MinimalFilter` and `AggressiveFilter` concepts: strip comments and docstrings from source code across 9+ languages, with two aggressiveness levels.

## Motivation

Comments and docstrings are for humans, not LLMs. In many contexts, they add noise. MinimalFilter strips line comments; AggressiveFilter also strips block comments and docstrings. Both preserve code semantics.

## Deliverables

- Language detectors or explicit language mapping
- MinimalFilter: strip single-line comments (`//`, `#`, `--`, `;`)
- AggressiveFilter: also strip block comments (`/* */`, `"""`, `'''`)
- Support: Python, JS/TS, Rust, Go, Java, C, C++, Ruby, Bash

## Acceptance Criteria

- [x] Python: `#` stripped in minimal; `#`, `"""`, `'''` in aggressive
- [x] JS/TS: `//` stripped in minimal; `//`, `/* */`, JSDoc in aggressive
- [x] Rust/Go/Java/C/C++: `//` in minimal; `//`, `/* */` in aggressive
- [x] Ruby: `#` in minimal; `#`, `=begin/=end` in aggressive
- [x] Bash: `#` in minimal
- [x] String literals containing comment syntax are preserved
- [x] Stripped output remains syntactically valid (if possible)

## Dependencies

Parent: [Epic 005](005-epic-code-strategies.md) — Code-Aware Filtering

## Estimated Effort

~150 lines, 1.5 hours
