---
id: "022"
title: "Epic: Relevance Scoring — Smarter Memory Extraction via BM25 & Embeddings"
status: closed
epic: "022"
labels: ["epic", "relevance-scoring", "P2", "memory", "headroom-port"]
created: "2025-07-16"
priority: "P2"
---

## Summary

Add relevance scoring to the autonomous memory pipeline so that only high-value session chunks go to the extraction LLM. BM25 (pure Python) scores chunks against project context; optional embedding scorer uses existing model infrastructure. Reduces extraction cost 60-80%.

## Motivation

Current `extract_session_knowledge()` sends the full session transcript to an LLM for knowledge extraction. Most of a coding session is boilerplate — "running tests...", "looking at file...". Scoring chunks before extraction means the LLM only sees the 20% that matters.

## Source

Ported from **headroom**'s `RelevanceScorer` — BM25 + embedding hybrid scoring, chunk selection by cumulative score threshold.

## Deliverables

1. BM25 scorer — pure Python, no new dependencies
2. Chunk scoring pipeline — split session into chunks, score each, select top-N
3. Integration into `extraction.py` — score before LLM call
4. Optional embedding scorer using existing model (for higher quality)
5. Configurable threshold: `MEMORY_RELEVANCE_THRESHOLD` env var

## Acceptance Criteria

- [ ] Session of 100 turns → only top 20 go to extraction LLM
- [ ] BM25 scoring correlates with human judgment of "important turns"
- [ ] Extraction quality does not degrade (same key facts found)
- [ ] Memory pipeline runtime drops by > 50%
- [ ] Empty/short sessions handled gracefully (no chunks dropped)
- [ ] Threshold configurable and defaults to sensible value

## Dependencies

- Epic 016 (Autonomous Memory Pipeline) — hooks into extraction
- Epic 006 (Token Tracking) — uses session data

## Estimated Effort

~250 lines, 2–3 hours

## Children

- [022-01](022-01-bm25-scorer.md)
- [022-02](022-02-extraction-pipeline-upgrade.md)
