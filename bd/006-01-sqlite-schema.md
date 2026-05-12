---
id: "006-01"
title: "SQLite Schema + Connection Management + Auto-Cleanup"
status: closed
epic: "006"
labels: ["tracking", "sqlite", "schema", "database", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Design and implement the SQLite schema for token tracking, plus connection management and automatic cleanup of records older than 90 days.

## Motivation

A lightweight local database is the right tradeoff for tracking history. SQLite requires no external server, is portable, and is natively supported in Python.

## Deliverables

- Schema: `executions` table with columns for command, strategy, raw tokens, compressed tokens, savings ratio, timestamp, session ID
- Connection manager with path resolution (`~/.local/share/rtk-puppy/`)
- Auto-cleanup job: delete records older than 90 days
- Migration stub for future schema changes

## Acceptance Criteria

- [x] Schema supports all required fields with appropriate types
- [x] DB file created automatically on first use
- [x] Connection is pooled or reused safely
- [x] Cleanup runs periodically (e.g., every 100 inserts or on startup)
- [x] 90-day retention is enforced
- [x] Schema is versioned for future migrations

## Dependencies

Parent: [Epic 006](006-epic-tracking.md) — Token Tracking Database

## Estimated Effort

~100 lines, 1 hour
