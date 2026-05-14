---
id: "020-01"
title: "Build JSON Pattern Detection — Array Templating & Field Analysis"
status: closed
epic: "020"
labels: ["smartcrusher", "json", "pattern-detection", "P1", "headroom-port"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Build the pattern detection layer of SmartCrusher: analyzes JSON/structured output to identify array-of-dicts templates, repeated keys, nested structures, and field importance scores.

## Motivation

Compression requires understanding structure. Array templating ("these 50 items all have keys A,B,C") is the highest-leverage detection; field analysis identifies which fields carry information vs boilerplate.

## Deliverables

- `detect_array_template(data: list[dict]) -> dict` — extract common key skeleton
- `score_field_importance(schema: dict) -> dict[str, float]` — information density per key
- `detect_nested_structure(data) -> list[str]` — key paths for flattening
- `is_homogeneous_array(data) -> bool` — all items same shape
- Unit tests with real-world JSON samples (package.json, API responses)

## Acceptance Criteria

- [ ] Array of 50 identical-shape dicts → single template extracted
- [ ] Mixed-shape array → individual items kept, no template
- [ ] Nested `{"a": {"b": 1}}` → key path `["a.b"]`
- [ ] Field scoring: `"name"` > `"id"` > `"_internal_counter"`
- [ ] Empty array → handled gracefully

## Dependencies

Parent: [Epic 020](020-epic-smartcrusher.md)

## Estimated Effort

~120 lines, 1.5 hours
