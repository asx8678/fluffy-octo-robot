---
id: "012-03"
title: "SHA-256 Content Hash Utility — Content-Addressed Cache Keys"
status: closed
epic: "012"
labels: ["hash", "sha256", "content", "utility", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Provide a small utility that computes SHA-256 hex digests of bytes or file contents. Used by cache systems that want content-based keys rather than path-based keys.

## Motivation

Content hashing enables cache invalidation by content change rather than timestamp, useful for prompt caching and artifact deduplication.

## Deliverables

- Two functions: sha256_digest(data: bytes) -> str, sha256_digest_file(path: Path) -> str.

## Acceptance Criteria

- [x] produces 64-char hex string
- [x] deterministic outputs
- [x] handles empty bytes
- [x] file version streams large files efficiently

## Dependencies

Parent: [Epic 012](012-epic-models-cache.md)

## Estimated Effort

~20 lines, 10 min
