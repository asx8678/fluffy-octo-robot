---
id: "018-01"
title: "Cacheable Prefix Detection — Find Static/Dynamic Boundary in Message Array"
status: "closed"
epic: "018"
labels: ["token", "cache", "prefix", "detection", "anthropic", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Analyze the message array for a Claude/Anthropic conversation to find the boundary between the static prefix (system prompt + project context like AGENTS.md/CLAUDE.md content) and the dynamic suffix (actual conversation turns with user/assistant messages). Return the breakpoint index (last message in static prefix). Handle edge cases: no static content (breakpoint=0), all static (breakpoint=len-1), empty messages.

## Motivation

Anthropic's prompt caching requires knowing where the static prefix ends. Correct breakpoint detection maximizes cache hits without caching dynamic content that would cause cache misses.

## Deliverables

- `detect_cache_breakpoint(messages: list[dict]) → int` (breakpoint index)
- Heuristic: first user message marks start of dynamic content

## Acceptance Criteria

- [x] system prompt identified as static
- [x] project context files identified as static
- [x] first user message starts dynamic section
- [x] breakpoint = last static message index
- [x] handles edge cases (empty, all static, no static)

## Dependencies

Parent [Epic 018](018-epic-token-caching.md).

## Estimated Effort

~60 lines, 30 min.
