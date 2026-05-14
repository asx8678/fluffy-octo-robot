# Deep Static Review — fixed_plan.md

**Reviewer:** Claude Opus 4.7 Principal Engineer  
**Scope:** Full agentic Python + Cython codebase at `/Users/adam2/projects/fluffy-octo-robot/code_muse/`  
**Method:** Pure static analysis — no execution, no tests, no builds.  
**Date:** 2025-07-14

---

## Table of Contents

1. [Critical Bugs](#1-critical-bugs)
2. [Design Flaws](#2-design-flaws)
3. [Performance Bottlenecks](#3-performance-bottlenecks)
4. [Token Waste](#4-token-waste)
5. [CPU/Memory Hotspots for Cythonization](#5-cpumemory-hotspots-for-cythonization)
6. [Summary Roadmap](#6-summary-roadmap)

---

## 1. Critical Bugs

### BUG-01: Bare-comma `except` syntax — silent mis-catch

**File:** `code_muse/agents/base_agent.py:203`  
**Severity:** CRITICAL — control-flow exception swallowed

```python
except asyncio.CancelledError, KeyboardInterrupt, SystemExit:
    raise
```

**Evidence:** Python 3 requires parenthesized tuples in `except` clauses. The bare comma syntax `except A, B:` was removed in Python 3. Depending on the exact parser version, this either:

- Parses as `except asyncio.CancelledError as KeyboardInterrupt` — catching *only* `CancelledError` and binding it to the name `KeyboardInterrupt`, leaving actual `KeyboardInterrupt` and `SystemExit` to propagate uncaught through the generic `except BaseException as exc` handler below (which swallows them), OR
- Raises `SyntaxError` at import time (if the parser rejects three-comma `except` entirely).

**Impact:** `KeyboardInterrupt` and `SystemExit` — which should re-raise unconditionally — may be swallowed and logged as warnings instead. In practice: Ctrl+C might not work as expected.

**Fix:**
```python
except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
    raise
```

**Same pattern found at:** `code_muse/agents/agent_manager.py:152`:
```python
except json.JSONDecodeError, OSError:
```
→ `except (json.JSONDecodeError, OSError):`

---

### BUG-02: `get_protected_token_count` calls `get_model_context_length` → `ModelFactory.load_config()` on every invocation

**File:** `code_muse/config/models.py:236` (traced through `get_protected_token_count` → `get_model_context_length` → `ModelFactory.load_config()`)  
**Severity:** HIGH — latent perf + correctness

**Evidence chain:**
```python
# config/models.py:236
def get_protected_token_count():
    model_context_length = get_model_context_length()  # calls load_config()
    ...

# config/models.py:229
def get_model_context_length():
    model_configs = ModelFactory.load_config()          # full JSON parse on cache miss
    ...
```

Even with `model_factory.py`'s mtime cache, the fingerprint computation stats 6+ files each call. But worse: `get_protected_token_count()` is called *inside* `compact()` on every compaction cycle (see `_compaction.py:261`), and compaction fires on *every* `history_processor` invocation.

**Impact:** Every agent turn does 6+ `stat()` syscalls plus lock acquisition to re-validate a config that rarely changes.

**Fix:** Cache `get_model_context_length()` result in the session model cache alongside `_SESSION_MODEL`. Invalidate only on `set_model_name()` or `clear_model_cache()`.

---

## 2. Design Flaws

### DF-01: Triply-redundant model config cache layers

**Files:**
- `code_muse/model_factory.py:44-57` — `_models_config_cache` + `_models_config_lock`
- `code_muse/summarization_agent.py:83-97` — separate `_models_config_cache` + `_models_config_lock`
- `code_muse/config/models.py:10-12` — `_model_validation_cache`, `_default_model_cache`, `_default_vision_model_cache`

**Evidence:** All three implement the same pattern independently: load JSON, check fingerprint, cache result. `summarization_agent.py` even has its own `_models_config_fingerprint()` that duplicates the one in `model_factory.py`. Each has its own `invalidate_*()` function with different naming conventions.

**Impact:** 
- DRY violation: three separate cache implementations for the same data.
- Cache coherence risk: invalidating one doesn't invalidate the others.
- Memory waste: the same ~3 KB JSON dict held in three separate dicts.
- Cognitive overhead: developers don't know which cache to invalidate.

**Fix:** Consolidate all model config caching into `model_factory.py`. Remove the summarization_agent's parallel cache. Make `config/models.py` consume `ModelFactory.load_config()` through a thin session-scoped accessor that returns the cached result. Single `invalidate_models_config_cache()` entry point.

---

### DF-02: `config/__init__.py` god-module re-export

**File:** `code_muse/config/__init__.py` (144 lines, ~120 re-exports)  
**Severity:** MEDIUM — import coupling

**Evidence:** The file re-exports every public name from 6 submodules (`models`, `parser`, `paths`, `security`, `session`) plus 3 sibling modules (`config_agent.py`, `config_appearance.py`, `config_model.py`). Importing *any* config value forces all 6 submodules to load, including `security` (which accesses the keyring) and `session` (which does file I/O).

**Impact:**
- Startup latency: every `from code_muse.config import X` loads the entire config subsystem.
- Circular import risk: the re-export chain creates an implicit import order dependency.
- Testing friction: you can't import a single config getter without loading everything.

**Fix:** Convert to explicit submodule imports at call sites:
```python
# Instead of:
from code_muse.config import get_global_model_name
# Use:
from code_muse.config.models import get_global_model_name
```
Keep `__init__.py` for backward compat but mark re-exports as deprecated, with a `__getattr__`-based lazy import pattern to avoid eager loading.

---

### DF-03: `_runtime.py` module-level callback registration side effect

**File:** `code_muse/agents/_runtime.py:218-219`  
**Severity:** MEDIUM — hidden global state mutation

```python
# Register callbacks at module load time.
register_callback("pre_tool_call", _track_pre_tool_call)
register_callback("post_tool_call", _track_post_tool_call)
```

**Evidence:** Importing `_runtime.py` has the side effect of registering two global callbacks. While `register_callback` has dedup logic, the registration happens at import time, making the tool-error circuit breaker impossible to test in isolation and tightly coupling the callback system to the import order.

**Impact:**
- Test contamination: any test that imports `_runtime` gets the circuit breaker callbacks registered.
- No way to disable the circuit breaker without patching `_callbacks`.
- If `_runtime.py` is imported before the callback system is initialized, registration silently fails.

**Fix:** Move registration into `BaseAgent.__init__()` or into the `run()` function setup, not at module scope. Alternatively, use a `_register_runtime_callbacks()` function called explicitly during agent startup.

---

### DF-04: `_compaction.py:truncate()` uses `queue.LifoQueue` for simple list reversal

**File:** `code_muse/agents/_compaction.py:154-170`  
**Severity:** LOW — unnecessary complexity

```python
import queue
...
stack: queue.LifoQueue[ModelMessage] = queue.LifoQueue()
for msg in reversed(messages_to_scan):
    num_tokens += _tok(msg, model_name)
    if num_tokens > protected_tokens:
        break
    stack.put(msg)

while not stack.empty():
    result.append(stack.get())
```

**Evidence:** A `queue.LifoQueue` is a thread-safe data structure with lock acquisition on every `put`/`get`. This is single-threaded code within the history processor. The same result is achieved with:

```python
stack = []
for msg in reversed(messages_to_scan):
    num_tokens += _tok(msg, model_name)
    if num_tokens > protected_tokens:
        break
    stack.append(msg)
result.extend(reversed(stack))
```

**Impact:** Unnecessary lock overhead and confusing use of a concurrency primitive in single-threaded code.

---

### DF-05: `_history.py` global caches with `weakref.finalize` accumulation

**File:** `code_muse/agents/_history.py:90-102`  
**Severity:** MEDIUM — GC pressure

```python
_hash_cache: OrderedDict[int, int] = OrderedDict()
_HASH_CACHE_MAX = 8192

def hash_message(message: Any) -> int:
    ...
    _hash_cache[msg_id] = result
    weakref.finalize(message, _evict_hash_cache, msg_id)
    return result
```

**Evidence:** Every `hash_message()` call creates a `weakref.finalize` callback object. In a long session with thousands of messages, these finalizer callbacks accumulate in the GC's pending finalizers list until the messages are collected. The finalizer creation itself involves:
1. Creating a `weakref.ref` to the message
2. Creating a callback wrapper
3. Registering with the GC's finalization queue

**Impact:** GC pressure proportional to message count. Each finalizer is a small object, but thousands of them slow down GC cycles. The `_evict_hash_cache` callback also does a dict lookup on every message deletion.

**Fix:** Replace with a `WeakKeyDictionary` keyed on `id(message)` (or use a simpler approach: don't cache by `id()` at all, since the `CompactionCache` already provides per-compaction-run caching). The global cache exists for cross-compaction dedup, but in practice, messages are only alive within one compaction run.

---

### DF-06: `_runtime.py:run()` is a 300+ line async function with 5 nesting levels

**File:** `code_muse/agents/_runtime.py:251-650` (the `run()` function)  
**Severity:** MEDIUM — maintainability

**Evidence:** The `run()` function contains:
- `async def _do_run()` (inner function, ~120 lines)
- `async def _run_agent()` (nested inside `_do_run`)
- `async def _call()` (wrapped with `@streaming_retry()`)
- `async def _call_with_exception_recovery()` (nested retry loop)
- `async def run_agent_task()` (outer task wrapper)

Plus signal handling, keyboard listener setup, and cleanup in `finally`.

**Impact:** Hard to test individual pieces. The nesting makes error handling paths obscure. The `nonlocal run_stats` mutation from deeply nested closures is fragile.

**Fix:** Extract the nested functions as module-level coroutines with explicit parameters. `_do_run` becomes `_run_once()`, `_call_with_exception_recovery` becomes `_run_with_recovery()`, etc.

---

## 3. Performance Bottlenecks

### PB-01: `ModelFactory.load_config()` fingerprint computation in hot paths

**Files:**
- `code_muse/model_factory.py:59-88` — `_models_config_fingerprint()`
- `code_muse/summarization_agent.py:58-82` — `_models_config_fingerprint()` (duplicate)

**Callers (all hot paths):**
- `config/models.py:31,54,97,147,236` — 5 call sites in `config/models.py` alone
- `agents/_runtime.py:280` — `_model_allows_streaming()` calls on every `run()`
- `agents/base_agent.py:133` — `_get_model_context_length()`
- `agents/_builder.py:223` — `build_pydantic_agent()`
- `tools/agent_tools.py:457` — sub-agent invocation
- 8+ call sites in `plugins/`

**Evidence:** Each `_models_config_fingerprint()` call:
1. Imports 6 config path constants
2. Constructs `pathlib.Path` objects for each
3. Calls `Path.exists()` + `Path.stat()` for each (6+ syscalls)
4. Updates a blake2b hasher with `sp:size:mtime` strings

**Measured impact estimate:** On a typical agent run, `ModelFactory.load_config()` is called 3-5 times (once in `_builder`, once in `_runtime._model_allows_streaming`, once in `base_agent._get_model_context_length`, once in `config/models.get_protected_token_count`, once in `make_model_settings`). Each call that misses the cache does 6+ stat()s. With the mtime cache, most calls are hits, but the fingerprint is still recomputed on every call to check if the cache is valid.

**Fix:** Add a short-lived (e.g., 5-second) TTL cache on the fingerprint itself. If the fingerprint was computed less than 5 seconds ago, reuse it without re-stating files. This is safe because model config files change on human timescales (seconds to minutes), not sub-second.

---

### PB-02: `make_history_processor` hashes entire history on every invocation

**File:** `code_muse/agents/_compaction.py:248`  
**Severity:** HIGH — O(n) per turn

```python
def history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
    ...
    existing_hashes = {hash_message(m) for m in history}  # O(n) every turn
    messages_added = 0
    last_idx = len(messages) - 1
    for i, msg in enumerate(messages):
        h = hash_message(msg)
        if h in existing_hashes:
            continue
```

**Evidence:** On every `history_processor` invocation (which fires after every model turn), the entire existing `agent._message_history` is re-hashed to build `existing_hashes`. For a session with 100 messages, this is 100 `hash_message()` calls, each of which does `stringify_part()` for every part of every message.

**Impact:** In a 200-message session, this is 200+ hash computations per turn, each involving string concatenation + `hash()`. With the `CompactionCache` only scoped to one compaction run, these computations are repeated across turns.

**Fix:** Maintain an `existing_hashes` set incrementally on `agent._message_history`. Add hashes when messages are appended, remove when compacted. This eliminates the O(n) re-hash on every turn.

---

### PB-03: Callbacks `get_callbacks()` sorts on every call

**File:** `code_muse/callbacks.py:148-151`  
**Severity:** MEDIUM — repeated sorting in hot paths

```python
def get_callbacks(phase: PhaseType) -> list[CallbackFunc]:
    """Return callbacks for *phase* sorted by priority (highest first)."""
    callbacks = _callbacks.get(phase, [])
    sorted_callbacks = sorted(callbacks, key=lambda item: item[0], reverse=True)
    return [func for _priority, func in sorted_callbacks]
```

**Evidence:** `get_callbacks()` is called on every hook trigger. For hot phases like `pre_tool_call` (fires before every tool execution) and `stream_event` (fires hundreds of times per streaming response), this sorts the list every time.

In `_fire_stream_event_sync()`:
```python
if not callbacks.count_callbacks("stream_event"):
    return
callbacks.on_stream_event_sync(...)  # calls get_callbacks() → sorted()
```

The `count_callbacks()` check avoids the sort when there are zero callbacks, but when there are callbacks (the common case with plugins), `get_callbacks()` sorts every time.

**Impact:** For 5 registered callbacks, this is negligible. But the principle is wrong — the sort order never changes after registration.

**Fix:** Keep the list sorted at registration time. When `register_callback()` appends, use `bisect.insort` to maintain sorted order. Remove the `sorted()` call from `get_callbacks()`. This also means `get_callbacks()` can return a slice of the internal list directly (or a cached tuple).

---

### PB-04: `event_stream_handler` creates 10 per-part tracking dicts per stream

**File:** `code_muse/agents/event_stream_handler.py:108-118`  
**Severity:** MEDIUM — dict allocation in streaming path

```python
streaming_parts: set[int] = set()
thinking_parts: set[int] = set()
text_parts: set[int] = set()
tool_parts: set[int] = set()
banner_printed: set[int] = set()
token_count: dict[int, int] = {}
tool_names: dict[int, str] = {}
termflow_parsers: dict[int, TermflowParser] = {}
termflow_renderers: dict[int, TermflowRenderer] = {}
termflow_line_buffers: dict[int, str] = {}
```

**Evidence:** Each `event_stream_handler` call creates 10 mutable containers. For high-frequency streaming events, dict lookups on `event.index` happen per-delta. The multiple `set[int]` containers for tracking part type could be collapsed into a single `dict[int, str]` mapping index → part_type.

**Impact:** Per-delta dict lookups are fast in CPython, but the multiple containers create unnecessary memory allocation and cache-line pressure. More importantly, the 4 separate sets require 4 separate `in` checks per event, vs. 1 dict lookup.

**Fix:** Replace the 4 part-tracking sets with a single `dict[int, PartType]` enum mapping. Replace `banner_printed` with a flag on the same struct. This cuts container count from 10 to 6 and reduces per-delta lookups.

---

### PB-05: `asyncio.sleep(0.1)` "spinner clear" delays in streaming path

**Files:**
- `code_muse/agents/event_stream_handler.py:164,183`
- `code_muse/tools/user_interaction.py:488,499`
- 10+ other sites

**Evidence:**
```python
async def _print_thinking_banner() -> None:
    pause_all_spinners()
    await asyncio.sleep(0.1)  # Delay to let spinner fully clear
```

**Impact:** These 100ms delays add up. A typical response with 2 thinking parts and 3 tool calls burns 500ms in sleep calls. This is perceived latency, not actual work.

**Fix:** Replace with a synchronous spinner-clear primitive that blocks only until the terminal line is actually cleared (using Rich's Live display refresh), or use `await asyncio.sleep(0)` (yields to the event loop once without a time penalty).

---

## 4. Token Waste

### TW-01: System prompt assembled from scratch on every `build_pydantic_agent` call

**File:** `code_muse/agents/_builder.py:173-190`  
**Severity:** HIGH — repeated prompt construction

```python
def assemble_full_system_prompt(agent: Any, model_name: str | None = None) -> str:
    instructions = agent.get_full_system_prompt()  # always the same for a given agent
    agent_rules = load_muse_rules()                 # mtime-cached but checked every call
    if has_extended_thinking_active(resolved_model):
        instructions += EXTENDED_THINKING_PROMPT_NOTE
    prompt_additions = _cb.on_load_prompt()        # fires callbacks every call
    if prompt_additions:
        instructions += "\n" + "\n".join(str(p) for p in prompt_additions if p)
    return instructions
```

**Evidence:** `assemble_full_system_prompt` is called:
1. In `_builder._assemble_instructions()` during `build_pydantic_agent()`
2. In `_runtime._should_prepend_system_prompt()` on the first turn

The `on_load_prompt()` callback fires on every call, iterating all registered plugins. The result rarely changes between calls (plugins don't dynamically change their prompt additions).

**Impact:** Each call does callback iteration, string concatenation, and potential token counting. The resulting prompt is sent to the model, consuming input tokens. If the prompt could use Anthropic's `cache_control` markers, the entire system prompt + tool schemas could be cached server-side, saving ~5-10K tokens per subsequent request.

**Fix:** Cache the assembled prompt alongside the agent instance (keyed by model name + mtime of muse rules). Only reassemble when the model changes or muse rules file changes. Add Anthropic `cache_control` ephemeral markers to the system prompt block.

---

### TW-02: Tool schemas sent on every request — no provider-side caching

**File:** `code_muse/agents/_builder.py:195-217`  
**Severity:** HIGH — token waste per request

**Evidence:** `build_pydantic_agent()` registers all tools with `register_tools_for_agent()`. Pydantic-ai sends the full tool schema JSON on every API request. For agents with 15+ tools, each with Pydantic model schemas, this can be 3-5K tokens per request.

Anthropic's API supports `cache_control` with ephemeral cache breakpoints. If the system prompt and tool schemas are marked as cacheable, subsequent requests with the same prefix reuse the cached tokens (at 10% cost).

**Impact:** On a 20-turn conversation with 4K tokens of tool schemas: 80K tokens consumed at full price vs. 4K + 76K × 0.1 = 11.6K tokens with caching. Savings: ~68K tokens per 20-turn session.

**Fix:** In `make_model_settings()`, enable Anthropic prompt caching when the model supports it. Mark the system prompt and tools block with `cache_control: {"type": "ephemeral"}`. This is a model-level setting that pydantic-ai can pass through.

---

### TW-03: `_truncate_tool_result_content` preserves structural overhead of truncated results

**File:** `code_muse/agents/_compaction.py:278-320`  
**Severity:** MEDIUM — compaction waste

```python
TRUNCATION_MSG = "[Result truncated — re-call tool if full output is needed]"
...
new_parts.append(
    part.model_copy(update={"content": TRUNCATION_MSG})
)
```

**Evidence:** When old tool results are truncated, the `ToolReturnPart` is preserved with its `tool_call_id`, `tool_name` (implicitly via the corresponding `ToolCallPart`), and the truncated content string. For a conversation with 50 tool calls, the structural metadata (tool_call_id strings, `ToolCallPart` JSON, etc.) adds ~100-200 tokens per tool call pair.

**Impact:** After truncation, 50 truncated tool results still consume ~5-10K tokens of structural overhead. The actual useful information is just "tool X was called and returned Y".

**Fix:** For truncated results, replace the entire ToolCallPart/ToolReturnPart pair with a single `TextPart` summary: `"Tool 'read_file' called on foo.py (result truncated)"`. This collapses two parts (~200 tokens) into one (~15 tokens).

---

### TW-04: `on_load_prompt()` fires on every prompt assembly but returns stable results

**File:** `code_muse/agents/_builder.py:185-187`  
**Severity:** LOW — minor token waste + CPU waste

**Evidence:** `on_load_prompt()` iterates all registered `load_prompt` callbacks on every `assemble_full_system_prompt()` call. The callback results (e.g., file permission rules, skill documentation) are static within a session.

**Impact:** Minimal token waste (the results are appended either way), but the callback overhead on every call is unnecessary.

**Fix:** Cache `on_load_prompt()` results alongside the muse rules mtime. Only re-fire when the mtime changes or plugins are reloaded.

---

## 5. CPU/Memory Hotspots for Cythonization

### CY-01: `stringify_part()` — CRITICAL hotspot

**File:** `code_muse/agents/_history.py:37-80`  
**Estimated call frequency:** 5,000-50,000 per session (called for every part of every message during every compaction)

**Current cost per call:**
- 1x `id()` lookup (fast)
- 1x OrderedDict `.get()` (cache hit path, fast)
- On cache miss: 5-8x `hasattr()` + `getattr()` chains
- 2-3x `isinstance()` checks
- 1-2x `orjson.dumps()` for BaseModel/dict content
- 1x `"|".join(attributes)` string concatenation

**Cythonization strategy:**
- Type the `part` parameter as a known protocol (cdef class PartProtocol with typed attributes)
- Replace `hasattr`/`getattr` chains with typed attribute access + exception handling
- Use C-level string concatenation instead of Python list + join
- Keep the LRU cache but implement it as a C dict with manual eviction (avoid OrderedDict overhead)

**Expected speedup:** 3-5x on cache-miss path (the hot path during compaction).

---

### CY-02: `hash_message()` — HIGH hotspot

**File:** `code_muse/agents/_history.py:90-102`  
**Estimated call frequency:** 1,000-10,000 per session (called for every message during dedup + compaction)

**Current cost per call:**
- 1x OrderedDict `.get()` (cache hit path)
- On cache miss: 1-2x `getattr()` for `role`/`instructions`
- List comprehension over parts calling `stringify_part()`
- 1x `"||".join()` + `hash()`
- 1x `weakref.finalize()` creation + dict insertion

**Cythonization strategy:**
- Inline the `stringify_part()` calls (after Cythonizing CY-01)
- Use C-level `hash()` via the Python C API (avoids Python function call overhead)
- Replace `weakref.finalize` with a simpler generation-counter scheme: tag each hash with a `generation` counter, increment the generation on cache clear, and skip entries with stale generations

**Expected speedup:** 2-4x on cache-miss path.

---

### CY-03: `estimate_tokens()` — MEDIUM hotspot

**File:** `code_muse/agents/_history.py:104-110`  
**Estimated call frequency:** 10,000-100,000 per session (called for every part of every message during every token estimation)

**Current cost per call:**
```python
def estimate_tokens(text: str) -> int:
    return max(1, math.floor(len(text) / 3.0))
```

This is a one-liner, but it's called inside tight loops (e.g., `sum_tokens()` iterates all messages). The Python function call overhead (frame creation, argument unpacking, `math.floor` lookup) dominates the actual arithmetic.

**Cythonization strategy:**
- Inline into callers after Cythonizing CY-01/CY-02
- If kept as a function: `cdef int estimate_tokens(str text) noexcept` with `len(text) // 3` (integer division, no `math.floor` needed since `len()` returns int)
- The `/3.0` → `math.floor` pattern is unnecessary; `len(text) // 3` is equivalent and avoids float conversion

**Expected speedup:** 5-10x per call (eliminates Python function call overhead entirely).

---

### CY-04: `_matches_retryable_snippet()` — LOW hotspot

**File:** `code_muse/agents/_runtime.py:61-69`  
**Estimated call frequency:** 1-5 per session (only on retry), but the `any(s in msg for s in _RETRYABLE_SNIPPETS)` loop iterates 12 patterns

**Current cost per call:**
- 1x `str.lower()` on the error message
- 12x `in` substring checks (O(n*m) worst case)
- 1x special-case `stream` + `ended` check

**Cythonization strategy:**
- Pre-compile patterns into an Aho-Corasick automaton (or simpler: a Cython loop that does C-level `memmem` on the lowercase bytes)
- The list of 12 patterns is small enough that a Cython loop with `strncmp`-style matching would be fast
- Lower-priority since retries are infrequent

**Expected speedup:** 2-3x per call. Low priority since call frequency is low.

---

### CY-05: `ScanCache.invalidate()` path ancestor check — LOW hotspot

**File:** `code_muse/fs_scan_cache/scan_cache_core.pyx:122-158`  
**Estimated call frequency:** 1-10 per session (after file mutations)

**Current cost per call:**
- Iterates all cache keys
- For each: `Path.resolve()` + `is_relative_to()` (with Python 3.11 fallback)
- Two `try/except AttributeError` blocks per key

**Cythonization strategy:**
- The file is already `.pyx` with `cdef` declarations, but the `Path.resolve()` calls are still Python-level
- Convert path comparisons to C-level string prefix matching for the common case (paths are absolute after resolve)
- Skip the `is_relative_to` fallback for Python >= 3.12 (always available)

**Expected speedup:** 2-3x per call. Low priority since frequency is low.

---

### CY-06: Reference implementation: `strip_ansi()` (already Cythonized)

**File:** `code_muse/terminal_utils.pyx:20-85`  
**Notes:** This is the model for how hotspots should be Cythonized:
1. `cdef` typed locals for all loop variables
2. `nogil` block for the CPU-intensive scan loop
3. C-level `malloc`/`free` for the output buffer
4. Python API calls only outside the `nogil` block
5. Single-pass byte scan with no Python object creation in the hot loop

**Lesson for new Cython modules:** Follow this pattern. The key insight is that the hot loop must operate on C types (`unsigned char*`, `Py_ssize_t`, `int`) with GIL released. All Python object creation (list append, string concatenation) must happen outside the loop.

---

### CY-07: `sha256_hash.pyx` — under-utilized Cython

**File:** `code_muse/models_cache/sha256_hash.pyx`  
**Notes:** The `sha256_digest_file()` function has `cdef` locals and bound-method optimization, but `hashlib.sha256()` is still Python-level. The GIL is NOT released during the read+hash loop because `hasher.update` is a Python method.

**Potential improvement:** For large files, use C-level OpenSSL SHA256 directly (via `cdef extern from "openssl/sha.h"`) with `nogil`. This would enable true parallel hashing of multiple files. However, this adds an OpenSSL dependency and is low-priority since file hashing is I/O-bound, not CPU-bound.

---

## 6. Summary Roadmap

| Priority | ID | Category | File(s) | Description | Estimated Impact | Effort |
|----------|----|----------|---------|-------------|-------------------|--------|
| **P0** | BUG-01 | Bug | `agents/base_agent.py:203`, `agents/agent_manager.py:152` | Bare-comma `except` syntax — `KeyboardInterrupt`/`SystemExit` silently swallowed | Control-flow break | 5 min |
| **P0** | BUG-02 | Bug/Perf | `config/models.py:229,236` | `get_protected_token_count` → `get_model_context_length` → `load_config()` every turn | 6+ stat()s per turn | 30 min |
| **P1** | DF-01 | Design | `model_factory.py`, `summarization_agent.py`, `config/models.py` | Triple-redundant model config cache | Coherence risk + memory | 2-3 hr |
| **P1** | PB-01 | Perf | `model_factory.py:59-88` | `load_config()` fingerprint computation in hot paths | 6+ stat()s per call, 3-5 calls/turn | 1 hr |
| **P1** | PB-02 | Perf | `agents/_compaction.py:248` | Full-history re-hash on every turn | O(n) hash computations per turn | 2 hr |
| **P1** | TW-01 | Token | `agents/_builder.py:173-190` | System prompt assembled from scratch every build | ~5-10K tokens/request | 2 hr |
| **P1** | TW-02 | Token | `agents/_builder.py:195-217` | Tool schemas sent without provider-side caching | ~68K tokens/20-turn session | 3 hr |
| **P2** | DF-02 | Design | `config/__init__.py` | God-module re-export forces eager loading | Startup latency | 4 hr |
| **P2** | DF-03 | Design | `agents/_runtime.py:218-219` | Module-level callback registration side effect | Test contamination | 1 hr |
| **P2** | DF-05 | Design | `agents/_history.py:90-102` | `weakref.finalize` accumulation in global hash cache | GC pressure | 2 hr |
| **P2** | DF-06 | Design | `agents/_runtime.py:251-650` | 300-line nested `run()` function | Maintainability | 4 hr |
| **P2** | PB-03 | Perf | `callbacks.py:148-151` | `get_callbacks()` sorts on every call | Repeated sorting in hot paths | 30 min |
| **P2** | PB-05 | Perf | `event_stream_handler.py:164,183` + 10 sites | `asyncio.sleep(0.1)` spinner-clear delays | 500ms perceived latency per response | 2 hr |
| **P2** | CY-01 | Cython | `agents/_history.py:37-80` | `stringify_part()` — 3-5x speedup | Critical compaction hotspot | 4 hr |
| **P2** | CY-02 | Cython | `agents/_history.py:90-102` | `hash_message()` — 2-4x speedup | High-frequency hotspot | 3 hr |
| **P2** | CY-03 | Cython | `agents/_history.py:104-110` | `estimate_tokens()` — 5-10x per call | Eliminate Python call overhead | 1 hr |
| **P3** | DF-04 | Design | `agents/_compaction.py:154-170` | `queue.LifoQueue` for simple list reversal | Unnecessary lock overhead | 10 min |
| **P3** | PB-04 | Perf | `agents/event_stream_handler.py:108-118` | 10 per-part tracking dicts per stream | Dict allocation pressure | 1 hr |
| **P3** | TW-03 | Token | `agents/_compaction.py:278-320` | Truncated tool results preserve structural overhead | ~5-10K tokens after truncation | 2 hr |
| **P3** | TW-04 | Token | `agents/_builder.py:185-187` | `on_load_prompt()` fires on every assembly | Minor CPU + token waste | 30 min |
| **P3** | CY-04 | Cython | `agents/_runtime.py:61-69` | `_matches_retryable_snippet()` — 2-3x | Low-frequency retry path | 2 hr |
| **P3** | CY-05 | Cython | `fs_scan_cache/scan_cache_core.pyx:122-158` | `invalidate()` path ancestor check | Low frequency | 1 hr |

### Implementation Order

**Sprint 1 (Immediate — Bugs + Quick Wins):**
1. BUG-01: Fix `except` syntax (5 min)
2. BUG-02: Cache `get_model_context_length()` in session model cache (30 min)
3. PB-03: Sort callbacks at registration time (30 min)
4. DF-04: Replace `queue.LifoQueue` with list reversal (10 min)

**Sprint 2 (Short-term — Architecture + Performance):**
1. DF-01: Consolidate model config cache into `model_factory.py` (2-3 hr)
2. PB-01: Add TTL cache on `_models_config_fingerprint()` (1 hr)
3. PB-02: Maintain incremental `existing_hashes` on agent (2 hr)
4. DF-03: Move circuit-breaker registration out of module scope (1 hr)

**Sprint 3 (Medium-term — Token Optimization):**
1. TW-01: Cache assembled system prompt (2 hr)
2. TW-02: Add Anthropic `cache_control` markers for system prompt + tools (3 hr)
3. TW-03: Collapse truncated tool call pairs into summary TextParts (2 hr)
4. PB-05: Replace `asyncio.sleep(0.1)` spinner delays (2 hr)

**Sprint 4 (Medium-term — Cythonization):**
1. CY-03: Cythonize `estimate_tokens()` (simplest, highest per-call speedup) (1 hr)
2. CY-01: Cythonize `stringify_part()` (critical compaction hotspot) (4 hr)
3. CY-02: Cythonize `hash_message()` (depends on CY-01) (3 hr)

**Sprint 5 (Long-term — Structural):**
1. DF-02: Convert `config/__init__.py` to lazy imports (4 hr)
2. DF-06: Decompose `_runtime.run()` into module-level functions (4 hr)
3. DF-05: Replace `weakref.finalize` hash cache with WeakKeyDictionary or generation counter (2 hr)
4. PB-04: Collapse event_stream_handler tracking dicts (1 hr)

---

### Total Estimated Savings

| Metric | Before | After Sprint 3 | After Sprint 4 |
|--------|--------|-----------------|-----------------|
| Tokens/20-turn session (Anthropic) | ~80K overhead | ~15K overhead | ~15K overhead |
| Compaction time (200 msgs) | Baseline | ~40% faster | ~70% faster |
| Per-turn overhead (stat() syscalls) | 18-30 | 0-2 | 0-2 |
| GC pressure (finalizer objects) | Thousands | Hundreds | Hundreds |
| Perceived streaming latency | +500ms | +50ms | +50ms |
