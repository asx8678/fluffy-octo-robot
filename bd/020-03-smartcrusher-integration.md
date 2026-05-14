---
id: "020-03"
title: "Register SmartCrusher as JSON Strategy + Wire to Content Router"
status: closed
epic: "020"
labels: ["smartcrusher", "integration", "registry", "P1"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Register the completed SmartCrusher as the `json` strategy, replacing the stub from 019-03. Wire it into the content router so JSON output automatically compresses.

## Deliverables

- Replace stub `json` strategy with SmartCrusher in StrategyRegistry
- Strategy function signature: `(command, stdout, stderr, exit_code, verbosity) -> ShellCommandOutput`
- Content router integration verified: `cat package.json` → detected JSON → SmartCrusher applied
- Add `/compress json` custom command for manual use
- Unit test: full pipeline from shell command → compressed output

## Acceptance Criteria

- [ ] `json` strategy returns `ShellCommandOutput` with compressed stdout
- [ ] Content router correctly routes JSON output to SmartCrusher
- [ ] `/compress json` command available
- [ ] Existing `unknown` passthrough still works for non-JSON
- [ ] Token reduction verified on sample outputs

## Dependencies

- [020-02](020-02-json-compressor-core.md) — compression engine
- [019-02](019-02-content-router-integration.md) — content router
- Parent: [Epic 020](020-epic-smartcrusher.md)

## Estimated Effort

~80 lines, 1 hour
