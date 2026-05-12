---
id: "013-02"
title: "Command Discovery + Namespacing — Scan User + Project Tiers, Directory→Namespace"
status: closed
epic: "013"
labels: ["commands", "discovery", "namespace", "directory", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Scan user tier (~/.muse/commands/) and project tier (.muse/commands/). Namespace commands by directory structure: subdir/name.toml becomes /subdir:name. Project commands override user commands with the same namespace+name (higher priority). Command names must be valid identifiers (alphanumeric + hyphens/underscores).

## Motivation

Namespacing prevents collisions between user-global and project-specific commands. Directory-based namespaces are intuitive and require no extra metadata in the TOML files.

## Deliverables

- `discover_commands() → dict[str, CommandDef]`
- `resolve_namespace(file_path, commands_dir) → str`
- Precedence: project > user

## Acceptance Criteria

- [x] Flat .toml → /name
- [x] Subdir/name.toml → /subdir:name
- [x] Project overrides user
- [x] Invalid filenames warned and skipped
- [x] Empty directories handled

## Dependencies

Parent: [Epic 013](013-epic-custom-commands.md) — Custom Commands. Depends on [013-01](013-01-command-toml-schema.md).

## Estimated Effort

~80 lines, 40 min
