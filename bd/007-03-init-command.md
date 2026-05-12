---
id: "007-03"
title: "rtk-puppy init — Install Hook, Write RTK.md, Settings.json Entry"
status: closed
epic: "007"
labels: ["integration", "init", "install", "hook", "settings", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Implement the `rtk-puppy init` command that installs the hook, writes a project RTK.md file, and adds the plugin entry to Claude Code's settings.json.

## Motivation

First-time setup must be one command. `init` detects the project type, installs the appropriate hook, and documents the project's conventions for the LLM.

## Deliverables

- Detect project type (Python, JS, Rust, etc.) from files present
- Install `pre_tool_call` hook in `.claude-code-hooks/` or equivalent
- Write `RTK.md` with project conventions and token-saving tips
- Add plugin entry to Claude Code settings.json
- `--dry-run` option to preview changes

## Acceptance Criteria

- [x] `rtk-puppy init` runs without errors in a fresh repo
- [x] Hook file is created and executable
- [x] `RTK.md` is written with project-appropriate content
- [x] `settings.json` is updated (or instructions printed if manual)
- [x] `--dry-run` shows what would change without writing
- [x] Idempotent: running init twice does not duplicate entries

## Dependencies

Parent: [Epic 007](007-epic-integration.md) — Integration & Polish
Depends on: [001-04](001-04-hook-integration.md)

## Estimated Effort

~100 lines, 1 hour
