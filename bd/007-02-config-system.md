---
id: "007-02"
title: "Config System — ~/.config/rtk-puppy/config.toml, Per-Project Filters"
status: closed
epic: "007"
labels: ["integration", "config", "toml", "per-project", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Build a TOML-based configuration system supporting global defaults in `~/.config/rtk-puppy/config.toml` and per-project overrides.

## Motivation

Users need to customize strategy behavior, set default verbosity, disable specific filters, and configure project-specific rules. TOML is human-readable and standard.

## Deliverables

- Config loader with XDG path resolution
- Global config schema: defaults, enabled strategies, verbosity
- Per-project config: `.rtk-puppy.toml` in repo root
- Merge strategy: project overrides global
- Validation: warn on unknown keys

## Acceptance Criteria

- [x] Config loads from `~/.config/rtk-puppy/config.toml`
- [x] Project config `.rtk-puppy.toml` merges over global
- [x] Supports `enabled = ["git", "pytest"]` to whitelist strategies
- [x] Supports `disabled = ["lint"]` to blacklist strategies
- [x] Supports `default_verbosity = "compact"`
- [x] Unknown keys log a warning but do not crash

## Dependencies

Parent: [Epic 007](007-epic-integration.md) — Integration & Polish

## Estimated Effort

~80 lines, 1 hour
