---
id: "008-02"
title: "Conversation Snapshots"
status: closed
epic: "008"
labels: ["checkpointing", "snapshot", "json", "serialization", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Serialize current session state (messages list + pending tool calls + agent state) to JSON before each checkpoint. Store in ~/.muse/history/<project_hash>/snapshots/. Include turn_id, timestamp, tool_call_id. Handle large message histories efficiently.

## Motivation

Rewinding files alone is not enough — we also need to restore the agent's mental state (conversation history, pending tool calls, and agent state). Snapshots make full-session rewind possible.

## Deliverables

- JSON snapshot serializer for messages, pending tool calls, and agent state
- Snapshot storage in the history directory
- Metadata fields: turn_id, timestamp, tool_call_id
- Efficient handling for large message histories (streaming or chunked)

## Acceptance Criteria

- [x] Snapshot JSON contains messages, pending tool calls, and agent state
- [x] Metadata includes turn_id, timestamp, and tool_call_id
- [x] Snapshots stored in ~/.muse/history/<project_hash>/snapshots/
- [x] Large message histories serialize without memory spikes
- [x] Snapshots are valid JSON and loadable without data loss
- [x] Snapshot files named deterministically (e.g., snapshot_<timestamp>.json)

## Dependencies

Parent: [Epic 008](008-epic-checkpointing.md) — Checkpointing + Rewind

## Estimated Effort

~100 lines, 45 min
