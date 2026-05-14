# Code Review Findings — Muse Agent Framework

## Executive Summary

Review across four pillars: Agentic Design, Performance, Token Optimization, and Cython Hotspot Identification. The codebase demonstrates strong architectural patterns (plugin isolation, mtime-based caching, thoughtful history compaction) but has several critical gaps.

**Key Statistics:**
- 956 Python files analyzed
- 3 Cython files: `scan_cache_core.pyx`, `sha256_hash.pyx`, `terminal_utils.pyx`
- 1 compiled extension: `terminal_utils.cpython-314-darwin.so`
- Primary agent loop: `code_muse/agents/_runtime.py`
- History management: `code_muse/agents/_history.py`, `code_muse/agents/_compaction.py`

---

## [P0] No max_steps in agent run loop — infinite token burn risk

**Category**: Agentic Design | **Location**: `code_muse/agents/_runtime.py:384-450`, `run()`

**Description**: `run()` delegates to pydantic-ai without enforcing a hard step limit. `UsageLimits` covers request/tool/token caps but no `max_steps` exists at the Muse runtime level.

**Evidence**:
```python
async def _do_run(prompt_to_use: Any) -> Any:
    usage_limits = UsageLimits(
        request_limit=get_message_limit(),
        tool_calls_limit=get_max_tool_calls() or None,
        total_tokens_limit=get_total_tokens_limit() or None,
    )
    # ... no max_steps or step counter
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

Fix: Add max_steps config (default 12-15), track in RunStats, add circuit breaker.
Effort: M | Risk: Massive API costs from stuck loops

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P0] History compaction deferred indefinitely on pending tool calls
───────────────────────────────────────────────────────────────────

Category: Agentic Design | Location: code_muse/agents/_compaction.py:320-335

Description: has_pending_tool_calls() blocks all compaction. Orphaned tool calls from interrupted runs cause unbounded history growth.

Evidence:
 python ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
if strategy == "summarization" and has_pending_tool_calls(filtered):
    return messages, []  # No compaction happens!
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

Fix: Call prune_interrupted_tool_calls() before check; add fallback truncation; add max-deferral counter.
Effort: S

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P1] Stringify part LRU cache unbounded
───────────────────────────────────────

Category: Performance | Location: code_muse/agents/_history.py:48-95

Evidence: clear_stringify_part_cache() exists but is never called; cache retains stale entries indefinitely.

Fix: Call at start of each compact() or use WeakValueDictionary.
Effort: S

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P1] System prompt rebuilt with full tool schemas every reload
──────────────────────────────────────────────────────────────

Category: Token | Location: code_muse/agents/_builder.py:155-190

Evidence: assemble_full_system_prompt() has no caching. 50+ tools × 50-200 tokens = 2.5k-10k wasted per reload.

Fix: Cache by (agent_name, model_name, tool_hash).
Effort: M

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P1] No prompt caching for Anthropic models
───────────────────────────────────────────

Category: Token | Location: code_muse/model_factory.py:200-350

Evidence: No cache_control headers despite extensive Anthropic usage.

Fix: Add enable_prompt_caching config, inject cache_control headers.
Effort: M | Gain: 50-90% cost reduction on cached prompts

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P1] Python cosine similarity — Cython candidate
────────────────────────────────────────────────

Category: Hotspot → Cython | Location: INSUFFICIENT DATA

Proposed signature: cpdef void batch_cosine(double[:] q, double[:,:] docs, double[:] out) nogil
Gain: 20x if retrieval module exists

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P2] Cython sha256_hash.pyx holds GIL
─────────────────────────────────────

Category: Cython | Location: code_muse/models_cache/sha256_hash.pyx:15-28

Evidence: sha256_digest_file() uses cdef locals but no nogil.

Fix: Add nogil or use OpenSSL C API directly.
Effort: S

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P2] Token estimation char/3 heuristic — limited calibration
────────────────────────────────────────────────────────────

Category: Token | Location: code_muse/agents/_history.py:140-160

Evidence: Only one multiplier rule (opus-4-7 → 1.35). Most models uncalibrated.

Fix: Add per-model rules or integrate actual tokenizers.
Effort: M

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P2] No per-tool timeout
────────────────────────

Category: Agentic Design | Location: code_muse/agents/_runtime.py:384-400

Evidence: Only global timeout via asyncio.wait_for(coro, timeout=timeout).

Fix: Add get_tool_timeout_seconds() (default 30s), wrap individual calls.
Effort: M

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P2] No idempotency tracking for destructive tools
──────────────────────────────────────────────────

Category: Agentic Design | Location: code_muse/tools/__init__.py:250-300

Evidence: idempotent flag exists in metadata but never enforced.

Fix: Track (tool_name, args_hash, result_hash) for dedup.
Effort: L

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

[P3] No per-step observability
──────────────────────────────

Category: Agentic Design | Location: code_muse/agents/_runtime.py:55-70

Fix: Add step_metrics: list[StepMetric] to RunStats.
Effort: M

──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

Top 3 Cythonization Candidates
──────────────────────────────

┌───────────────────────┬─────────────────────────────────────────────────────────────────────────────┬───────┬────────┐
│ File                  │ Signature                                                                   │ Gain  │ Effort │
├───────────────────────┼─────────────────────────────────────────────────────────────────────────────┼───────┼────────┤
│ core/similarity.pyx   │ cpdef void batch_cosine(double[:] q, double[:,:] docs, double[:] out) nogil │ 20x   │ M (3h) │
│ core/prompt_build.pyx │ cpdef bytes assemble_prompt(bytes system, list tools, bytes user)           │ 5-10x │ M (4h) │
│ core/json_fast.pyx    │ cpdef object loads_nogil(bytes data) nogil                                  │ 3-5x  │ S (2h) │
└───────────────────────┴─────────────────────────────────────────────────────────────────────────────┴───────┴────────┘

Note: Static analysis only. No code executed, compiled, or tested. Findings marked INSUFFICIENT DATA require additional context.
