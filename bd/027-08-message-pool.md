---
id: "027-08"
title: "Message pool for frequently-emitted message types (P3)"
status: closed
epic: "027"
labels: ["performance", "messaging", "GC", "P3"]
created: "2026-06-10"
priority: "P3"
---

## Summary

`MessageBus.emit()` creates new pydantic `TextMessage` instances for every `emit_info()`/`emit_warning()`/`emit_error()` call. With hundreds of calls per agent run, this generates significant GC pressure. Use a message pool or pre-allocated templates.

## Current Code

```python
def emit_info(self, text: str) -> None:
    message = TextMessage(level=MessageLevel.INFO, text=text, category=MessageCategory.SYSTEM)
    self.emit(message)  # New pydantic object every call
```

Each `TextMessage()` call:
- Allocates a new pydantic BaseModel (field validation, default factories)
- Generates a UUID via `str(uuid4())` (16 random bytes → hex string)
- Creates a `datetime.now(UTC)` timestamp
- Eventually GC'd, causing collection pressure

## Fix Options

Option A (low effort): **Pre-allocated templates** — create one `TextMessage` per level, then `model_copy(update={"text": text})`:
```python
_INFO_TEMPLATE = TextMessage(level=MessageLevel.INFO, text="", category=MessageCategory.SYSTEM)
def emit_info(self, text: str) -> None:
    self.emit(_INFO_TEMPLATE.model_copy(update={"text": text, "id": str(uuid4())}))
```

Option B (medium effort): **Lazy id/timestamp** — only generate UUID and timestamp when the message is actually consumed (not when emitted). Requires async-friendly lazy fields.

Option C (highest effort): **Message pool** — pre-allocate a ring buffer of N messages per level, recycle them:
```python
class MessagePool:
    def acquire(self, level: MessageLevel, text: str) -> TextMessage: ...
    def release(self, msg: TextMessage) -> None: ...  # Reset fields for reuse
```

## Recommendation

Start with Option A (templates + `model_copy`). If profiling shows GC still significant, consider Option C.

## Deliverables

- [ ] Pre-allocated `TextMessage` templates for each `MessageLevel`
- [ ] `emit_text()` uses `model_copy(update=...)` instead of `TextMessage(...)` constructor
- [ ] UUID generation deferred (only when message is consumed by a renderer)
- [ ] Benchmark shows reduced GC pressure

## Acceptance Criteria

- [ ] Message creation for frequent types does not allocate new pydantic model from scratch
- [ ] All message fields (id, timestamp, text, level) are correctly populated
- [ ] No regression in message ordering or dedup
- [ ] All tests pass

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)

## Estimated Effort

~80 lines changed, 2 days (includes benchmarking)
