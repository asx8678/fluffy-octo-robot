---
id: "011-03"
title: "Policy File Discovery — Scan User + Project Tiers, /policies reload Command"
status: closed
epic: "011"
labels: ["policy", "discovery", "file", "toml", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Scan user tier (`~/.muse/policies/*.toml`) and project tier (`.muse/policies/*.toml`). Both tiers always loaded; project rules re-evaluate but don't override by file path — the evaluator's priority system handles conflicts. Provide `/policies reload` slash command to rescan files without restart. Handle missing directories, unreadable files, invalid TOML (warn + skip).

## Motivation

Users need both global (user-level) and repo-specific (project-level) policies. A live reload command means they never have to restart the agent to iterate on rules.

## Deliverables

- `discover_policy_files()` → list[Path]
- `load_all_policies()` → list[ToolRule]
- `/policies reload` command handler

## Acceptance Criteria

- [x] both tiers scanned
- [x] invalid files warned and skipped
- [x] `/policies reload` rescans
- [x] empty directories handled
- [x] TOML parse errors surfaced to user

## Dependencies

Parent: [Epic 011](011-epic-policy-engine.md) — Policy Engine
Depends on: [011-01](011-01-policy-toml-schema.md) — Policy TOML Schema + Parser

## Estimated Effort

~60 lines, 30 min
