---
id: "010-02"
title: "activate_skill Tool"
status: closed
epic: "010"
labels: ["skills", "activate", "tool", "consent", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Tool that agent calls to activate a skill. Takes skill name, checks registry, presents consent prompt to user (skill name, description, directory path). On approval: inject SKILL.md content into conversation, add skill directory to allowed read paths. On denial: return rejection message. Handle skill not found, already active.

## Motivation

Skills are powerful — they can read files, run scripts, and change behavior. Requiring explicit user consent before activation is a safety and transparency boundary.

## Deliverables

- `activate_skill` tool callable by the agent
- Consent prompt with skill name, description, and directory path
- On approval: inject `SKILL.md` into conversation, add directory to read allowlist
- On denial: return clear rejection message to the agent
- Error handling for skill not found and already active

## Acceptance Criteria

- [x] Agent can call `activate_skill` with a skill name
- [x] Registry lookup validates skill exists
- [x] User sees a consent prompt with name, description, and path
- [x] Approval injects `SKILL.md` content into the conversation context
- [x] Approval adds the skill directory to allowed read paths
- [x] Denial returns a rejection message the agent can act on
- [x] Already-active skills detected and reported without duplicate injection
- [x] Skill not found returns a helpful error to the agent

## Dependencies

Parent: [Epic 010](010-epic-skills-system.md) — Skills System

## Estimated Effort

~120 lines, 1 hour
