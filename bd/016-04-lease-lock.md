---
id: "016-04"
title: "Lease Lock + Secret Scanning — Prevent Concurrent Extraction, Scan for Credentials"
status: "open"
epic: "016"
labels: ["memory", "lease", "lock", "secret", "security", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Implement lease-based locking to prevent multiple CLI instances from running extraction simultaneously. Lock file in memory directory with PID + timestamp. 30-minute lease timeout with stale lease detection (if lease holder PID no longer running, lease can be broken). Before writing MEMORY.md or memory_summary.md to disk, scan output for secrets (API key patterns, token patterns, private key headers) using regex rules and SHA-256 hash check against known secrets. Reject or quarantine outputs with detected secrets.

## Motivation

Concurrent extraction wastes resources. Secret scanning prevents accidental credential persistence in memory files.

## Deliverables

- `acquire_memory_lease(project_dir: Path) → LeaseHandle`, `release_lease(handle)`
- `scan_for_secrets(text: str) → list[SecretMatch]`
- `SecretMatch` with pattern_name, location

## Acceptance Criteria

- [x] only one instance holds lease at a time
- [x] stale lease broken after 30 min
- [x] secrets detected before write
- [x] common secret patterns covered
- [x] quarantined files moved to .quarantine/
- [x] lease released on normal exit

## Dependencies

Parent [Epic 016](016-epic-autonomous-memory.md).

## Estimated Effort

~80 lines, 40 min.
