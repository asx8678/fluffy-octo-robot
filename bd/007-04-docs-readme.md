---
id: "007-04"
title: "User-Facing Docs — README Update, FEATURES.md, Quick-Start"
status: closed
epic: "007"
labels: ["integration", "docs", "readme", "features", "quick-start", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Write user-facing documentation: update the README with token-saving stats, create FEATURES.md documenting every strategy with examples, and write a quick-start guide.

## Motivation

Documentation drives adoption. The README must explain *why* Fast-Puppy matters (tokens saved). FEATURES.md must show *how* each strategy works. The quick-start must get users running in <2 minutes.

## Deliverables

- README section: token-saving philosophy, install, `init`, basic usage
- FEATURES.md: one section per strategy with before/after examples
- QUICKSTART.md: copy-paste commands for common project types
- Inline help strings for all CLI commands

## Acceptance Criteria

- [x] README explains the problem (token bloat) and solution (filtering)
- [x] README includes install and init instructions
- [x] FEATURES.md covers all 20+ strategies with examples
- [x] Each example shows raw output → filtered output
- [x] QUICKSTART.md gets a user from zero to filtered in 3 steps
- [x] All docs are compact and LLM-readable (no marketing fluff)

## Dependencies

Parent: [Epic 007](007-epic-integration.md) — Integration & Polish

## Estimated Effort

~90 lines, 1 hour
