---
id: "002-04"
title: "Git Mutations — Add/Commit/Push/Pull Compact Responses"
status: closed
epic: "002"
labels: ["git", "mutations", "add", "commit", "push", "pull", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Compress mutation commands (`git add`, `git commit`, `git push`, `git pull`, `git merge`) into minimal success responses like `ok` or `ok abc1234`.

## Motivation

Mutation output is mostly progress bars and remote chatter. The agent usually only cares whether it succeeded and what the resulting commit/branch state is.

## Deliverables

- `git add` → `ok` or list of added files (if `-v`)
- `git commit` → `ok <short-hash>` + subject
- `git push` → `ok` or remote response summary
- `git pull` → `ok` or merge summary
- `git merge` → `ok` or conflict warning

## Acceptance Criteria

- [x] Successful add returns `ok`
- [x] Successful commit returns `ok <hash>` and first line of message
- [x] Successful push returns `ok` + branch info
- [x] Pull with fast-forward returns `ok` + files changed count
- [x] Any error or conflict returns raw output (do not hide failures)

## Dependencies

Parent: [Epic 002](002-epic-git-strategies.md) — Git Output Compression

## Estimated Effort

~70 lines, 45 minutes
