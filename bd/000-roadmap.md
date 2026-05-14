---
id: "000"
title: "Fast-Puppy Feature Roadmap — Grand Unified Plan"
status: closed
epic: "000"
labels: ["roadmap", "master", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Overview

This roadmap integrates the best features from Codex, RTK, Oh-My-Pi, and Gemini CLI into Fast-Puppy. It covers 18 epics organized into 6 dependency-ordered implementation phases, from core filter engine to advanced caching and memory systems.

## Source Projects

- **RTK** — Token-saving filter strategies for shell command output
- **Codex** — Stream parser framework, models cache, LRU cache
- **Oh-My-Pi** — Autonomous memory pipeline, filesystem scan cache
- **Gemini CLI** — Checkpointing, skills system, policy engine, custom commands, behavioral evals, plan mode, token caching

## Epic Inventory

| ID | Epic | Source | Status | Priority | Est. Lines |
|----|------|--------|--------|----------|------------|
| 001 | Core Filter Engine | RTK | closed | P0 | ~400 |
| 002 | Git Strategies | RTK | closed | P0 | ~350 |
| 003 | Test Strategies | RTK | closed | P0 | ~300 |
| 004 | Lint Strategies | RTK | closed | P0 | ~300 |
| 005 | Code Strategies | RTK | closed | P0 | ~350 |
| 006 | Token Tracking | Fast-Puppy | closed | P0 | ~300 |
| 007 | Integration & Tooling | Fast-Puppy | closed | P0 | ~400 |
| 008 | Checkpointing + Rewind | Gemini CLI | closed | P0 | ~500 |
| 009 | Stream Parser Framework | Codex | closed | P0 | ~300 |
| 010 | Skills System | Gemini CLI | closed | P1 | ~400 |
| 011 | Policy Engine | Gemini CLI | closed | P1 | ~250 |
| 012 | Models Cache + LRU Cache | Codex | closed | P1 | ~200 |
| 013 | Custom Commands | Gemini CLI | closed | P2 | ~250 |
| 014 | Behavioral Eval Framework | Gemini CLI | closed | P2 | ~350 |
| 015 | Plan Mode | Gemini CLI | closed | P2 | ~300 |
| 016 | Autonomous Memory Pipeline | Oh-My-Pi | closed | P3 | ~500 |
| 017 | Filesystem Scan Cache | Oh-My-Pi | closed | P3 | ~300 |
| 018 | Token Caching | Gemini CLI | closed | P3 | ~200 |

## Implementation Phases

### Phase 0 — Foundation (Epics 001–007)
Core token-saving infrastructure. Filter engine, strategy implementations, token tracking, and integration tooling. These are already in progress and form the baseline for all later work.

### Phase 1 — Critical Utilities (Epics 008–009)
Checkpointing and stream parsing. These are standalone utilities with no dependencies but high impact. Checkpointing enables safe experimentation; stream parsing enables structured model output handling.

### Phase 2 — Agent Control (Epics 010–012)
Skills, policies, and caching. These give users control over agent capabilities and improve startup performance. Policy engine replaces ad-hoc safety checks with a general rule system.

### Phase 3 — Productivity (Epics 013–015)
Custom commands, behavioral evals, and plan mode. These improve the daily user experience and code quality. Plan mode provides a structured research→plan→implement workflow.

### Phase 4 — Intelligence (Epic 016)
Autonomous memory. Cross-session knowledge extraction and consolidation. Depends on token tracking data and the skills system. Runs in background without blocking UI.

### Phase 5 — Performance (Epics 017–018)
Filesystem scan cache and token caching. These optimize repeated operations and API costs. Scan cache avoids redundant directory walks; token caching reduces Anthropic API spend.

## Source Code Reuse Strategy

Where possible, port concepts and data structures rather than direct code translation. Rust→Python ports should use Python idioms (dataclasses, generators, context managers) while preserving the original algorithmic behavior. For TOML-based systems (policy engine, custom commands), keep schema compatibility with Gemini CLI so users can reuse configuration files. For cache systems, preserve the same cache key semantics and TTL policies to maintain behavioral parity.

## Completion Notes

All 18 base epics completed as of 2025-07. ~9,000 tests passing. Epic 023 (Phase 8) completed 2026-05-11.

- **Phase 0 (001-007)**: Filter engine, strategies, tracking, integration ✅
- **Phase 1 (008-009)**: Checkpointing, stream parser ✅
- **Phase 2 (010-012)**: Skills, policy engine, models cache ✅
- **Phase 3 (013-015)**: Custom commands, behavioral evals, plan mode ✅
- **Phase 4 (016)**: Autonomous memory pipeline ✅
- **Phase 5 (017-018)**: FS scan cache, token caching ✅
- **Phase 8 (023)**: CPython 3.14 Modernization ✅

## Phase 6 — Advanced Compression (Epics 019–021)
Deep content-aware compression from headroom port. Structured JSON crushing, AST-aware code squashing, and content-type routing to replace generic comment-stripping.

## Phase 7 — Memory Intelligence (Epic 022)
Smarter memory extraction with relevance scoring. Reduces extraction costs and improves knowledge quality.

## Extended Epic Inventory

| ID | Epic | Source | Status | Priority | Est. Lines |
|----|------|--------|--------|----------|------------|
| 019 | Content Router & Structured Compression | headroom | open | P1 | ~200 |
| 020 | SmartCrusher — JSON Compression | headroom | open | P1 | ~350 |
| 021 | AST-Aware Code Compression | headroom | open | P1 | ~400 |
| 022 | Relevance Scoring for Memory | headroom | open | P2 | ~250 |
| 023 | CPython 3.14 Modernization | Fast-Puppy | closed | P0 | ~3,000 |

## Phase 8 — Python 3.14 Modernization (Epic 023)

Full-stack upgrade to CPython 3.14. Removes legacy typing, adopts PEP 758 exception grouping syntax, PEP 749 annotationlib, free-threaded readiness, pathlib migration, t-string audit, and strict py314 tooling targets. Drops support for Python <3.14.

## Phase 9 — Performance Optimization: Libraries, Callbacks & Startup (Epic 027)

Focused optimization sweep targeting library consistency (json→orjson across 53 files), callback dispatch overhead (cached sorted lists, fast-path empty guards), startup time (parallel plugin loading, deferred models.json), and remaining Cython coverage gaps (JS/Go/Rust/C++ AST walkers). All items are performance-only with zero behavior changes.

## Extended Epic Inventory (continued)

| ID | Epic | Source | Status | Priority | Est. Lines |
|----|------|--------|--------|----------|------------|
| 024 | Code Health & Integration Audit | Code Review | closed | P0 | ~600 |
| 025 | Code Review Remediation | Code Review | open | P0 | ~500 |
| 026 | Findings Remediation | AI Review | open | P0 | ~2,000 |
| 027 | Performance Optimization | Deep Review | open | P0 | ~800 |
