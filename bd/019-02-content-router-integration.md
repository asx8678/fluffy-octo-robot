---
id: "019-02"
title: "Integrate Content Router into FilterDispatcher"
status: open
epic: "019"
labels: ["content-router", "dispatcher", "integration", "P1"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Wire `ContentTypeDetector` + routing logic into `FilterDispatcher.handle()` so that after command execution, the output is sniffed and the best strategy is selected (overriding command-name classification when content type is more specific).

## Motivation

The detector alone does nothing — it must be called in the dispatcher pipeline at the right point: after `_execute_shell_command` returns stdout, before strategy lookup.

## Deliverables

- Modified `FilterDispatcher.handle()` — add `detect()` call after execution
- Routing priority: content-type strategy > command-name strategy > unknown passthrough
- Strategy lookup: map `ContentType` → registered strategy category
- Fallback: if no content-type strategy registered, use command-name strategy
- Logging: debug-level log of detected type and chosen strategy

## Acceptance Criteria

- [ ] `cat package.json` → detector says JSON → dispatcher calls `json` strategy
- [ ] `git diff` → detector says DIFF → dispatcher calls `diff` strategy
- [ ] `pytest` → detector says LOG → dispatcher calls `log` strategy
- [ ] `cat foo.py` → detector says CODE → dispatcher calls `code` strategy (existing)
- [ ] `echo hello` → detector says UNKNOWN → falls back to command-name → unknown passthrough
- [ ] Existing git/test/lint strategies still work unchanged

## Dependencies

- [019-01](019-01-content-type-detector.md) — Content type detector
- [019-03](019-03-strategy-registration.md) — New strategy categories
- Parent: [Epic 019](019-epic-content-router.md)

## Estimated Effort

~60 lines, 1 hour
