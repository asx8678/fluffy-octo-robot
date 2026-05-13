---
id: "024-08"
title: "Content Detector: _is_code Structural Detection & _is_log Regex Combine (P1)"
status: closed
epic: "024"
labels: ["bug", "content-detector", "P1", "correctness"]
created: "2026-05-18"
closed: "2026-05-18"
priority: "P1"
---

## Summary

Two fixes to `content_detector.py`:
1. `_is_code` uses keyword-density heuristic requiring 5% of tokens in a 29-word set — real code files have <2% density. Replace with structural detection (shebang, leading def/class/fn, import/from, balanced braces, indentation).
2. `_is_log` tests 50 lines × 5 regex patterns = 250 evaluations. Combine into single compiled alternation.

## What

Replace `_is_code` keyword-density heuristic with structural signals: shebang line, `def`/`class`/`fn` at start of lines, `import`/`from` statements, balanced braces, and meaningful indentation. Combine `_is_log` 5 separate regexes into one compiled `re.compile("(?:^...|^...|...)")` pattern tested once per line.

## Deliverables

- [ ] `_is_code` uses structural detection, not keyword density
- [ ] `_is_log` uses single combined pattern
- [ ] `ruff check` passes
- [ ] All tests pass

## Acceptance Criteria

- [ ] Real code files (Python, JS, Go, Rust) detected without 5% keyword density
- [ ] Log files detected with single regex evaluation
- [ ] No regressions in content-type classification
- [ ] `ruff check` and all tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~80 lines changed, 45 minutes
