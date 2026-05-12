---
id: "011-01"
title: "Policy TOML Schema + Parser — Rule Definitions with Tool Name, Command Prefix, Decision"
status: closed
epic: "011"
labels: ["policy", "toml", "schema", "parser", "rule", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Define the TOML schema for policy rules. Each rule: toolName (str, supports * wildcard), commandPrefix (optional str, matches start of shell command), decision (enum: allow/deny/ask_user), priority (int, higher wins). Parse `[[rule]]` arrays from TOML files using Python's tomllib/tomli. Validate: reject unknown fields, invalid decision values, negative priority. Support loading multiple files (user + project tiers).

## Motivation

A declarative TOML format lets users version-control their security and UX preferences. Tomllib is stdlib in Python 3.11+, so we have zero dependency cost for parsing.

## Deliverables

- ToolRule dataclass
- `parse_policy_toml(path)` → list[ToolRule]
- `validate_rules(rules)` → None (raises on invalid)
- SchemaVersion field for forward compat

## Acceptance Criteria

- [x] valid TOML parses correctly
- [x] invalid TOML raises descriptive error
- [x] unknown fields rejected
- [x] wildcard `*` in toolName supported
- [x] commandPrefix optional (omitted or null)
- [x] decision enum exact match required

## Dependencies

Parent: [Epic 011](011-epic-policy-engine.md) — Policy Engine

## Estimated Effort

~80 lines, 40 min
