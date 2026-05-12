---
id: "015-02"
title: "Plan Generation + Storage — Research, Discuss, Draft plan.md"
status: closed
epic: "015"
labels: ["plan", "generation", "markdown", "storage", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

After entering plan mode, the agent researches the task (reads files, searches codebase), discusses approach with user via ask_user, and drafts a structured plan as markdown. Plan file has sections: Goal, Analysis, Approach, Implementation Steps, Risks. Saved to plans/plan_<timestamp>.md with metadata header (goal, created_at, status: draft).

## Motivation

Structured planning produces better implementation outcomes. Markdown plans are reviewable, editable, and can be committed to version control.

## Deliverables

- Plan generation workflow (research → discuss → draft)
- plan.md template with sections
- File storage in plans/ directory
- Metadata header

## Acceptance Criteria

- [x] plan.md created in plans/ directory
- [x] includes all required sections
- [x] metadata header present
- [x] agent asks user before drafting
- [x] plan is editable after creation

## Dependencies

Parent: [Epic 015](015-epic-plan-mode.md), depends on 015-01

## Estimated Effort

~100 lines, 45 min
