---
id: "019-01"
title: "Build Content Type Detector — Output Sniffing Heuristics"
status: closed
epic: "019"
labels: ["content-router", "detector", "P1", "headroom-port"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Build a `ContentTypeDetector` class that sniffs shell command stdout and classifies it as JSON, diff, log, HTML, code, search results, or unknown. Uses fast heuristics (JSON parse test, diff header regex, log pattern detection).

## Motivation

The filter engine currently classifies by command name only. To route output to SmartCrusher, LogCompressor, etc., we need to know what the output *is*. Fast heuristics avoid LLM calls.

## Deliverables

- `ContentTypeDetector` class with `detect(stdout: str) -> ContentType`
- Heuristics: JSON parse attempt, diff `@@` header detection, log timestamp patterns, HTML tag detection, code keyword density
- `ContentType` enum: JSON, DIFF, LOG, HTML, CODE, SEARCH, UNKNOWN
- Unit tests for each type

## Acceptance Criteria

- [ ] Valid JSON (object, array, nested) → JSON
- [ ] Invalid/malformed JSON → UNKNOWN or CODE
- [ ] Unified diff with `@@` headers → DIFF
- [ ] Log lines with timestamps → LOG
- [ ] HTML with `<html>` / `<div>` → HTML
- [ ] Python/JS source → CODE
- [ ] Empty/short output → UNKNOWN

## Dependencies

Parent: [Epic 019](019-epic-content-router.md)

## Estimated Effort

~80 lines, 1 hour
