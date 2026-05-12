---
id: "018-02"
title: "Anthropic Cache Control API — Add cache_control: ephemeral to Static Prefix"
status: "open"
epic: "018"
labels: ["token", "cache", "anthropic", "api", "cache_control", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Modify the Anthropic API request builder to add cache_control: { type: "ephemeral" } to all messages up to the detected breakpoint. Set at least one cache breakpoint (minimum Anthropic requirement: 1024 tokens in cached prefix). Handle API version compatibility (cache_control supported in specific API versions). Fall back to no-cache if API doesn't support prompt caching.

## Motivation

Anthropic charges 0.1x for cache reads vs 1.0x for base input tokens. Properly caching the static prefix saves significant cost on multi-turn sessions.

## Deliverables

- `inject_cache_control(messages, breakpoint) → modified_messages`
- Version detection
- Fallback handling

## Acceptance Criteria

- [x] cache_control added to static prefix messages
- [x] breakpoint set correctly
- [x] minimum 1024 tokens in cached prefix
- [x] falls back gracefully on unsupported API
- [x] cache write/read tracked in response

## Dependencies

Parent [Epic 018](018-epic-token-caching.md), depends on 018-01.

## Estimated Effort

~60 lines, 30 min.
