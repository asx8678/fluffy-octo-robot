---
id: "007"
title: "Epic: Hook Integration, Tee Recovery, Config, Docs"
status: closed
epic: "007"
labels: ["epic", "integration", "config", "docs", "tee", "recovery", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Register as plugin, implement tee recovery on failure, build config system, write user docs, and create `rtk init` equivalent.

## Motivation

A filter engine is useless if users cannot install it, configure it, or recover when it fails. This epic makes Fast-Puppy production-ready and approachable.

## Deliverables

1. Tee mode — save raw output on failure, hint path to LLM
2. Config system — `~/.config/rtk-puppy/config.toml`, per-project filters
3. `rtk-puppy init` — install hook, write RTK.md, settings.json entry
4. User-facing docs — README update, FEATURES.md, quick-start

## Acceptance Criteria

- [x] On strategy crash, raw output is saved to a temp file and path is returned
- [x] Config file supports global defaults and per-project overrides
- [x] `rtk-puppy init` detects project type and installs appropriate hooks
- [x] README includes quick-start, strategy list, and troubleshooting
- [x] FEATURES.md documents each strategy with examples
- [x] All docs are LLM-readable (compact, no marketing fluff)

## Dependencies

Depends on [Epics 001–006](.)

## Estimated Effort

~350 lines, 3 hours

## Children

- [007-01](007-01-tee-recovery.md) — Tee recovery
- [007-02](007-02-config-system.md) — Config system
- [007-03](007-03-init-command.md) — Init command
- [007-04](007-04-docs-readme.md) — Docs and README
