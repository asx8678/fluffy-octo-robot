---
id: "024-15"
title: "SmartCrusher JSON Reachability & Tee Recovery UX (P2)"
status: open
epic: "024"
labels: ["feature", "json", "ux", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Two integration gaps:
1. SmartCrusher JSON only reachable via content-type detection (Finding 4.1). Classifier never returns "json".
2. Tee error-recovery doesn't notify user (Finding 4.2). Strategy crashes write tee files silently.
Fix: Add `json_command` classifier category; emit user warning on tee write; `/tee list` command.

## What

Add "json" as a classifier category so JSON files are routed to `SmartCrusher`. On strategy crash, tee recovery writes to disk — wrap this in a user-visible warning. Add `/tee list` slash command to list recovered tee files for inspection.

## Deliverables

- [ ] `json_command` classifier category
- [ ] Tee user notification on recovery write
- [ ] `/tee` commands (list)
- [ ] Tests pass

## Acceptance Criteria

- [ ] Classifier returns "json" for `.json` / JSON-like prompts
- [ ] User sees warning when tee recovery writes a file
- [ ] `/tee list` displays recovered files with timestamps
- [ ] All tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~90 lines changed, 1.5 hours
