---
id: "015-03"
title: "Plan Approval Flow — Review, Edit via Ctrl+X, Approve or Iterate"
status: closed
epic: "015"
labels: ["plan", "approval", "review", "edit", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

After plan generation, present the plan for user review. Options: approve (transitions to auto-edit or manual-edit mode for implementation), edit (opens plan in external editor via Ctrl+X, re-reads after save), iterate (agent revises plan based on user feedback), cancel (returns to default mode). Handle edge case where user edits plan file externally during review.

## Motivation

User must have final say on plan before implementation begins. External editor integration respects developer workflow preferences.

## Deliverables

- Plan review prompt with options
- Ctrl+X external editor integration
- Plan status transitions (draft → approved → implementing → done/cancelled)

## Acceptance Criteria

- [x] approve transitions to implementation mode
- [x] Ctrl+X opens configured editor
- [x] agent re-reads plan after external edit
- [x] iterate updates plan based on feedback
- [x] cancel returns to default mode

## Dependencies

Parent: [Epic 015](015-epic-plan-mode.md), depends on 015-02

## Estimated Effort

~80 lines, 40 min
