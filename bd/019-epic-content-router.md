---
id: "019"
title: "Epic: Content Router — Output-Type Detection & Smart Routing"
status: open
epic: "019"
labels: ["epic", "content-router", "P1", "structured-compression", "headroom-port"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Add a content-type detection layer to the filter engine that sniffs shell command output and routes it to the best compression strategy. Enables SmartCrusher for JSON, CodeCompressor for code, LogCompressor for logs — instead of relying solely on command-name regex classification.

## Motivation

Current `CommandClassifier` maps commands by regex on command name. But `cat package.json` should route to SmartCrusher, not generic code comment-stripping. `curl api.example.com` returns JSON but goes through "unknown" passthrough. Content routing after execution unlocks structured compression.

## Source

Ported from **headroom**'s `ContentRouter` + `detect_content_type()` — content sniffing heuristics.

## Deliverables

1. Content type detector — sniff stdout for JSON, diff, log, HTML, code, search
2. Content router — maps detected type to best compression strategy
3. Integration into `FilterDispatcher.handle()` — post-execution routing
4. New strategy categories: `json`, `diff`, `log`, `html`, `search`

## Acceptance Criteria

- [ ] `cat package.json` → JSON → SmartCrusher
- [ ] `git diff` → diff → DiffCompressor
- [ ] `pytest -v` → log → LogCompressor
- [ ] `curl api.example.com` JSON → detected correctly
- [ ] `cat src/main.py` → code → (future) CodeCompressor
- [ ] Unknown output falls back to command-name classification
- [ ] < 5ms detection overhead

## Dependencies

- Epic 001 (Core Filter Engine) — hooks into dispatcher
- Epic 020 (SmartCrusher) — JSON strategy
- Epic 021 (AST Code Compressor) — code strategy

## Estimated Effort

~200 lines, 2–3 hours

## Children

- [019-01](019-01-content-type-detector.md)
- [019-02](019-02-content-router-integration.md)
- [019-03](019-03-strategy-registration.md)
