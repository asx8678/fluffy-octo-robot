---
id: "012-01"
title: "Models Cache Writer — Pre-Seed Model List at Build Time"
status: closed
epic: "012"
labels: ["models", "cache", "json", "startup", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Write a models_cache.json file to ~/.muse/ that contains all picker-visible models converted from models_dev_api.json. This prevents network fetch on cold startup. Include fetched_at timestamp and client_version for freshness checking.

## Motivation

Muse currently fetches model lists on every startup. A pre-seeded cache means instant model list display.

## Deliverables

- Function write_models_cache() that reads models_dev_api.json, filters picker-visible entries, converts to ModelInfo format, and writes models_cache.json.

## Acceptance Criteria

- [x] cache file created at correct path
- [x] contains all visible models
- [x] fetched_at is current time
- [x] client_version matches package
- [x] handles missing source file gracefully

## Dependencies

Parent: [Epic 012](012-epic-models-cache.md)

## Estimated Effort

~60 lines, 30 min
