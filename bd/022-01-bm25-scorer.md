---
id: "022-01"
title: "Build BM25 Relevance Scorer — Pure Python Token-Based Scoring"
status: open
epic: "022"
labels: ["relevance-scoring", "bm25", "P2"]
created: "2025-07-16"
priority: "P2"
---

## Summary

Implement BM25 relevance scoring in pure Python (no external deps). Score text chunks against a project context (key files, recent edits, active task) to rank which chunks contain useful information.

## Motivation

BM25 is the proven baseline for text relevance. It's fast, interpretable, and needs no model downloads. Perfect as the default scorer for memory extraction.

## Deliverables

- `BM25Scorer` class: `score(chunks: list[str], context: str) -> list[float]`
- Tokenization: simple whitespace + punctuation split
- TF-IDF-like scoring with length normalization
- `select_top_chunks(chunks, scores, threshold) -> list[str]`
- Unit tests with known-relevant and known-irrelevant text

## Acceptance Criteria

- [ ] Chunk containing project name scores higher than generic "hello world"
- [ ] Error/exception chunks score high (always relevant)
- [ ] Boilerplate ("running tests...") scores low
- [ ] `select_top_chunks` returns correct count based on threshold
- [ ] Empty context → uniform low scores, all chunks kept

## Dependencies

Parent: [Epic 022](022-epic-relevance-scoring.md)

## Estimated Effort

~80 lines, 1 hour
