---
id: "016-05"
title: "Memory Injection at Startup — Load memory_summary.md into System Prompt"
status: "open"
epic: "016"
labels: ["memory", "injection", "startup", "system-prompt", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

At session startup, check for project memory_summary.md. If present and less than 7 days old, inject its content as a "Memory Guidance" block in the system prompt. The injection instructs the agent to: treat memory as heuristic context (not authoritative on current repo state), cite memory path when used, prefer current repo evidence over conflicting memory. Handle missing or empty memory gracefully (no injection).

## Motivation

Memory is only useful if the agent can see it. Startup injection ensures accumulated knowledge is available from turn 1.

## Deliverables

- `load_memory_injection(project_dir: Path) → str | None`
- `inject_into_system_prompt(base_prompt: str, memory_text: str) → str`
- Memory freshness check

## Acceptance Criteria

- [x] memory injected when present and fresh
- [x] missing memory handled silently
- [x] stale memory (>7d) skipped with log
- [x] injection includes usage instructions
- [x] agent cites memory path when using it

## Dependencies

Parent [Epic 016](016-epic-autonomous-memory.md), depends on 016-03.

## Estimated Effort

~80 lines, 40 min.
