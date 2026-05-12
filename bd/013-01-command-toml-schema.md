---
id: "013-01"
title: "Command TOML Schema + Parser — Prompt + Optional Description"
status: closed
epic: "013"
labels: ["commands", "toml", "schema", "parser", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Define the TOML schema for custom command definitions. Each command has: prompt (str, required — the text sent to the model), description (optional str, shown in /help). Parse .toml files. Validate: prompt must be non-empty string. Support multi-line prompts using TOML literal strings (single quotes) or multi-line basic strings (triple double-quotes).

## Motivation

A declarative TOML format lets users version-control custom commands. Keeping the schema minimal (prompt + optional description) reduces learning curve while supporting rich multi-line prompts.

## Deliverables

- `CommandDef` dataclass
- `parse_command_toml(path) → CommandDef`
- Schema version for forward compat

## Acceptance Criteria

- [x] Valid TOML with prompt parses correctly
- [x] Missing prompt raises error
- [x] Description optional
- [x] Multi-line prompts supported
- [x] Unknown fields rejected

## Dependencies

Parent: [Epic 013](013-epic-custom-commands.md) — Custom Commands

## Estimated Effort

~60 lines, 30 min
