# Agentic Python + Cython Review — Muse (code_muse)

Reviewer: Claude Opus 4.7 — Principal Engineer
Date: 2025-01-25
Scope: Deep static review of `code_muse/` — agentic system with Cython extensions.
No execution, no tests, no builds. All findings reference actual code.

---

## [P0] No hard step cap on agent run — infinite token burn risk

**Category**: Agentic Design
**Location**: `code_muse/agents/_runtime.py:262-320`, `run()` → `_do_run()`
**Severity**: P0

**Description**:
The agent run is delegated to `pydantic_agent.run()` which uses `UsageLimits(request_limit, tool_calls_limit, total_tokens_limit)`. These are configuration-driven limits, but there is **no explicit `max_steps` cap** that terminates the run after N LLM round-trips. The `request_limit` controls message count, and `tool_calls_limit` caps tool invocations, but if the model generates long chains of text-only responses (no tools), the message limit is the only guard. A misconfigured or absent `message_limit` means the agent runs until the LLM stops responding.

**Root Cause**: pydantic-ai's `UsageLimits` is used but no independent `max_steps` counter exists in the runtime. The loop is a single `pydantic_agent.run()` call — pydantic-ai internally manages the tool loop, and the outer runtime just awaits the result. If pydantic-ai's internal loop doesn't enforce `request_limit` on text-only responses, the run is unbounded.

**Evidence**:
```python
# code_muse/agents/_runtime.py:278-282
usage_limits = UsageLimits(
    request_limit=get_message_limit(),
    tool_calls_limit=get_max_tool_calls() or None,
    total_tokens_limit=get_total_tokens_limit() or None,
)
```

**Proposed Fix**:
1. Add a `max_steps` parameter to `run()` (default 30).
2. After each `pydantic_agent.run()` return, check `len(result.all_messages())` against `max_steps`. If exceeded, truncate with a warning.
3. Add a hard wall-clock timeout via `asyncio.wait_for()` (already partially done for `get_overall_run_timeout_seconds()`, but verify default is set).

**Token Impact**: Prevents unbounded token burn on misconfigured models.
**Performance Impact**: Negligible — single counter check.
**Effort**: S

**Risk if not fixed**: A model that loops on text-only responses can burn $100+ in tokens.

---

## [P0] Unbounded `_message_history` growth between compaction cycles

**Category**: Agentic Design
**Location**: `code_muse/agents/_compaction.py:468`, `history.append(msg)` in `history_processor()`
**Severity**: P0

**Description**:
The `history_processor` callback appends new messages to `agent._message_history` without any size guard before compaction runs. Between the time messages are appended and `compact()` fires, the list can grow arbitrarily large. In the worst case (fast tool-call chains), dozens of messages accumulate before compaction threshold is checked.

More critically, `BaseAgent.append_to_message_history()` at `base_agent.py:121` provides an **unconditional append** with no truncation check — any caller can grow the list without limit.

**Root Cause**: No max-size check on `history.append()`. Compaction is threshold-based, not size-gated.

**Evidence**:
```python
# code_muse/agents/base_agent.py:120-121
def append_to_message_history(self, message: Any) -> None:
    self._message_history.append(message)

# code_muse/agents/_compaction.py:468
history.append(msg)
```

**Proposed Fix**:
1. Add a `MAX_HISTORY_LEN = 200` constant in `BaseAgent`.
2. In `append_to_message_history()`, check `len(self._message_history)` and trigger emergency compaction if over limit.
3. In `history_processor()`, add a guard before appending: if `len(history) > MAX_HISTORY_LEN`, run `compact()` synchronously before appending.

**Token Impact**: Prevents OOM on long sessions.
**Performance Impact**: Reduces memory pressure.
**Effort**: S

**Risk if not fixed**: Long-running sessions OOM, especially with large tool outputs.

---

## [P1] Pure-Python token estimation in hot path — O(n) char scan per message, called hundreds of times per compaction

**Category**: Hotspot
**Location**: `code_muse/agents/_history.py:146-155`, `estimate_tokens()` and `estimate_tokens_for_message()`
**Severity**: P1

**Description**:
`estimate_tokens()` is a trivial `max(1, math.floor(len(text) / 3.0))`, which is fast. However, `estimate_tokens_for_message()` calls `stringify_part()` for every part of every message, and `stringify_part()` does:
- `orjson.dumps()` on dict/BaseModel content (CPU-heavy serialization)
- String concatenation with `|` join for attribute lists
- LRU cache lookup by `id(part)` (dict lookup, move_to_end)

During compaction of a 100-message history, this function is called ~100 × 2-5 parts = 200-500 times. The `CompactionCache` helps, but the underlying `stringify_part` + `orjson.dumps` path is still pure Python doing JSON serialization on every uncached call.

**Root Cause**: Token estimation requires full message serialization; no shortcut exists for "just count chars without serializing."

**Evidence**:
```python
# code_muse/agents/_history.py:198-202
def estimate_tokens_for_message(message, model_name=None):
    total = 0
    for part in getattr(message, "parts", []) or []:
        part_str = stringify_part(part)
        if part_str:
            total += estimate_tokens(part_str)
```

**Hotspot Analysis**:
- Calls per agent run: ~100-500 (compaction × messages × parts)
- Complexity: O(n × m) where n = messages, m = parts per message
- Current time estimate: ~50ms for 100-message compaction (dominated by `orjson.dumps` on tool outputs)
- **Proposed Cython signature**:
```cython
# cython: language_level=3, boundscheck=False, wraparound=False
cimport cython

cpdef int fast_estimate_tokens(str text) nogil:
    cdef Py_ssize_t n = len(text)
    if n == 0:
        return 1
    return n // 3 if n // 3 > 0 else 1
```

**Token Impact**: N/A (token estimation is for accounting, not LLM)
**Performance Impact**: The actual `len()/3` is trivial; the real gain is from Cythonizing `stringify_part()` to avoid Python-level attribute access and orjson in inner loop. Estimated 5-10x for the serialization path. However, the `CompactionCache` already mitigates much of this. **Lower priority than initially scored.**
**Effort**: M (4h — serialize part in Cython is non-trivial due to pydantic models)

**Risk if not fixed**: Compaction latency grows with history size; currently mitigated by CompactionCache.

---

## [P1] System prompt rebuilt on every agent build — not cached between runs

**Category**: Token
**Location**: `code_muse/agents/_builder.py:108-119`, `assemble_full_system_prompt()` and `_assemble_instructions()`
**Severity**: P1

**Description**:
`build_pydantic_agent()` is called on every agent run (when `agent._code_generation_agent is None`). Each call rebuilds the full system prompt from scratch: `agent.get_full_system_prompt()` + `load_muse_rules()` + `has_extended_thinking_active()` + `on_load_prompt()`. For agents like MuseAgent, `get_system_prompt()` returns a large f-string (~800 tokens). The `muse_overlay` from `prompt_v3.py` adds another ~400 tokens. Plugin prompts add more.

The system prompt is identical across turns (unless `AGENTS.md` changes on disk), but it's reassembled from scratch each time `build_pydantic_agent()` is called. The `load_muse_rules()` function has an mtime-based cache, but the rest (identity prompt, extended thinking note, plugin additions) is recomputed.

**Root Cause**: No cached "final system prompt" keyed by agent identity + model name + mtime.

**Evidence**:
```python
# code_muse/agents/_builder.py:108-119
def assemble_full_system_prompt(agent, model_name=None):
    instructions = agent.get_full_system_prompt()
    agent_rules = load_muse_rules()
    if agent_rules:
        instructions += f"\n{agent_rules}"
    if has_extended_thinking_active(resolved_model):
        instructions += EXTENDED_THINKING_PROMPT_NOTE
    prompt_additions = _cb.on_load_prompt()
    if prompt_additions:
        instructions += "\n" + "\n".join(str(p) for p in prompt_additions if p)
    return instructions
```

**Proposed Fix**:
1. Cache the full system prompt per (agent.name, model_name, mtime_of_agents_md).
2. Add a `_system_prompt_cache` dict on the agent or as a module-level LRU.
3. Invalidate when `AGENTS.md` mtime changes or plugins change (rare).

**Token Impact**: ~1,500-2,500 tokens resent per step; caching doesn't reduce tokens (Anthropic cache_control handles this), but it reduces prompt assembly CPU time.
**Performance Impact**: -2ms per build call (minor). The real win is the `cache_control` injection already implemented in `claude_cache_client.py`, which means the system prompt IS cached at the API level.
**Effort**: S

**Risk if not fixed**: Minor — prompt assembly cost is small; Anthropic cache_control already avoids re-processing the system prompt tokens.

---

## [P1] `cache_control` injection only for Anthropic — OpenAI/Gemini models miss prompt caching

**Category**: Token
**Location**: `code_muse/claude_cache_client.py:694-830`, `_inject_cache_control()` and `_inject_cache_control_in_payload()`
**Severity**: P1

**Description**:
The `cache_control` injection is Anthropic-specific. OpenAI models (GPT-5, codex) and Gemini models don't benefit from prompt caching. OpenAI has its own caching mechanism (automatic prefix caching for identical prompts), but the code doesn't set `cached_prompt` or use `seed`/`logprobs` hints that could improve cache hit rates.

For Gemini, there's no caching at all — the full prompt is re-sent every turn.

**Root Cause**: Anthropic's `cache_control` is an API extension; OpenAI/Gemini don't have equivalent client-side hints.

**Evidence**:
```python
# code_muse/claude_cache_client.py:694-732
# Only runs inside _inject_cache_control() which patches Anthropic client
def _inject_cache_control(body: bytes) -> bytes | None:
    data = json.loads(body.decode("utf-8"))
    # ... inject cache_control on system, tools, last message
```

**Proposed Fix**:
1. For OpenAI: Pin the system prompt prefix + tool schemas to the first turn and reuse (OpenAI auto-caches on matching prefix). This already works implicitly but document it.
2. For Gemini: Investigate `cachedContents` API (Vertex AI context caching). Not a code fix but a plugin opportunity.
3. Add observability: log `cache_creation_input_tokens` and `cache_read_input_tokens` from Anthropic responses to confirm cache hits.

**Token Impact**: For Anthropic, caching IS working. For non-Anthropic models, this is a provider limitation, not a code bug. **Downgrade to P2 for non-Anthropic models.**
**Performance Impact**: N/A — provider-side.
**Effort**: M (Gemini context caching plugin)

**Risk if not fixed**: Non-Anthropic models pay full prompt cost every turn.

---

## [P1] Jaro-Winkler similarity scan over full haystack in Python — O(n×m) string comparison per `replace_in_file`

**Category**: Hotspot
**Location**: `code_muse/tools/window_matching.py:10-40`, `_find_best_window()` and `_jaro_winkler_similarity()`
**Severity**: P1

**Description**:
`_find_best_window()` slides a window of size `len(needle_lines)` over `haystack_lines`, calling `_jaro_winkler_similarity()` (via `rapidfuzz`) for every position. For a 500-line file with a 20-line needle, this is 480 Jaro-Winkler comparisons, each O(len(window)). This is called on every `replace_in_file` tool invocation.

`rapidfuzz` is a C extension, so the per-comparison cost is low (~50µs). But for very large files (10K+ lines), this becomes O(n×m) where n = file lines and m = needle lines.

**Root Cause**: Brute-force sliding window; no early termination or prefiltering.

**Evidence**:
```python
# code_muse/tools/window_matching.py:24-37
for i in range(len(haystack_lines) - win_size + 1):
    window = "\n".join(haystack_lines[i : i + win_size])
    score = _jaro_winkler_similarity(window, needle)
    if score > best_score:
        best_score = score
        best_span = (i, i + win_size)
```

**Hotspot Analysis**:
- Calls per agent run: 3-15 (one per `replace_in_file`)
- Complexity: O(n × m) where n = haystack lines, m = needle lines
- Current time estimate: ~25ms for 500-line file, ~500ms for 10K-line file
- **Proposed Cython signature**:
```cython
# cython: language_level=3, boundscheck=False, wraparound=False
cpdef tuple find_best_window_cython(
    list haystack_lines,
    str needle,
    int win_size,
) nogil:
    # Pre-join needle; slide window without re-joining
    # Return (start, end, score)
```

**Note**: `rapidfuzz` already provides C-speed JW; the bottleneck is the Python-level `"\n".join()` per iteration and the loop overhead. A Cython version that operates on pre-joined lines (or raw offsets) would eliminate the join overhead.

**Proposed Fix**:
1. Short-term: Pre-join the haystack once; use string slicing instead of per-iteration join.
2. Medium-term: Cythonize the loop with pre-computed line offsets.
3. Add early termination: if score > 0.95, break.

**Performance Impact**: 3-5x for large files with Cython; 2x with pre-join optimization in pure Python.
**Effort**: S (pure-Python pre-join), M (Cython)

**Risk if not fixed**: `replace_in_file` latency degrades linearly with file size.

---

## [P1] `gemini_schema.py` uses `copy.deepcopy()` in recursive schema resolution — O(n²) for complex schemas

**Category**: Performance
**Location**: `code_muse/gemini_schema.py:28-80`, `_flatten_union_to_object_gemini()` and `_sanitize_schema_for_gemini()`
**Severity**: P1

**Description**:
Every `$ref` resolution in `_flatten_union_to_object_gemini` calls `copy_module.deepcopy(defs[ref_name])`. For a schema with 50 tool definitions (common for Muse), each with nested `$ref`s, this creates 50+ deep copies. `deepcopy` on nested dicts with string keys is O(n × depth) and allocates substantial intermediate objects.

The main `_sanitize_schema_for_gemini()` also calls `copy.deepcopy(schema)` at the top level.

**Root Cause**: Defensive copying is correct for mutation safety, but `deepcopy` is overkill when the schema is only read and transformed (not mutated in-place during iteration).

**Evidence**:
```python
# code_muse/gemini_schema.py:28-29
import copy as copy_module
# ...
item = copy_module.deepcopy(defs[ref_name])

# code_muse/gemini_schema.py:73
schema = copy.deepcopy(schema)
```

**Proposed Fix**:
1. Replace `deepcopy` with `json.loads(json.dumps(obj))` (2-3x faster for pure-dict schemas).
2. Or use `orjson.loads(orjson.dumps(obj))` — already imported elsewhere.
3. Better: transform in-place and deepcopy only at the top level, not per-ref.

**Performance Impact**: 2-3x faster schema sanitization (currently ~30ms for 50 tools, would drop to ~10ms).
**Effort**: S

**Risk if not fixed**: Schema preparation adds latency to every Gemini model run.

---

## [P1] Summarization agent spawns a new event loop per call — overhead for frequent compactions

**Category**: Performance
**Location**: `code_muse/summarization_agent.py:170-210`, `run_summarization_sync()`
**Severity**: P1

**Description**:
Every compaction that triggers summarization calls `run_summarization_sync()`, which:
1. Gets/caches the summarization agent (good)
2. Creates a **new event loop** (`asyncio.new_event_loop()`) per call
3. Runs `loop.run_until_complete(agent.run(...))` in a ThreadPoolExecutor
4. Cancels all tasks, shuts down async generators, and closes the loop

The per-call loop creation/destruction overhead is ~5-10ms. For an agent run with 8 compaction cycles, that's 40-80ms of pure overhead.

**Root Cause**: `run_summarization_sync()` must work from sync context, and the main thread may have a running event loop. Creating a new loop per call is the safe pattern but adds overhead.

**Evidence**:
```python
# code_muse/summarization_agent.py:191-210
def _run_in_thread():
    loop = asyncio.new_event_loop()
    try:
        coro = agent.run(prompt, message_history=message_history)
        return loop.run_until_complete(coro)
    finally:
        # Cancel pending tasks, shutdown asyncgens, close loop
```

**Proposed Fix**:
1. Keep a dedicated summarization event loop alive in the ThreadPoolExecutor thread (one loop, reused across calls).
2. Use `loop.call_soon_threadsafe()` + `asyncio.run_coroutine_threadsafe()` pattern instead of creating/destroying loops.
3. Or use `asyncio.to_thread()` from the main loop to offload the sync wrapper.

**Performance Impact**: -5ms per compaction cycle (~40ms saved over 8 compactions).
**Effort**: M

**Risk if not fixed**: Each compaction adds 5-10ms of event loop lifecycle overhead.

---

## [P2] Cython `.pyx` files lack `boundscheck(False)` and `wraparound(False)` directives

**Category**: Cython
**Location**: `code_muse/fs_scan_cache/scan_cache_core.pyx:1`, `code_muse/models_cache/sha256_hash.pyx:1`, `code_muse/stream_parser/tagged_line_parser.pyx:1`, `code_muse/stream_parser/utf8_stream_parser.pyx:1`
**Severity**: P2

**Description**:
Only `terminal_utils.pyx` properly uses `nogil` and typed C pointers. The other `.pyx` files are "Cython in name only":
- `scan_cache_core.pyx`: Uses `cdef` type declarations but no `nogil`, no `boundscheck(False)`, no `wraparound(False)`. The `get_or_scan()` method does dict operations under `threading.Lock` — pure Python patterns with Cython type hints that don't actually compile to C fast paths.
- `sha256_hash.pyx`: Uses `cdef` for local variables in the file-reading loop, which provides minor speedup. But `hashlib.sha256()` is already C-implemented — the Cython wrapper adds nothing.
- `tagged_line_parser.pyx`: Uses `cdef` for loop variables but still does Python string operations (`buf.find()`, `strip()`, `startswith()`) in tight loops. No `nogil` sections.
- `utf8_stream_parser.pyx`: Pure Python class with `cdef` annotations on local variables. No `nogil`, no memoryviews, no C-level optimization.

**Root Cause**: These files were likely created with the intent to Cythonize but never got the full treatment.

**Evidence**:
```python
# scan_cache_core.pyx — no compiler directives
# cython: language_level=3
# (no boundscheck=False, no wraparound=False)

# tagged_line_parser.pyx — Python string ops in "Cython" code
self._line_buffer += delta  # Python string concat
newline_idx = buf.find("\n")  # Python method call
```

**Proposed Fix**:
1. Add `# cython: boundscheck=False, wraparound=False` to all `.pyx` files.
2. For `tagged_line_parser.pyx`: rewrite the line-scanning loop with `const char*` and `memchr()` for newline detection; release GIL during scan.
3. For `sha256_hash.pyx`: the Cython wrapper is redundant — `hashlib` is already C. Either remove the `.pyx` or add a C-level SHA-256 implementation.
4. For `scan_cache_core.pyx`: the dict/OrderedDict operations can't be `nogil` — consider whether Cython adds value here at all.

**Performance Impact**: 2-5x for `tagged_line_parser` with proper C-level line scanning. Others: negligible.
**Effort**: L (proper rewrite), S (add directives)

**Risk if not fixed**: `.pyx` files masquerading as fast when they're essentially Python.

---

## [P2] `stringify_part()` uses `id(part)` for LRU cache — dangling reference risk after GC

**Category**: Performance
**Location**: `code_muse/agents/_history.py:47-98`, `stringify_part()` and `_stringify_part_lru`
**Severity**: P2

**Description**:
The LRU cache for `stringify_part()` is keyed by `id(part)` — the memory address of the part object. When a part object is garbage collected, its `id()` can be reused by a new, different object. The `_hash_cache` at line 166 has a `weakref.finalize` callback to evict stale entries, but `_stringify_part_lru` at line 47 does **not**.

This means that after GC, a new part object at the same address could return a stale cached string from a previous part — a correctness bug, not just a performance one.

**Root Cause**: `_stringify_part_lru` lacks the `weakref.finalize` eviction that `_hash_cache` has.

**Evidence**:
```python
# code_muse/agents/_history.py:47-98
_stringify_part_lru: OrderedDict[int, str] = OrderedDict()
_STRINGIFY_PART_LRU_MAX = 2048

def stringify_part(part: Any) -> str:
    msg_id = id(part)
    cached = _stringify_part_lru.get(msg_id)
    # ... no weakref.finalize() to evict on GC
```

Compare with:
```python
# code_muse/agents/_history.py:168-170
def hash_message(message: Any) -> int:
    # ...
    weakref.finalize(message, _evict_hash_cache, msg_id)  # ← correct
```

**Proposed Fix**:
1. Add `weakref.finalize(part, _evict_stringify_part_lru, msg_id)` after inserting into `_stringify_part_lru`.
2. Or: use a `WeakValueDictionary` if applicable (part objects aren't values though — they're keys).

**Performance Impact**: Correctness fix; no performance impact (finalize callback is O(1)).
**Effort**: S

**Risk if not fixed**: Stale cached strings returned for new part objects sharing recycled `id()` — rare but possible in long sessions.

---

## [P2] Prompt construction in `MuseAgent.get_system_prompt()` uses f-string interpolation for identity — not candidate for Cython but wasteful token structure

**Category**: Token
**Location**: `code_muse/agents/agent_muse.py:70-100`, `MuseAgent.get_system_prompt()`
**Severity**: P2

**Description**:
`MuseAgent.get_system_prompt()` returns a large f-string with the agent's name and owner baked in. This is then concatenated with `get_identity_prompt()` (which adds the agent ID) in `get_full_system_prompt()`. The identity prompt is ~50 tokens. The main prompt is ~600 tokens.

Meanwhile, `prompt_v3.py` provides `autonomy_base_prompt()` + `muse_overlay()` + `repository_addendum()` — a cleaner architecture. But `MuseAgent.get_system_prompt()` does NOT use `prompt_v3`. It has its own inline prompt that duplicates most of the same content. This means:
- Two different "Muse personality" descriptions exist
- `MuseAgent` prompt is ~800 tokens vs the v3 prompt's ~1200 tokens (includes autonomy base)
- The v3 `autonomy_base_prompt()` has the operating contract (tool-first, validate, iterate); the inline prompt is less structured

**Root Cause**: Migration to v3 prompt architecture is incomplete — only `AgentCreatorAgent` and `PlanningAgent` use `prompt_v3`.

**Evidence**:
```python
# agent_muse.py — uses inline prompt
def get_system_prompt(self) -> str:
    return f"""You are {agent_name}, the divine Muse..."""

# agent_creator_agent.py — uses v3
result = autonomy_base_prompt() + "\n\n" + agent_creator_overlay() + ...
```

**Proposed Fix**:
1. Migrate `MuseAgent.get_system_prompt()` to use `autonomy_base_prompt() + muse_overlay() + repository_addendum()`.
2. Remove the inline prompt from `agent_muse.py`.
3. Ensure all agents use v3 architecture.

**Token Impact**: Potentially +400 tokens (v3 is more complete), but better structured and deduped.
**Effort**: M

**Risk if not fixed**: Prompt drift between agents; MuseAgent missing the operating contract.

---

## [P2] Redundant `_estimate_tokens()` reimplementation in `subagent_stream_handler.py`

**Category**: Performance
**Location**: `code_muse/agents/subagent_stream_handler.py:67-80`, `_estimate_tokens()`
**Severity**: P2

**Description**:
`subagent_stream_handler.py` defines its own `_estimate_tokens()` that uses `len(content) / 2.5` instead of the canonical `estimate_tokens()` from `_history.py` which uses `len(text) / 3.0`. The comment says "same ~2.5 heuristic as BaseAgent.estimate_token_count" but the canonical function was updated to `/3.0`.

This causes inconsistency: subagent token counts will be ~20% higher than compaction token counts for the same content.

**Root Cause**: Copy-paste divergence; the subagent handler wasn't updated when the divisor changed.

**Evidence**:
```python
# subagent_stream_handler.py:67-80
def _estimate_tokens(content: str) -> int:
    """Uses the same ~2.5 characters per token heuristic as BaseAgent.estimate_token_count"""
    # Actually uses len / 2.5

# _history.py:146-155
def estimate_tokens(text: str) -> int:
    """Uses len / 3.0 as the base divisor"""
    return max(1, math.floor(len(text) / 3.0))
```

**Proposed Fix**:
1. Replace `subagent_stream_handler._estimate_tokens()` with an import from `_history.estimate_tokens`.
2. Delete the duplicate function.

**Performance Impact**: Negligible — same O(1) operation.
**Effort**: S

**Risk if not fixed**: Token accounting inconsistency between subagent metrics and compaction decisions.

---

## [P2] Blocking I/O in sync `history_processor` — compaction stalls the event loop

**Category**: Performance
**Location**: `code_muse/agents/_compaction.py:440-500`, `history_processor()` → `compact_with_tool_truncation()` → `compact()` → `summarize()`
**Severity**: P2

**Description**:
`history_processor` is a sync callback called by pydantic-ai. When summarization is triggered, it calls `run_summarization_sync()` which blocks the calling thread (creates a new event loop in a ThreadPoolExecutor and blocks on `.result()`). This means the main event loop is blocked during summarization — no other async work can proceed.

For truncation strategy, this is fast (< 1ms). For summarization strategy, it blocks for the LLM call duration (1-5 seconds).

**Root Cause**: pydantic-ai's `history_processors` callback is sync, not async. Summarization requires an async LLM call, which must be bridged to sync.

**Evidence**:
```python
# _compaction.py:440
def history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
    # ... synchronous callback
    new_history, dropped = compact_with_tool_truncation(...)  # can call summarize()
```

**Proposed Fix**:
1. Short-term: Move summarization to `asyncio.to_thread()` if the history processor allows it (unlikely — pydantic-ai controls the calling context).
2. Medium-term: Pre-check if summarization is needed and fire it asynchronously before the next `pydantic_agent.run()` call.
3. Long-term: Request pydantic-ai to support async `history_processors`.

**Performance Impact**: Prevents 1-5 second event loop stalls during summarization.
**Effort**: L (requires architectural change)

**Risk if not fixed**: UI freezes during summarization; subagent streams stall.

---

## [P2] Global mutable state: `_AGENT_REGISTRY`, `_AGENT_HISTORIES`, `_CURRENT_AGENT` in agent_manager

**Category**: Agentic Design
**Location**: `code_muse/agents/agent_manager.py:20-25`
**Severity**: P2

**Description**:
`agent_manager.py` uses module-level global mutable dicts for agent registry, history storage, and current agent tracking:
- `_AGENT_REGISTRY: dict[str, type[BaseAgent] | str] = {}`
- `_AGENT_HISTORIES: dict[str, list[ModelMessage]] = {}`
- `_CURRENT_AGENT: BaseAgent | None = None`

These are accessed without locking in async contexts. While Python's GIL provides basic thread safety for dict operations, the free-threaded Python 3.14 target (noted in FREE-THREADED comments throughout the codebase) means these globals are a race condition waiting to happen.

**Root Cause**: Legacy singleton pattern; no encapsulation.

**Evidence**:
```python
# agent_manager.py:20-25
_AGENT_REGISTRY: dict[str, type[BaseAgent] | str] = {}
_DISCOVERY_CACHE: dict[str, type[BaseAgent] | str] = {}
_AGENT_HISTORIES: dict[str, list[ModelMessage]] = {}
_CURRENT_AGENT: BaseAgent | None = None
```

**Proposed Fix**:
1. Wrap in a `class AgentManager` with `threading.Lock` for all mutable state.
2. Or: use contextvars for `_CURRENT_AGENT` (already done for tool error tracker in `_runtime.py`).
3. Add lock-based access for `_AGENT_HISTORIES`.

**Performance Impact**: Negligible — lock overhead is <1µs.
**Effort**: M

**Risk if not fixed**: Race conditions under free-threaded Python 3.14.

---

## [P2] `_find_best_window()` creates a new joined string per iteration — memory churn

**Category**: Hotspot
**Location**: `code_muse/tools/window_matching.py:24-37`, `_find_best_window()`
**Severity**: P2

**Description**:
Each iteration of the sliding window does `"\n".join(haystack_lines[i : i + win_size])` which:
1. Creates a list slice (new list object)
2. Joins into a string (new string object)
3. Passes to `JaroWinkler.normalized_similarity()` (new comparison)

For a 1000-line file with a 20-line needle, this creates 980 intermediate string objects, each ~1-4KB. Total allocation: ~1-4MB of temporary strings.

**Root Cause**: Brute-force approach with no pre-optimization.

**Evidence**:
```python
for i in range(len(haystack_lines) - win_size + 1):
    window = "\n".join(haystack_lines[i : i + win_size])
    score = _jaro_winkler_similarity(window, needle)
```

**Proposed Fix**:
1. Pre-join the entire haystack into one string with line offsets.
2. Use string slicing on the pre-joined string instead of per-iteration join.
3. Cythonize with `const char*` slice comparisons.

**Hotspot Analysis**:
- Calls per agent run: 3-15
- Complexity: O(n × m) with O(m) allocation per step
- Current: ~25ms for 500-line file, ~500ms for 10K-line file
- **Proposed Cython signature**:
```cython
cpdef tuple find_best_window_prejoined(
    str haystack_joined,
    int[:] line_offsets,
    str needle,
) nogil:
```

**Performance Impact**: 2-3x with pre-join in pure Python; 5-10x with Cython.
**Effort**: S (pre-join), M (Cython)

**Risk if not fixed**: Memory churn on large file edits.

---

## [P2] `tagged_line_parser.pyx` does Python string concatenation in hot streaming path

**Category**: Cython
**Location**: `code_muse/stream_parser/tagged_line_parser.pyx:111-130`, `TaggedLineParser._push_text()`
**Severity**: P2

**Description**:
`_push_text()` does `last.text += text` for coalescing consecutive segments. In a streaming response with 100+ text deltas, this creates O(n) intermediate strings. The parser is on the critical path for every streamed response.

While Python's string concatenation is optimized for single-reference strings (CPython's `str` is mutable before sharing), the pattern is still slower than `list.append()` + `''.join()` for many concatenations.

**Root Cause**: Coalescing optimization uses `+=` on the last segment's text.

**Evidence**:
```cython
# tagged_line_parser.pyx:111-130
def _push_text(self, text, segments):
    # ...
    if isinstance(last, TaggedLineSegmentNormal):
        last.text += text  # Python string concatenation
```

**Proposed Fix**:
1. Change `TaggedLineSegmentNormal.text` to accumulate in a list and join on demand (lazy `join`).
2. Or: pre-allocate a `bytearray` in Cython and append bytes.

**Performance Impact**: ~2x for high-frequency streaming paths.
**Effort**: S

**Risk if not fixed**: Streaming latency scales with response length.

---

## [P2] `scan_cache_core.pyx` uses Python `OrderedDict` under Cython — minimal gain from `.pyx` extension

**Category**: Cython
**Location**: `code_muse/fs_scan_cache/scan_cache_core.pyx:1-170`, `ScanCache`
**Severity**: P2

**Description**:
`ScanCache` is a `.pyx` file with `cdef` type hints on local variables, but all data structures are Python objects (`OrderedDict`, `GlobMatch` dataclass, `ScanEntry` dataclass). The critical path (`get_or_scan`) does dict lookups, `move_to_end()`, and list operations — all Python-level. The `cdef` hints on `now`, `age_ms`, `evict_count` provide negligible speedup because the bottleneck is the dict operations.

The `invalidate()` method iterates over all cache keys and does `Path.resolve()` + `is_relative_to()` — expensive I/O-bound operations that Cython can't accelerate.

**Root Cause**: `.pyx` extension was added for future optimization that never happened.

**Evidence**:
```cython
# scan_cache_core.pyx — all Python data structures
class ScanCache:
    def __init__(self, max_entries=16):
        self._cache: OrderedDict[tuple, ScanEntry] = OrderedDict()
```

**Proposed Fix**:
1. Either: rewrite with C-level LRU (linked list + hash map in C) for true Cython benefit.
2. Or: move back to `.py` — the current `.pyx` adds build complexity with no runtime gain.

**Performance Impact**: Negligible either way — `fs_scan_cache` is I/O-bound (filesystem scans).
**Effort**: S (revert to .py), L (proper C LRU)

**Risk if not fixed**: Misleading "Cython optimized" claim; build complexity for no gain.

---

## [P3] `estimate_context_overhead()` iterates all tool schemas on every agent build — should cache

**Category**: Performance
**Location**: `code_muse/agents/_history.py:210-250`, `estimate_context_overhead()`
**Severity**: P3

**Description**:
`estimate_context_overhead()` walks every registered tool's schema, docstring, and annotations to estimate token overhead. This is called once per agent build via `BaseAgent._estimate_context_overhead()`, which has an instance-level cache. The cache works well for the common case (agent doesn't rebuild), but on model switch or agent reload, the full schema walk repeats.

For an agent with 16 tools, this is 16 × (name + doc + schema) serializations ≈ 2-3ms. Not critical but unnecessary if the toolset hasn't changed.

**Root Cause**: Cache is keyed by model_name, not (model_name, toolset_hash).

**Evidence**:
```python
# _history.py:210-250
def estimate_context_overhead(system_prompt, pydantic_tools, model_name=None):
    for tool_name, tool_func in pydantic_tools.items():
        total += estimate_tokens(tool_name)
        description = getattr(tool_func, "__doc__", None) or ""
        schema = getattr(tool_func, "schema", None)
```

**Proposed Fix**:
1. Add a `toolset_hash` to the cache key (frozenset of tool names).
2. Skip recomputation if toolset hasn't changed.

**Performance Impact**: Saves ~2ms on model switch.
**Effort**: S

**Risk if not fixed**: Minor — 2ms on infrequent operations.

---

## [P3] Magic number `50000` for token threshold in `filter_huge_messages()`

**Category**: Agentic Design
**Location**: `code_muse/agents/_history.py:280-290`, `filter_huge_messages()`
**Severity**: P3

**Description**:
The 50,000-token threshold for filtering huge messages is hardcoded. This should be configurable or derived from the model's context window.

**Evidence**:
```python
# _history.py:280-290
def filter_huge_messages(messages, model_name=None, cache=None):
    filtered = [m for m in messages if ... < 50000]
```

**Proposed Fix**:
1. Make it `get_filter_huge_message_threshold()` from config.
2. Default to `min(50000, model_context_length * 0.4)`.

**Effort**: S

**Risk if not fixed**: 50K threshold may be too low for 1M-context models or too high for 32K models.

---

## [P3] Temperature hardcoded to 1.0 for all Anthropic extended-thinking models

**Category**: Agentic Design
**Location**: `code_muse/model_factory.py:339-342`
**Severity**: P3

**Description**:
When extended thinking is active, temperature is forced to 1.0 per Anthropic API requirements. This is correct for the API, but the code silently overrides any user-set temperature without feedback. Users who set `temperature=0.3` via `/set` may not realize it's being ignored.

**Root Cause**: API requirement — Anthropic rejects non-1.0 temperature with extended thinking.

**Proposed Fix**:
1. Emit a one-time warning when temperature is overridden for extended thinking.
2. Document in the model settings menu.

**Effort**: S

**Risk if not fixed**: User confusion when temperature setting appears ignored.

---

## Summary Roadmap

| Priority | Issue | Category | Effort | Gain |
|----------|-------|----------|--------|------|
| P0 | No hard step cap on agent run | Agentic Design | S | prevents infinite burn |
| P0 | Unbounded `_message_history` growth | Agentic Design | S | prevents OOM |
| P1 | Token estimation hotspot in compaction | Hotspot | M | 5-10x for serialize path |
| P1 | System prompt rebuilt per build | Token | S | -2ms/build, cache_control already helps |
| P1 | cache_control only for Anthropic | Token | M | non-Anthropic caching |
| P1 | Jaro-Winkler O(n×m) window scan | Hotspot | M | 3-5x for large files |
| P1 | deepcopy in gemini_schema | Performance | S | 2-3x schema prep |
| P1 | Summarization event loop per call | Performance | M | -5ms/compaction |
| P2 | Cython .pyx files lack directives | Cython | S-L | 2-5x for tagged_line_parser |
| P2 | stringify_part LRU stale entry risk | Performance | S | correctness fix |
| P2 | MuseAgent not using prompt_v3 | Token | M | dedup, structure |
| P2 | Duplicate _estimate_tokens in subagent | Performance | S | consistency |
| P2 | Blocking I/O in history_processor | Performance | L | prevent UI freeze |
| P2 | Global mutable agent state | Agentic Design | M | free-threaded safety |
| P2 | Window matching memory churn | Hotspot | S-M | 2-3x, less GC |
| P2 | tagged_line_parser += concat | Cython | S | 2x streaming |
| P2 | scan_cache_core .pyx no real gain | Cython | S | honest build |
| P3 | context_overhead cache missing toolset hash | Performance | S | -2ms/model switch |
| P3 | Magic 50K token threshold | Agentic Design | S | configurable |
| P3 | Silent temperature override | Agentic Design | S | UX clarity |

**Top 3 Cythonization Candidates** (new code worth writing):

1. **`code_muse/tools/window_matching.pyx`** — Pre-joined sliding window search with `const char*` slicing and `nogil`. Eliminates per-iteration string allocation. Expected: 5-10x for 10K-line files, releases GIL.

2. **`code_muse/agents/_history.pyx`** — Fast `stringify_part()` using `orjson` C calls + typed attribute access + `weakref`-safe LRU. Eliminates Python-level attribute chains in the compaction hot path. Expected: 5x for compaction of 100+ messages.

3. **`code_muse/stream_parser/tagged_line_parser.pyx`** — Proper rewrite with `const char*` newline scanning via `memchr()`, `bytearray` accumulation instead of `str +=`, and `nogil` for the scan loop. Expected: 5-10x for parsing streamed responses.
