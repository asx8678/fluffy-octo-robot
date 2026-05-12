---
id: "013"
title: "Epic: Custom Commands — TOML-Defined Shortcuts with {{args}} Injection"
status: closed
epic: "013"
labels: ["epic", "commands", "toml", "shortcuts", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Port Gemini CLI's TOML custom command system. Commands defined as .toml files with prompt + optional description. Namespaced via directory structure. `{{args}}` placeholder injection. Shell-command context-aware injection.

## Motivation

Muse has customizable_commands plugin but without TOML format, namespacing, or `{{args}}` pattern.

## Deliverables

1. Command TOML parser (prompt, description fields)
2. Command discovery (user `~/.muse/commands/` + project `.muse/commands/`)
3. `{{args}}` injection (raw in prompt body, shell-aware in shell blocks)
4. `/commands list` + `/commands reload` slash commands

## Acceptance Criteria

- [x] Commands discovered from user + project tiers
- [x] Project commands override user commands with same name
- [x] `{{args}}` replaced with user input in prompt body
- [x] Shell commands auto-wrapped with efficiency flags
- [x] `/commands list` shows all available commands with descriptions
- [x] `/commands reload` picks up new files without restart

## Dependencies

None. Standalone.

## Estimated Effort

~250 lines, 2 hours

## Children

- [013-01](013-01-command-toml-schema.md) — Command TOML Schema + Parser (prompt, description, optional fields)
- [013-02](013-02-command-discovery.md) — Command Discovery + Namespacing (directory→namespace mapping, precedence)
- [013-03](013-03-args-injection.md) — {{args}} Injection (raw mode, shell-context mode with auto-flags)
- [013-04](013-04-slash-commands.md) — Slash Commands for Management (/commands list, /commands reload)
