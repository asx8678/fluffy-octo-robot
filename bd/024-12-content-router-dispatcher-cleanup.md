---
id: "024-12"
title: "Content Router & Dispatcher Cleanup (P2)"
status: closed
epic: "024"
labels: ["refactor", "performance", "content-router", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Two findings in `dispatcher.py`:
1. `ContentType.CODE` routes back to command category, making content-type scan a no-op.
2. Content sniffing runs after full command execution — long-running commands pay full I/O before compression.
Fix: Drop `CODE` from `content_strategy_map` or route directly; add streaming sniffer that decides after first 8KB.

## What

Remove `CODE` from `content_strategy_map` so it routes to the code strategy directly instead of bouncing through command category. Introduce a streaming content sniffer that reads the first 8KB of output, runs type detection, then selects strategy before consuming the rest of the stream.

## Deliverables

- [ ] `CODE` routing fixed (direct route, no command bounce)
- [ ] Streaming sniffer added (decides after 8KB)
- [ ] Tests pass

## Acceptance Criteria

- [ ] `ContentType.CODE` output routed directly to code compression strategy
- [ ] Dispatcher can determine content type within first 8KB of output
- [ ] No full-buffer requirement before strategy selection
- [ ] All tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~120 lines changed, 2 hours
