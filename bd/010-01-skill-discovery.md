---
id: "010-01"
title: "Skill Discovery + Registry"
status: closed
epic: "010"
labels: ["skills", "discovery", "registry", "scan", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Scan 4 tiers (built-in, extension, user ~/.muse/skills/, workspace .muse/skills/) for directories containing SKILL.md. Dedupe by skill name, higher tier wins. Store name+description+path in registry. Emit skill list at session start for agent awareness.

## Motivation

Skills extend the agent's capabilities without core code changes. A tiered discovery system ensures built-in skills are always available, while user and workspace skills override or augment them.

## Deliverables

- Tiered scanner: built-in → extension → user → workspace
- Registry storing skill name, description, and filesystem path
- Deduplication: higher tier wins on name collision
- Session-start skill list emitted for agent awareness

## Acceptance Criteria

- [x] All 4 tiers scanned for directories containing `SKILL.md`
- [x] Skills without `SKILL.md` ignored
- [x] Duplicate names resolved: higher tier wins
- [x] Registry stores name, description, and path for each skill
- [x] Skill list emitted at session start for agent context
- [x] Missing tiers handled gracefully (no crash if user directory absent)

## Dependencies

Parent: [Epic 010](010-epic-skills-system.md) — Skills System

## Estimated Effort

~100 lines, 45 min
