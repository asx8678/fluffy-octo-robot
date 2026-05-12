---
id: "001"
title: "Epic: Core Filter Engine — Command Classifier & Strategy Router"
status: closed
epic: "001"
labels: ["epic", "filter-engine", "core", "P0", "classifier", "dispatcher"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Build the central filter engine that intercepts shell command output, classifies the command type, and routes to the appropriate filtering strategy. This is the foundational epic that all other strategy epics depend on.

## Motivation

RTK's token-saving power comes from its ability to classify commands and apply domain-specific compression. Without a robust filter engine, Fast-Puppy cannot intelligently reduce token volume. This epic establishes the architectural backbone.

## Deliverables

1. Command classifier with regex pattern matching (port RTK's REGEX_SET)
2. Strategy registry with plugin-style registration via callbacks
3. Filter dispatcher — execute underlying command, capture output, apply strategy, return compact result
4. Hook integration wiring into `pre_tool_call` callback in `claude_code_hooks` plugin
5. `-u`/`--ultra-compact` and `-v`/`-vv`/`-vvv` CLI flags

## Acceptance Criteria

- [x] Classifier correctly identifies git, test, lint, code, and unknown command categories
- [x] Registry allows strategies to self-register without core modification
- [x] Dispatcher captures stdout/stderr, applies matched strategy, and returns result
- [x] Hook callback intercepts shell tool calls and routes through the dispatcher
- [x] CLI flags override default verbosity levels per invocation
- [x] Passthrough fallback preserves raw output when no strategy matches

## Dependencies

None. This is the root epic. All other epics depend on this one.

## Estimated Effort

~400 lines, 3–4 hours

## Children

- [001-01](001-01-classifier.md) — Command classifier
- [001-02](001-02-registry.md) — Strategy registry
- [001-03](001-03-dispatcher.md) — Filter dispatcher
- [001-04](001-04-hook-integration.md) — Hook integration
- [001-05](001-05-cli-flags.md) — CLI flags
