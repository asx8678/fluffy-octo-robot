---
id: "018"
title: "Epic: Token Caching — Prompt Cache Pattern for Anthropic/Claude"
status: closed
epic: "018"
labels: ["epic", "cache", "token", "prompt", "anthropic", "claude", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Port Gemini CLI's token caching pattern to Claude/Anthropic. Detect cacheable prompt prefix (system instructions + static context), reuse across requests via Anthropic's prompt caching API. Show cached token savings in `/stats`.

## Motivation

Anthropic charges for cached tokens at 0.1x (read) / 1.25x (write) vs full price. Caching the system prompt + static project context can save significant cost on multi-turn sessions.

## Deliverables

1. Cacheable prefix detection (system prompt + project context = static prefix)
2. Anthropic prompt caching API integration (`cache_control: { type: "ephemeral" }`)
3. Cache hit/miss tracking
4. `/stats` display of cached token savings

## Acceptance Criteria

- [x] System prompt + GEMINI.md equivalent marked as cacheable
- [x] Cache breakpoint set after static prefix in message list
- [x] Cache hits tracked across conversation turns
- [x] `/stats` shows cached tokens saved and cost reduction
- [x] Works with Anthropic API versions that support prompt caching
- [x] Fallback to no-cache if API version doesn't support the feature

## Dependencies

Depends on Epic 009 (Stream Parser) for content chunking awareness.

## Estimated Effort

~200 lines, 1.5 hours

## Children

- [018-01](018-01-cacheable-prefix-detection.md) — Cacheable Prefix Detection (identify static prefix boundary in messages)
- [018-02](018-02-anthropic-cache-control.md) — Anthropic Cache Control API (cache_control: ephemeral, breakpoint placement)
- [018-03](018-03-cache-hit-tracking.md) — Cache Hit/Miss Tracking (record cache reads/writes per turn)
- [018-04](018-04-stats-display.md) — /stats Display Integration (show cached tokens + savings in token report)
