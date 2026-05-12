---
id: "016"
title: "Epic: Autonomous Memory Pipeline — Cross-Session Knowledge Extraction + Consolidation"
status: closed
epic: "016"
labels: ["epic", "memory", "autonomous", "extraction", "consolidation", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Port Oh-My-Pi's autonomous memory pipeline. Two-phase background process: Phase 1 extracts durable knowledge from past sessions; Phase 2 consolidates into MEMORY.md + memory_summary.md + skills/. Uses lease-based locking to prevent double-run.

## Motivation

Neither Codex nor RTK have cross-session memory. Oh-My-Pi's implementation is the most complete, with extraction + consolidation + skill generation.

## Deliverables

1. Session scanner (find eligible sessions: idle >3h, 10+ user messages)
2. Phase 1 extraction agent (reads session, extracts durable facts/workflows)
3. Phase 2 consolidation agent (synthesizes MEMORY.md, memory_summary.md, skills/)
4. Lease-based locking (prevents concurrent extraction)
5. Memory injection at session start

## Acceptance Criteria

- [x] Sessions indexed from `~/.muse/sessions/`
- [x] Extraction runs in background without blocking UI
- [x] MEMORY.md updated with new knowledge after each extraction cycle
- [x] memory_summary.md injected at session start as system context
- [x] skills/ directory generated for repeated workflows
- [x] Lease prevents double extraction across concurrent sessions
- [x] Secrets scanned before any memory file write

## Dependencies

Depends on Epic 006 (Token Tracking) for session data, Epic 010 (Skills System) for skill generation.

## Estimated Effort

~500 lines, 4 hours

## Children

- [016-01](016-01-session-scanner.md) — Session Scanner + Eligibility (index sessions, idle detection, min messages)
- [016-02](016-02-per-session-extraction.md) — Phase 1 — Per-Session Extraction (background agent, durable fact extraction)
- [016-03](016-03-cross-session-consolidation.md) — Phase 2 — Cross-Session Consolidation (MEMORY.md, memory_summary.md, skills/)
- [016-04](016-04-lease-lock.md) — Lease Lock + Secret Scanning (lock file, SHA-256 secret detection)
- [016-05](016-05-memory-injection.md) — Memory Injection at Startup (load memory_summary.md into system prompt)
