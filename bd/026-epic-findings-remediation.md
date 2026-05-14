---
id: "026"
title: "Epic: Findings Remediation — Agent Safety, Performance & Cython Honesty"
status: open
epic: "026"
labels: ["epic", "agent-safety", "performance", "cython", "P0"]
created: "2026-05-19"
priority: "P0"
---

## Summary

Consolidated remediation of 18 issues discovered by 8 AI reviewers (Gemini Flash, Hy, Kiro, Seedance, Kimi, Mimo, Trinity, GLM 5.1) who analyzed the `code_muse/` codebase across four pillars: Agentic Design, Performance, Token Optimization, and Cython Hotspots.

Kiro's findings were verified by running code against the live codebase. All findings were cross-referenced against live code for this analysis.

## Verification Results

### Already Fixed (Stale findings — no action needed)
- `resolve_env_var_in_header`: Already uses `os.path.expandvars()` — fix applied
- Ruff `target-version`: Already set to `py314`
- `frontend_emitter.on_stream_event`: Already sync (not async)
- `_trigger_callbacks_sync`: Already has 30s timeout
- `prune_interrupted_tool_calls`: Already called before compaction check
- System prompt rebuild: Only on agent build (not every step) — less impactful

### Confirmed Real Issues

| Priority | Issue | File | Effort | Gain |
|----------|-------|------|--------|------|
| P0 | No hard max_steps guard | _runtime.py | S | Prevents infinite token burn |
| P0 | ToolErrorTracker blocks all tools | _runtime.py | S | Prevents unnecessary aborts |
| P1 | stringify_part LRU no weakref | _history.py | S | Correctness fix |
| P1 | window_matching O(n×m) allocation | window_matching.py | S | 2-3x speedup |
| P1 | gemini_schema deepcopy per $ref | gemini_schema.py | S | 2-3x faster schema |
| P1 | Summarization event loop per call | summarization_agent.py | M | -40ms per run |
| P1 | BM25Scorer dict rebuilt per call | bm25_scorer.pyx | M | 10-30x memory retrieval |
| P2 | Cython .pyx files Python in disguise | Multiple .pyx files | M | Honest build |
| P2 | ast_compressor Python recursion | ast_compressor.pyx | L | 15x for large files |
| P2 | Semantic compression 30 regex passes | compressor.py | L | 5-10x per step |
| P2 | json_compressor json.dumps per scalar | json_compressor.pyx | M | 3-5x compression |
| P2 | Blocking history_processor | _compaction.py | L | Prevent UI freeze |
| P2 | agent_manager global mutable state | agent_manager.py | M | Free-threaded safety |
| P2 | 34 files exceed 600-line cap | Various | L | Maintainability |
| P2 | 668 broad except Exception clauses | 163 files | L | Debuggability |
| P3 | estimate_tokens coarse heuristic | _history.py | M | Better compaction |
| P3 | Duplicate _estimate_tokens | subagent_stream_handler.py | S | Consistency |
| P3 | Magic 50000 token threshold | _history.py | S | Configurable |

## Acceptance Criteria

- [ ] max_steps config (default 15) enforced in agent run loop
- [ ] _ToolErrorTracker tracks errors per-tool-name
- [ ] stringify_part LRU cache has weakref.finalize cleanup
- [ ] window_matching.py uses pre-joined strings to avoid per-iteration allocation
- [ ] gemini_schema.py replaces deepcopy with orjson round-trip
- [ ] summarization_agent reuses event loop across calls
- [ ] BM25Scorer pre-builds corpus_lookup dict in fit()
- [ ] Cython .pyx files either properly Cythonized (nogil, boundscheck) or reverted to .py
- [ ] history_processor doesn't block event loop during summarization
- [ ] agent_manager globals wrapped in thread-safe class
- [ ] 600-line cap enforced across codebase
- [ ] All existing tests pass after each change

## Dependencies

None — self-contained cleanup epic.

## Estimated Effort

~2,000 lines changed, 40-60 hours total across all 18 issues

## Children

- P0: Add hard max_steps guard
- P0: Fix ToolErrorTracker per-tool tracking
- P1: Add weakref.finalize to stringify_part LRU
- P1: Optimize window_matching pre-join
- P1: Replace deepcopy in gemini_schema
- P1: Reuse event loop in summarization_agent
- P1: Cache BM25 corpus_lookup dict
- P2: Audit Cython .pyx files
- P2: Cythonize ast_compressor
- P2: Optimize semantic compression regex
- P2: Optimize json_compressor
- P2: Fix blocking history_processor
- P2: Wrap agent_manager globals
- P2: Enforce 600-line cap
- P2: Audit broad except clauses
- P3: Integrate model-specific tokenizers
- P3: Fix duplicate _estimate_tokens
- P3: Make 50000 threshold configurable
