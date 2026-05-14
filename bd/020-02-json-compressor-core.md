---
id: "020-02"
title: "Build SmartCrusher Compression Engine — Template Application & Flattening"
status: closed
epic: "020"
labels: ["smartcrusher", "compression", "json", "P1", "headroom-port"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Build the core compression engine that takes detected patterns (from 020-01) and produces compact output: applies templates, flattens nested structures, selects informative fields, and formats for minimal token count.

## Motivation

Pattern detection without compression is useless. The engine applies the detected template ("all items are `{name, version, deps}`") and emits a compact representation.

## Deliverables

- `compress_json(data, patterns, verbosity) -> str` — main compression function
- Template application: replace full items with template + values array
- Field selection: drop low-score fields per verbosity threshold
- Nest flattening: `a.b.c` notation for deep paths
- Type-aware formatting: arrays as `[...N items]`, strings as-is, numbers as-is
- Preserve error/exception fields always

## Acceptance Criteria

- [ ] `[{"a":1,"b":2},{"a":3,"b":4}]` → template `{a,b}` + values `[[1,2],[3,4]]`
- [ ] Verbosity 0: drops all optional whitespace
- [ ] Verbosity 4: keeps near-original structure
- [ ] Error fields (`"error"`, `"exception"`) never dropped
- [ ] Roundtrip: compressed output is still valid JSON

## Dependencies

- [020-01](020-01-json-pattern-detection.md) — pattern detection
- Parent: [Epic 020](020-epic-smartcrusher.md)

## Estimated Effort

~150 lines, 2 hours
