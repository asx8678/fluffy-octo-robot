---
id: "024-16"
title: "Minor Code Cleanup: Exception Tuples, compress_dict, TODO, Spinner, Session (P2)"
status: open
epic: "024"
labels: ["cleanup", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Group of small items:
1. Redundant parent+child exception tuples (`JSONDecodeError`+`ValueError`, `PermissionError`+`OSError`)
2. `_compress_dict` level-0 fallback keeps all keys instead of compact mode
3. PEP 750 TODO comment in `database.py`
4. `ConsoleSpinner` started on every agent call
5. Session data full JSON rewrite per update

## What

Collapse redundant exception tuples to the more specific child only. Make `_compress_dict` level-0 fallback keep top-3 keys in compact mode. Document or resolve PEP 750 TODO. Debounce `ConsoleSpinner` so it only starts on calls >100ms; skip when `-p` (plain) flag present. Debounce session writes with dirty flag / periodic flush.

## Deliverables

- [ ] Exception tuples fixed (specific child only)
- [ ] `compress_dict` fallback keeps top-3 keys
- [ ] TODO documented or resolved
- [ ] Spinner debounced, `-p` skipped
- [ ] Session writes debounced
- [ ] Tests pass

## Acceptance Criteria

- [ ] No redundant parent+child exception tuples remain
- [ ] `_compress_dict` compact mode active at level 0
- [ ] PEP 750 TODO has documented follow-up or is resolved
- [ ] Spinner does not spin on fast / plain-mode calls
- [ ] Session writes batched or debounced (not per-update full rewrite)
- [ ] All tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~120 lines changed, 2 hours
