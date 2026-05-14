---
id: "025-02"
title: "Replace static badges with dynamic CI badges (P1)"
status: closed
epic: "025"
labels: ["docs", "readme", "P1"]
created: "2026-05-18"
priority: "P1"
---

## Summary

Replace the static shield.io "Build-Passing" and "Tests-Passing" badges in README.md with real dynamic GitHub Actions status badges.

## Motivation

The current badges are static images that always show "Passing" regardless of actual CI status. This is misleading to potential users and evaluators. The CI workflows exist (ci.yml, nightly.yml, publish.yml) but the badges don't reflect their actual status.

## Current (static)
```
[![Build Status](https://img.shields.io/badge/Build-Passing-brightgreen?...)](...)
[![Tests](https://img.shields.io/badge/Tests-Passing-success?...)](...)
```

## Target (dynamic)
```
[![CI](https://img.shields.io/github/actions/workflow/status/asx8678/muse/ci.yml?style=for-the-badge&logo=github)](https://github.com/asx8678/muse/actions)
```

## Deliverables

- [ ] Replace Build Status badge with dynamic `github/actions/workflow` badge for ci.yml
- [ ] Replace Tests badge with dynamic badge pointing to test workflow
- [ ] Verify badges render correctly in rendered README

## Dependencies

Parent: [Epic 025](025-epic-code-review-remediation.md)

## Estimated Effort

~5 lines changed, 5 minutes
