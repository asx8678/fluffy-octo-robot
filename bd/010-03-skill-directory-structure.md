---
id: "010-03"
title: "Skill Directory Structure"
status: closed
epic: "010"
labels: ["skills", "directory", "structure", "SKILL.md", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Define SKILL.md format (frontmatter with name+description, markdown body with instructions). Standard subdirectories: scripts/ (executable scripts), references/ (docs the agent can read), assets/ (bundled files). Validate skill structure on discovery. Template for creating new skills.

## Motivation

A consistent skill directory structure makes skills discoverable, predictable, and easy to create. Validation ensures broken skills are caught early rather than failing silently at runtime.

## Deliverables

- `SKILL.md` format spec: frontmatter (name, description) + markdown body
- Standard subdirectories: `scripts/`, `references/`, `assets/`
- Validation logic checked during discovery
- Template for creating a new skill from scratch

## Acceptance Criteria

- [x] `SKILL.md` frontmatter parsed for `name` and `description`
- [x] Markdown body treated as skill instructions
- [x] `scripts/` directory identified as containing executable scripts
- [x] `references/` directory identified as docs the agent may read
- [x] `assets/` directory identified as bundled static files
- [x] Validation rejects skills missing required frontmatter fields
- [x] Template generates a valid minimal skill directory on request

## Dependencies

Parent: [Epic 010](010-epic-skills-system.md) — Skills System

## Estimated Effort

~80 lines, 40 min
