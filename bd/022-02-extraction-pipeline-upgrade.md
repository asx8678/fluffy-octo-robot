---
id: "022-02"
title: "Upgrade Memory Extraction Pipeline with Relevance Scoring"
status: open
epic: "022"
labels: ["relevance-scoring", "memory", "extraction", "integration", "P2"]
created: "2025-07-16"
priority: "P2"
---

## Summary

Integrate BM25 scoring into `extract_session_knowledge()` so that only high-relevance chunks are sent to the extraction LLM. Add project context collection and threshold configuration.

## Deliverables

- Modify `extract_session_knowledge()` in `extraction.py`
  - Accept optional `project_context: str` parameter
  - Split session transcript into turn-level chunks
  - Score chunks with BM25
  - Select top chunks by `MEMORY_RELEVANCE_THRESHOLD` (default 0.3)
  - Pass only selected chunks to extraction LLM
- Add `_collect_project_context()` helper — reads key project files
- Add env var `MEMORY_RELEVANCE_THRESHOLD` support
- Preserve backward compatibility: if scorer unavailable, send all chunks

## Acceptance Criteria

- [ ] 100-turn session → only ~20 turns sent to extraction LLM
- [ ] Project context auto-collected from cwd
- [ ] `MEMORY_RELEVANCE_THRESHOLD=0.5` → fewer chunks, `=0.0` → all chunks
- [ ] Existing memory tests still pass (extraction works with fewer chunks)
- [ ] Fallback: if BM25 fails, all chunks sent (no data loss)

## Dependencies

- [022-01](022-01-bm25-scorer.md) — BM25 scorer
- Parent: [Epic 022](022-epic-relevance-scoring.md)

## Estimated Effort

~100 lines, 1.5 hours
