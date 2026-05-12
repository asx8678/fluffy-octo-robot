---
id: "016-01"
title: "Session Scanner + Eligibility — Index Past Sessions, Detect Idle Candidates"
status: "open"
epic: "016"
labels: ["memory", "session", "scanner", "eligibility", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Scan session files from ~/.muse/sessions/. Filter for eligible sessions: idle for at least 3 hours, contain 10+ user messages, not currently active. Track which sessions have already been processed via a state file (processed_sessions.json) to avoid re-processing. Sort candidates by most recent first. Return list of eligible session paths for extraction.

## Motivation

Autonomous memory needs raw material. The scanner identifies sessions worth mining without re-processing the same data.

## Deliverables

- `scan_eligible_sessions(sessions_dir: Path, state_file: Path) → list[SessionInfo]`
- `SessionInfo` dataclass with path, message_count, last_active timestamp
- State file read/write

## Acceptance Criteria

- [x] sessions with <10 user messages filtered out
- [x] active sessions excluded
- [x] idle <3h excluded
- [x] state file prevents re-processing
- [x] handles missing sessions directory
- [x] sorted by recency

## Dependencies

Parent [Epic 016](016-epic-autonomous-memory.md).

## Estimated Effort

~100 lines, 45 min.
