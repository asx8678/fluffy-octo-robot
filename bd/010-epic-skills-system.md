---
id: "010"
title: "Epic: Skills System — Activation + Consent, Progressive Disclosure, Background Jobs"
status: closed
epic: "010"
labels: ["epic", "skills", "activation", "consent", "discovery", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Port Gemini CLI's Agent Skills system. Skills are self-contained directories with SKILL.md + assets. Lifecycle: discovery (scan tiers at startup) → activation (agent calls `activate_skill`) → consent (user confirmation) → injection (SKILL.md content + directory access). Progressive disclosure saves context tokens.

## Motivation

Muse has agent_skills plugin but without activation/consent gating or background job patterns. Gemini's model is more secure and context-efficient.

## Deliverables

1. Skill discovery (scan built-in, extension, user, workspace tiers)
2. `activate_skill` tool (consent-gated, injects SKILL.md + grants directory access)
3. Skill directory structure (SKILL.md, scripts/, references/, assets/)
4. Background job pattern (async-pr-review style: spawn headless agent, ephemeral git worktree)

## Acceptance Criteria

- [x] Skills discovered from 4 tiers with correct precedence rules
- [x] `activate_skill` requires explicit user consent before injection
- [x] Injection adds SKILL.md content to conversation + directory to allowed paths
- [x] `deactivate_skill` removes skill content and directory access
- [x] Background jobs run headless gemini with `-p` flag on ephemeral worktree

## Dependencies

Depends on Epic 009 (Stream Parser) for markup handling, Epic 011 (Policy Engine) for consent rules.

## Estimated Effort

~400 lines, 3.5 hours

## Children

- [010-01](010-01-skill-discovery.md) — Skill Discovery + Registry (scan tiers, dedupe by name, precedence rules)
- [010-02](010-02-activate-skill.md) — activate_skill Tool (consent gate, SKILL.md injection, directory permissions)
- [010-03](010-03-skill-directory.md) — Skill Directory Structure (SKILL.md format, scripts/, references/, assets/)
- [010-04](010-04-background-jobs.md) — Background Job Skills (async-pr-review pattern, headless agent invocation)
