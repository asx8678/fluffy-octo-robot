---
id: "027-05"
title: "Move token estimation after dirty-flag check (P2)"
status: closed
epic: "027"
labels: ["performance", "session", "P2"]
created: "2026-06-10"
priority: "P2"
---

## Summary

In `session_storage.py::save_session()`, token estimation happens **before** the dirty-flag check. For large histories (1000+ messages) that haven't changed, this wastes CPU cycles computing token estimates that are never used.

## Current Code

```python
def save_session(*, history, session_name, ...):
    session_data = _wrap_messages(history)
    
    # Dirty-flag check
    current_hash = _hash_session_data(session_data)
    if current_hash is not None and _LAST_SAVED_HASHES.get(hash_key) == current_hash:
        total_tokens = sum(token_estimator(message) for message in history)  # Wasted!
        return SessionMetadata(total_tokens=total_tokens, ...)  # ...but we return anyway
    
    # ... actual write path
```

## Fix

Move the `total_tokens` computation after the dirty-flag check. Since `token_estimatator` is only used for the metadata return value (which is the same on dirty-hit as on write), compute it lazily.

## Deliverables

- [ ] Token estimation moved after dirty-flag return
- [ ] Metadata constructed without estimating tokens when dirty-flag hits
- [ ] Token estimation still computed correctly on actual save

## Acceptance Criteria

- [ ] `token_estimator` not called on dirty-flag hit cache
- [ ] Session metadata correctly populated on first save
- [ ] Autosave dirty-check test covers this path

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)

## Estimated Effort

~30 lines changed, 1 hour
