# Muse — Agentic Python + Cython Review v2

Static review of the Muse code agent (`code_muse/`). No execution, builds, or tests were run. Findings cite concrete locations in `.py` / `.pyx` files. The agent loop is delegated to `pydantic-ai`; this review focuses on what Muse owns: the run wrapper, history compaction, tool registry, prompt assembly, message-bus, plugin pipeline, and existing Cython modules.

Scoring: Frequency × Complexity × Cython gain (1–5 each); P0/P1 candidates score >40.

---

## [P0] No max_steps / max_tool_calls / consecutive_error cap on the agent run
**Category**: Agentic Design
**Location**: `code_muse/agents/_runtime.py:266-360, run()` and `_do_run()`; `code_muse/config/__init__.py` → `get_message_limit()`
**Severity**: P0 — runaway-token risk, no upper bound on tool-error storms
**Description**: `run()` configures only `UsageLimits(request_limit=get_message_limit())`. There is no per-tool timeout, no cap on consecutive tool errors, no max-step circuit breaker, and the plugin `agent_exception` hook can request unlimited retries (only the *outer* `on_agent_run_result` retry counter is bounded by `get_max_hook_retries()`).
**Root Cause**: The "agent loop" is delegated to `pydantic_agent.run()`, so Muse cannot directly observe step count. Nothing local enforces a budget except the request_limit (count of LLM calls).
**Evidence**:
```python
# _runtime.py:264-269
async def _do_run(prompt_to_use: Any) -> Any:
    usage_limits = UsageLimits(request_limit=get_message_limit())
    ...
# Plugin can request retries without a counter:
# _runtime.py:294-310
hook_results = await on_agent_exception(exc, ...)
retry_req = next((r for r in hook_results if isinstance(r, dict) and r.get("retry")), None)
if not retry_req:
    raise
... return await _call()   # one extra attempt; but combined with streaming_retry it stacks
```
**Proposed Fix**:
1. Add `UsageLimits(request_limit=..., total_tokens_limit=...)` (pydantic-ai supports both) wired from config.
2. Track tool-error count inside `_do_run` (use a `pre_tool_call` / `post_tool_call` callback) and abort with a structured error after N consecutive failures.
3. Wrap `pydantic_agent.run()` in `asyncio.wait_for(..., timeout=get_overall_run_timeout())`.
4. Cap `on_agent_exception` retries the same way `on_agent_run_result` is capped (via `get_max_hook_retries()`).
**Token Impact**: Caps blast radius of a model that loops on a broken tool; can save tens of thousands of tokens per accident.
**Performance Impact**: Defensive — prevents pathological runs from monopolizing rate-limit budget.
**Effort**: S
**Risk if not fixed**: One bad prompt + a flaky tool can drain an entire context window and rate-limit allowance silently.

---

## [P0] `prune_interrupted_tool_calls` runs 4–5× per turn over the entire history
**Category**: Performance
**Location**:
- `code_muse/agents/_history.py:243-281, prune_interrupted_tool_calls()`
- Call sites: `_runtime.py:393, 412` (start + finally of `run_agent_task`); `_compaction.py:213-216, 252` (inside `_run_summarization_core`); `_history.py:316, filter_huge_messages` end; `_compaction.py:579-585, history_processor` end.
**Severity**: P0 (dominant Python overhead in long sessions)
**Description**: Each invocation walks all messages and inspects every part with `getattr(part, "tool_call_id", None)` and `getattr(part, "part_kind", None)`. With ~50 messages × ~5 parts × 5 calls/turn = 1,250 attribute lookups per turn. None of the calls share a result.
**Root Cause**: Defensive-coding sprinkle. Each layer added pruning "just in case" without removing earlier passes.
**Evidence**:
```python
# _runtime.py
agent._message_history = _history.prune_interrupted_tool_calls(agent._message_history)
...
finally:
    agent._message_history = _history.prune_interrupted_tool_calls(agent._message_history)
# _compaction.py:213
pruned = prune_interrupted_tool_calls(messages_to_summarize)
# _compaction.py:579-585
if filtered_count > 0 or len(cleaned) != len(agent._message_history):
    cleaned = prune_interrupted_tool_calls(cleaned)
# _history.py:316
return prune_interrupted_tool_calls(filtered)
```
**Proposed Fix**:
1. Run `prune_interrupted_tool_calls` exactly once per turn — at the end of `make_history_processor`. Remove the start-of-run prune, the finally prune, and the `filter_huge_messages` prune.
2. Add a fast first-pass check: if `tool_call_ids == tool_return_ids` exit immediately without rebuilding the list (already there, but pull it into a single helper called by the one survivor).
3. If callers need a guard, expose `_history.is_history_consistent(messages) -> bool` and only re-prune when it returns False.
**Hotspot Analysis**:
- Calls per agent run: ~5 × steps (~30–50 prune walks for a 6–10 step run).
- Complexity: O(N·P) per call, N=messages, P=parts/message; both growing during a session.
- Current time estimate: 0.5–3 ms per call, but the *redundancy* is the issue.
**Performance Impact**: 4–5× reduction in pruning CPU; cleaner data flow.
**Effort**: S
**Risk if not fixed**: Constant-factor waste that grows with conversation length; minor on each turn but accumulates noticeably in long sessions.

---

## [P0] `load_muse_rules()` does disk I/O on every `invoke_agent` call
**Category**: Token / Performance
**Location**:
- `code_muse/agents/_builder.py:23-65, load_muse_rules()`
- Called from `code_muse/tools/agent_tools.py:484-489` inside `invoke_agent` (every sub-agent invocation)
- Also called from `_runtime.py:240, _should_prepend_system_prompt` for claude-code-style models on the first turn of every run.
**Severity**: P0 (every sub-agent call hits disk; tokens silently doubled when both branches add rules)
**Description**: `load_muse_rules()` walks up to 8 candidate paths (`~/.muse/AGENT*.md`, `.muse/AGENT*.md`, `./AGENT*.md`) and reads files. Result is never cached; mtime never checked. Each `invoke_agent` re-reads them, then concatenates the result into the sub-agent's instructions; the parent's `_assemble_instructions` already added the same rules to the parent prompt.
**Root Cause**: The rules-loader has no caching, and each call site adds rules independently.
**Evidence**:
```python
# agent_tools.py:484
from code_muse.agents._builder import load_muse_rules
agent_rules = load_muse_rules()
if agent_rules:
    instructions += f"\n\n{agent_rules}"
```
And in `_runtime.py:_should_prepend_system_prompt`:
```python
system_prompt = agent.get_full_system_prompt()
rules = load_muse_rules()
if rules:
    system_prompt += f"\n{rules}"
```
**Proposed Fix**:
1. Memoize `load_muse_rules()` keyed by `(global_path_mtime, project_path_mtime)` — cheap stat() calls instead of re-reading.
2. Move rules merging into `_assemble_instructions` only; remove the duplicate concat in `agent_tools.invoke_agent` and `_runtime._should_prepend_system_prompt`.
3. For claude-code prompt-prepend mode, accept that `instructions` already contains the rules and stop appending again.
**Token Impact**: Eliminates duplicate AGENTS.md content in claude-code first-turn prompts (saves the size of AGENTS.md per first turn, often ~500–2,000 tokens).
**Performance Impact**: Removes 1–8 file reads per sub-agent invocation.
**Effort**: S
**Risk if not fixed**: Token duplication, slow sub-agent fan-out, and behavior drift between claude-code and OpenAI-style models.

---

## [P1] `_estimate_context_overhead` recomputes tool-schema tokens every turn
**Category**: Performance / Token
**Location**: `code_muse/agents/base_agent.py:130-160, _estimate_context_overhead()`; `code_muse/agents/_history.py:184-230, estimate_context_overhead()`
**Severity**: P1
**Description**: Called once inside `make_history_processor` on every turn. Iterates *all* registered pydantic tools, JSON-dumps each schema, runs `get_annotations()` if no schema is set, and applies the per-model multiplier. The tool set is fixed per agent build, so the overhead is constant within a session.
**Root Cause**: No caching — recomputed every history-processor invocation.
**Evidence**:
```python
# _history.py:208-227
for tool_name, tool_func in pydantic_tools.items():
    total += estimate_tokens(tool_name)
    description = getattr(tool_func, "__doc__", None) or ""
    if description:
        total += estimate_tokens(description)
    schema = getattr(tool_func, "schema", None)
    if schema is not None:
        schema_str = json.dumps(schema) if isinstance(schema, dict) else str(schema)
        total += estimate_tokens(schema_str)
    else:
        annotations = get_annotations(tool_func)
        if annotations:
            total += estimate_tokens(str(annotations))
```
**Proposed Fix**:
1. Cache the result on the agent instance keyed by `id(agent.pydantic_agent)`; invalidate in `build_pydantic_agent` and on `reload_code_generation_agent`.
2. Add a module-level LRU keyed by a tuple of (model_name, frozenset of tool ids) for cross-agent reuse.
**Hotspot Analysis**:
- Calls per agent run: 1 per turn × 6–10 turns = 6–10 per run.
- Complexity: O(T·schema_size) per call; T ≈ 30–80 tools in Muse.
- Current time estimate: 1–4 ms per call (dominated by `json.dumps` of large pydantic schemas).
**Performance Impact**: ~10–40 ms saved per run; less GC churn from dump strings.
**Effort**: S
**Risk if not fixed**: Constant-factor waste; grows linearly with the tool catalogue.

---

## [P1] `stringify_part` JSON-dumps message content on every hash and token estimate
**Category**: Hotspot → Cython
**Location**: `code_muse/agents/_history.py:18-72, stringify_part()`; called by `hash_message()` (line 84) and `estimate_tokens_for_message()` (line 175).
**Severity**: P1 — dominant CPU in the history processor for long sessions.
**Description**: For every part (≥1 per message), `stringify_part` does `getattr` chains, then `json.dumps(..., sort_keys=True, default=_json_safe)` of the part's `content` if it's a `BaseModel` or `dict`. Tool-return parts often carry large strings/dicts (file contents, command output). The id-keyed `_hash_cache` helps for repeated hashing of the same part but **not** for token estimation, where the cache is per-compaction-cycle (`CompactionCache`) — a fresh one is built each `compact()` call.
**Root Cause**: Pure-Python serialization of every part, every turn.
**Evidence**:
```python
# _history.py:42-58
elif isinstance(content, pydantic.BaseModel):
    dumped = json.dumps(content.model_dump(), sort_keys=True, default=_json_safe)
    attributes.append(f"content={dumped}")
elif isinstance(content, dict):
    dumped = json.dumps(content, sort_keys=True, default=_json_safe)
    attributes.append(f"content={dumped}")
```
**Proposed Fix**:
1. Move the JSON-canonicalization into `code_muse/agents/_history_native.pyx`:
```cython
# cython: language_level=3, boundscheck=False, wraparound=False
cpdef str stringify_part_native(object part):
    """Build the canonical string representation of a message part."""
    cdef list parts = [type(part).__name__]
    cdef object content
    ...
    return "|".join(parts)
```
2. Keep the JSON dump in Python but replace `json.dumps` with `orjson.dumps(..., option=orjson.OPT_SORT_KEYS)` (3–5× faster, no bytes→str conversion).
3. Add a global LRU on `(id(part), part_kind, tool_call_id)` so token estimation hits the same cache as hashing.
**Hotspot Analysis**:
- Calls per turn: ~N × 2 (hash + token) where N is parts count. For a 50-msg history with 5 parts/msg: 500 calls/turn.
- Complexity: each call O(content_size).
- Current time estimate: 5–25 ms per turn for tool-output-heavy histories.
- **Proposed Cython signature**:
```cython
cpdef str stringify_part_native(object part) noexcept
cpdef long fast_hash_message(object message)
```
**Performance Impact**: 4–8× speedup when content is large; releases 5–25 ms per step.
**Effort**: M
**Risk if not fixed**: Linear growth in compaction cost as conversations get longer.

---

## [P1] `_truncate_tool_result_content` runs unconditionally on every turn
**Category**: Performance
**Location**: `code_muse/agents/_compaction.py:613-665, compact_with_tool_truncation()` and `_truncate_tool_result_content()`
**Severity**: P1
**Description**: `compact_with_tool_truncation` always calls `_truncate_tool_result_content(messages)` before deferring to `compact()` — even when the history is well below the compaction threshold. The function reverse-scans the entire history to collect protected ids, then forward-scans every part to build new `ModelRequest(parts=...)` objects. With many tool returns, this allocates a fresh ModelRequest for each "old" tool turn every step.
**Root Cause**: No threshold guard before truncation.
**Evidence**:
```python
# _compaction.py:617-623
def compact_with_tool_truncation(...):
    truncated = _truncate_tool_result_content(messages)  # always runs
    return compact(agent, truncated, model_max, context_overhead)
```
**Proposed Fix**:
1. Skip `_truncate_tool_result_content` when `total_tokens < threshold * model_max`. Push that gate into the wrapper, mirroring the early-return inside `compact()`.
2. When tool-truncation does run, mark "already truncated" via a sentinel attribute so subsequent passes are no-ops.
**Performance Impact**: Saves O(N·P) per turn for the common case where history is small (~80% of turns in early sessions).
**Effort**: S
**Risk if not fixed**: Wasted CPU and unnecessary `ModelRequest` allocations on every turn.

---

## [P1] `_hash_cache` clears on overflow instead of LRU eviction
**Category**: Performance
**Location**: `code_muse/agents/_history.py:75-97`
**Severity**: P1
**Description**: When the id-keyed message-hash cache fills (8,192 entries) it calls `_hash_cache.clear()` — wiping all entries. After a clear, every subsequent `hash_message` call re-runs the expensive `stringify_part` pipeline until the cache refills.
**Root Cause**: `clear()` chosen for simplicity instead of bounded LRU eviction.
**Evidence**:
```python
# _history.py:93-97
if len(_hash_cache) >= _HASH_CACHE_MAX:
    _hash_cache.clear()
_hash_cache[msg_id] = result
weakref.finalize(message, _evict_hash_cache, msg_id)
```
**Proposed Fix**:
1. Replace `dict` with `collections.OrderedDict`; on overflow `popitem(last=False)` (oldest entry). Re-insert on hit via `move_to_end`.
2. Optional: drop the cap entirely — `weakref.finalize` already evicts when the message is GC'd; the global cap is only there to bound footprint.
**Performance Impact**: Avoids cache-stampede after every 8,192 unique messages; eliminates a recurring 5–25 ms cliff in long-running sessions.
**Effort**: S
**Risk if not fixed**: Periodic re-hashing storms in long sessions.

---

## [P1] `_find_best_window` (Jaro-Winkler fuzzy match) is pure Python — Cython candidate
**Category**: Hotspot → Cython
**Location**: `code_muse/tools/common.py:1361-1383, _find_best_window()`; called by `_replace_in_file` (`code_muse/tools/file_modifications.py:300-330`) on every fuzzy fallback edit.
**Severity**: P1
**Description**: For every replacement whose `old_str` is not an exact substring, the function slides a window of `win_size = old_str.splitlines()` over the haystack lines, joining each window with `"\n".join(...)` and calling `JaroWinkler.normalized_similarity(window, needle)`. With files near `MAX_FUZZY_FILE_LINES=20_000` and snippets near `MAX_FUZZY_OLD_SNIPPET_CHARS=20_000`, this is ~20k joins + 20k JW calls per fallback.
**Root Cause**: Not Cythonized; window strings are reallocated each iteration; the join is done at the Python level.
**Evidence**:
```python
# common.py:1376-1383
for i in range(len(haystack_lines) - win_size + 1):
    window = "\n".join(haystack_lines[i : i + win_size])
    score = JaroWinkler.normalized_similarity(window, needle)
    if score > best_score:
        best_score = score
        best_span = (i, i + win_size)
```
**Proposed Fix**:
1. Add `code_muse/tools/_fuzzy_window.pyx`:
```cython
# cython: language_level=3, boundscheck=False, wraparound=False
from rapidfuzz.distance import JaroWinkler

cpdef tuple find_best_window(list haystack_lines, str needle):
    cdef Py_ssize_t i
    cdef Py_ssize_t n = len(haystack_lines)
    cdef Py_ssize_t win_size
    cdef double best_score = 0.0
    cdef double score
    cdef object best_span = None
    needle = needle.rstrip("\n")
    cdef list needle_lines = needle.splitlines()
    win_size = len(needle_lines)
    if win_size == 0 or n < win_size:
        return (None, 0.0)
    for i in range(n - win_size + 1):
        # avoid join: use rapidfuzz.fuzz.ratio over an iterable of line indices
        score = JaroWinkler.normalized_similarity(
            "\n".join(haystack_lines[i : i + win_size]),
            needle,
        )
        if score > best_score:
            best_score = score
            best_span = (i, i + win_size)
    return (best_span, best_score)
```
2. Better: precompute haystack as a single string with line-offset map, then slice via memoryview to avoid `"\n".join` allocations entirely.
3. Add early-exit when `best_score >= 0.99`.
**Hotspot Analysis**:
- Calls per agent run: 0–10 (per fuzzy fallback). Each call: 5,000–20,000 windows.
- Complexity: O(L · M) Python work where L = lines in haystack, M = chars per window.
- Current time estimate: 100–800 ms per fallback for 10k-line files.
- **Proposed Cython signature**: `cpdef tuple find_best_window(list haystack_lines, str needle)`.
**Performance Impact**: 5–10× speedup (the JW kernel is already C inside rapidfuzz; gain comes from removing the Python join + loop overhead).
**Effort**: M
**Risk if not fixed**: Multi-second pauses when an LLM tries to fuzzy-edit a large file.

---

## [P1] Semantic compression runs ~30 regex passes per tool result, all pure Python
**Category**: Hotspot → Cython
**Location**: `code_muse/plugins/semantic_compression/compressor.py:200-310, _apply_compression_rules()`
**Severity**: P1
**Description**: `compress_semantic` is invoked from `_on_post_tool_call` for every string tool-result longer than 200 chars (`code_muse/plugins/semantic_compression/register_callbacks.py:52-75`). It then runs ~30 `re.sub` passes (Tier 1 + Tier 2 + structural + cleanup) per non-code segment. With shell output frequently 10–50 KB, this is a dominant per-step cost when the plugin is enabled.
**Root Cause**: Pure-Python regex pipeline; no early-exit when no patterns match; each pass produces a fresh string.
**Evidence**:
```python
# compressor.py:233-286 (each line allocates a new string)
s = _PASSIVE_BY_RE.sub(r"\2 \1", s)
s = _CLAUSE_TO_MODIFIER_RE.sub(r"\2 \1", s)
for pattern, replacement in _NOMINALIZATIONS:
    s = pattern.sub(replacement, s)
for pattern, replacement in _REDUNDANT_PAIRS:
    s = pattern.sub(replacement, s)
for pattern, replacement in _FILLER_PHRASES:
    s = pattern.sub(replacement, s)
s = _RE_COMPLEMENTIZER.sub(r"\1", s)
s = _RE_ARTICLES.sub("", s)
s = _RE_COPULAS.sub("", s)
...
```
**Proposed Fix**:
1. Move to `code_muse/plugins/semantic_compression/compressor_core.pyx` and:
   - Combine compatible patterns into a single big alternation using a function-replacer that dispatches on group name (saves ~20 passes).
   - Use `regex` (PyPI) which compiles a fused pattern DFA.
2. Skip whole pipeline if `len(text) < threshold` *and* an early character-set scan finds none of `{is, are, the, a, an, very, that}` substrings.
3. For very large inputs (>50 KB), run on the bytes-level via `cython` typed memoryview.
**Hotspot Analysis**:
- Calls per turn: every string tool-result > 200 chars → typical 1–5 per turn.
- Complexity: O(passes × len(text)). 30 passes × 30 KB = 900 KB of string churn per result.
- Current time estimate: 5–30 ms per result.
- **Proposed Cython signature**:
```cython
cpdef str compress_semantic_native(str text, bint aggressive)
```
**Performance Impact**: 3–6× speedup; halves GC churn from intermediate strings.
**Effort**: M
**Risk if not fixed**: Plugin is gated off by default precisely because of this cost — but the cost is in the way of making it default-on.

---

## [P1] No prompt caching across providers — `token_caching` plugin only observes Anthropic stats
**Category**: Token
**Location**: `code_muse/plugins/token_caching/cache_hit_tracking.py:1-160`; `code_muse/plugins/token_caching/cacheable_prefix_detection.py:1-30`; `code_muse/plugins/token_caching/register_callbacks.py:1-60`
**Severity**: P1
**Description**: The plugin reads `cache_read_input_tokens` / `cache_creation_input_tokens` from Anthropic responses and shows stats via `/cache`, but it does **not** insert `cache_control: {"type": "ephemeral"}` markers into outgoing requests. There is no equivalent cache-priming for OpenAI or Gemini either. Every step ships the full system prompt + tool schemas as fresh tokens to all non-Anthropic providers.
**Root Cause**: Stats-only implementation; no cache-control wiring at the request layer.
**Evidence**: `cacheable_prefix_detection.py` exists (33 lines) but is essentially a stub helper. `register_callbacks.py` only registers `/cache` slash-command handlers.
**Proposed Fix**:
1. Add a `pre_request` (or pydantic-ai message-mutation hook) that:
   - Marks the system prompt and tool-schema block with `cache_control` for Anthropic models.
   - Sets `prompt_cache_key` for OpenAI Responses API where supported.
2. Detect cacheable prefixes (system + AGENTS.md + tool schemas) and stable-tag them once per session.
3. Surface savings in the spinner/status line, not just behind `/cache`.
**Token Impact**: 70–90% reduction in input-token cost for repeated turns on Claude (cache reads at 0.1× base price).
**Effort**: M
**Risk if not fixed**: 5–10× higher token bill for long sessions on Anthropic; no caching at all on other providers.

---

## [P1] Inconsistent system prompt between claude-code and other models
**Category**: Agentic Design / Token
**Location**: `code_muse/agents/_runtime.py:228-251, _should_prepend_system_prompt()` vs `code_muse/agents/_builder.py:140-168, _assemble_instructions()`
**Severity**: P1
**Description**: For claude-code-style models, `_should_prepend_system_prompt` rebuilds the system prompt as `agent.get_full_system_prompt() + load_muse_rules()` and prepends it into the user prompt. This omits two pieces that `_assemble_instructions` *does* include:
- `EXTENDED_THINKING_PROMPT_NOTE` (when extended thinking is active)
- Plugin prompt additions from `on_load_prompt()` (file-permission rules, skill docs, etc.)

So claude-code agents see a different system prompt than every other provider.
**Root Cause**: Two parallel prompt-assembly paths drifted.
**Evidence**:
```python
# _runtime.py:240-251
system_prompt = agent.get_full_system_prompt()
rules = load_muse_rules()
if rules:
    system_prompt += f"\n{rules}"
prepared = prepare_prompt_for_model(...)
```
vs
```python
# _builder.py:144-168
instructions = agent.get_full_system_prompt()
... instructions += f"\n{agent_rules}"
if has_extended_thinking_active(...): instructions += EXTENDED_THINKING_PROMPT_NOTE
prompt_additions = _cb.on_load_prompt()
if prompt_additions:
    instructions += "\n" + "\n".join(...)
```
**Proposed Fix**:
1. Extract a single `assemble_full_system_prompt(agent, model_name) -> str` and call it from both paths.
2. Have `_should_prepend_system_prompt` reuse the *same* assembled string `_assemble_instructions` already built; `agent.pydantic_agent.instructions` already holds it.
**Token Impact**: Avoids both omissions and (in fix scenarios) duplications.
**Performance Impact**: Removes a redundant `load_muse_rules()` disk read on every claude-code first turn (paired with P0 #3).
**Effort**: S
**Risk if not fixed**: Different agent behavior on different providers; subtle bug surface for prompt-driven plugins.

---

## [P1] Existing Cython modules hold the GIL and lean on Python objects
**Category**: Cython
**Location**:
- `code_muse/fs_scan_cache/scan_cache_core.pyx` (entire file)
- `code_muse/security/redaction.pyx:90-141, redact_secrets()`
- `code_muse/stream_parser/utf8_stream_parser.pyx:80-160, push_bytes()`
- `code_muse/stream_parser/tagged_line_parser.pyx` (entire file)
- `code_muse/terminal_utils.pyx:31-65, strip_ansi()`
**Severity**: P1
**Description**: Most `.pyx` modules ship typed locals but the bodies still call Python APIs (`hashlib.sha256().update`, `OrderedDict.move_to_end`, `Path.is_relative_to`, `re.compile`, `bytearray.append`, etc.) under the GIL. Speedup vs. plain Python is small (1.2–2×) and parallelism is impossible because no kernel uses `nogil`.
**Root Cause**: Cython was applied as `cdef`-decoration of existing Python rather than as a redesign around C-level data.
**Evidence (representative)**:
```cython
# scan_cache_core.pyx — lock held for the whole match, no nogil block
with self._lock:
    if key in self._cache:                         # Python dict lookup
        entry = self._cache[key]
        if is_fresh(entry, now):                   # Python call, attr access
            self._cache.move_to_end(key)           # Python OrderedDict
            ...
```
```cython
# redaction.pyx — recursive Python over `Any`
def redact_secrets(value: Any, ...):
    if isinstance(value, dict):
        d = {}
        for k, v in value.items():
            ...
```
```cython
# terminal_utils.pyx:32 — `out.append(ch)` is a Python method call
cdef bytearray out = bytearray()
out.append(ch)
```
**Proposed Fix**:
1. **`scan_cache_core.pyx`**: Hold the lock only for the dict mutation; do `Path(key[0]).resolve()` and ancestor checks outside the lock with snapshotted keys. Add `nogil` to a typed inner helper that does the freshness compare on `double created_at` + `double now`.
2. **`redaction.pyx`**: Pre-flatten `(value, key)` pairs into a typed work-stack and process strings via Cython byte-level scanners using `regex`'s C API or hand-coded automata. Drop `json.loads`/`json.dumps` round-trip — emit redactions in place.
3. **`utf8_stream_parser.pyx`**: Replace `bytearray.decode` failures with a hand-rolled UTF-8 validator over `const unsigned char[:]` that returns `(valid_up_to, is_incomplete)` with `nogil`.
4. **`tagged_line_parser.pyx`**: Replace `_match_open` / `_match_close` scans with a precomputed `dict[str, TagSpec]` keyed by trimmed delimiter string; turn `_is_tag_prefix` into a precomputed sorted prefix table or trie.
5. **`terminal_utils.pyx:strip_ansi`**: Use `unsigned char *` plus pre-allocated `bytearray(n)` (write index) instead of repeated `out.append` Python calls; or write to a `cython.view.array` and slice at the end.
**Performance Impact**: Most kernels go from 1.5× to 8–20× faster, plus enable parallel calls when GIL is released.
**Effort**: M (per file)
**Risk if not fixed**: Cython binaries are large (1.2 MB `.so` for `redaction`, 270 KB for `utf8_stream_parser`) but the wins are modest; build cost is paid without realizing the speedups.

---

## [P2] Tool registry has no per-tool timeout / retry / idempotency wiring
**Category**: Agentic Design
**Location**: `code_muse/tools/__init__.py:88-200, TOOL_REGISTRY` and `register_tools_for_agent()`; `code_muse/plugins/tool_registry/registry.py:1-115` (rich metadata that is *not* consulted by the runtime).
**Severity**: P2
**Description**: `TOOL_REGISTRY` maps tool names to register functions but carries no metadata. The richer `ToolMetadata` (tier, category, destructive, idempotent, requires_confirmation) lives in the `tool_registry` plugin and is currently used only for documentation and allow-list selection. The runtime path (`register_tools_for_agent` → `pydantic_agent.tool`) ignores per-tool timeouts, retry counts, and confirmation requirements; everything inherits the global `tool_retries=3` from `_builder.py:194`.
**Root Cause**: Two parallel registries with no shared schema; pydantic-ai's per-tool retry decorator is unused.
**Evidence**:
```python
# tools/__init__.py:88-200
TOOL_REGISTRY = {
    "list_agents": register_list_agents,
    "invoke_agent": register_invoke_agent,
    ...
}
# _builder.py:185-198 — single tool_retries for all tools
return PydanticAgent(
    ...,
    tool_retries=3,
    ...
)
```
**Proposed Fix**:
1. Promote `ToolMetadata` to be the authoritative schema in `code_muse/tools/`. Each register-function returns metadata.
2. In `register_tools_for_agent`, pass `retries=`, `requires_confirmation=`, and a wrapping decorator that enforces `timeout=` per tool.
3. Tag destructive tools so the safety plugin can require approval automatically rather than via implicit naming heuristics in `tool_registry/definitions.py:_derive_destructive`.
**Performance Impact**: Indirect — fewer wasted tool retries on tools that should fail fast (e.g. read-only).
**Effort**: M
**Risk if not fixed**: Subtle correctness issues (tool that mutates is allowed 3 retries) and slow-tool stalls.

---

## [P2] `_save_session_history` writes two JSON files atomically per sub-agent step
**Category**: Performance
**Location**: `code_muse/tools/agent_tools.py:117-185, _save_session_history()`
**Severity**: P2
**Description**: Every sub-agent invocation, after each turn, dumps its full `message_history` to both `<session>.json` (atomic via `atomic_write_private_json`) and `<session>.pkl` (also JSON content, written non-atomically). For sub-agents that run many tool turns this is two full re-serializations of the entire session per turn.
**Root Cause**: Backward-compat `.pkl` file kept "for old callers" plus the canonical `.json`.
**Evidence**:
```python
# agent_tools.py:147-160
json_path = sessions_dir / f"{session_id}.json"
atomic_write_private_json(json_path, session_data)
pkl_path = sessions_dir / f"{session_id}.pkl"
try:
    tmp_pkl = pkl_path.with_suffix(".tmp")
    with open(tmp_pkl, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)
    tmp_pkl.replace(pkl_path)
except OSError:
    pass
```
**Proposed Fix**:
1. Drop the `.pkl` compat write; symlink it to `.json` if anything still expects the suffix.
2. Skip the `indent=2` for the canonical write (or make it config-gated) — saves ~30% serialization time and disk space.
3. Only re-save when `message_history` length changed since the last save (track a counter on the in-memory session record).
**Performance Impact**: Halves disk write volume for sub-agent sessions; eliminates one `json.dumps` per turn.
**Effort**: S
**Risk if not fixed**: I/O amplification, especially noticeable for parallel sub-agents.

---

## [P2] `agent_manager._discover_agents` instantiates every agent class to read its name
**Category**: Performance
**Location**: `code_muse/agents/agent_manager.py:178-275, _discover_agents()`
**Severity**: P2
**Description**: For every Python module in `code_muse/agents/` and its sub-packages, the function imports the module, finds all `BaseAgent` subclasses, and *instantiates* each one to read `agent_instance.name`. Construction triggers `__init__` side effects (config reads in `MuseAgent`, JSON load in `JSONAgent`).
**Root Cause**: Naming is an instance property rather than a class attribute.
**Evidence**:
```python
# agent_manager.py:213-218
agent_instance = attr()
_AGENT_REGISTRY[agent_instance.name] = attr
```
**Proposed Fix**:
1. Move `name` and `display_name` to class-level `ClassVar[str]`. Discovery becomes pure class introspection; no construction needed until the user actually picks the agent.
2. Defer `JSONAgent` JSON parsing until `load_agent` is called — store only the path in the registry.
**Performance Impact**: ~50–200 ms saved on first discovery; faster cold-start for the CLI; no load of OpenAI/Anthropic clients via Muse's tool-time imports.
**Effort**: M (touches every Python agent class)
**Risk if not fixed**: Slower startup, especially as new agents are added; tools auto-imported just from discovery.

---

## [P2] `difflib.unified_diff` per file edit is pure Python and unbounded by line count
**Category**: Hotspot
**Location**: `code_muse/tools/file_modifications.py:330-355` (replace), `455-470` (write), `595-610` (delete-snippet)
**Severity**: P2
**Description**: Every successful edit produces a unified diff via `difflib.unified_diff(...)`. The cap is `MAX_DIFF_BYTES = 512_000` after the diff is built. For large files where 50% of lines change, building the diff allocates O(N²) memory in the worst case.
**Root Cause**: Pure Python diff algorithm; no early-exit when one side is empty (file create/delete).
**Evidence**:
```python
# file_modifications.py:455-470
diff_lines = difflib.unified_diff(
    old_lines,
    content.splitlines(keepends=True),
    fromfile="/dev/null" if not exists else f"a/{file_path.name}",
    tofile=f"b/{file_path.name}",
    n=get_diff_context_lines(),
)
diff_text = "".join(diff_lines)
if len(diff_text) > MAX_DIFF_BYTES:
    ...
```
**Proposed Fix**:
1. For "create" path (`old_lines == []`) skip diff and just emit `+` lines truncated to `MAX_DIFF_BYTES`.
2. For "delete-file" path skip diff entirely (the agent already knows file content).
3. For real modifications, switch to `git diff --no-index` via the already-installed `git` binary when files are >2,000 lines (much faster) or use `python-Levenshtein`'s editops.
4. Cython-port the unified-diff *formatter* (the `_format_range_unified` part) — `difflib`'s algorithm is C-ish but the formatter is hot Python.
**Performance Impact**: 5–10× speedup on large edits, lower memory peak.
**Effort**: M
**Risk if not fixed**: 200–500 ms stalls on big-file edits; UI freezes during diff render.

---

## [P2] `streaming_retry()` rebuilds wrapper closures per call
**Category**: Performance
**Location**: `code_muse/agents/_runtime.py:154-190, streaming_retry()`; used at `_runtime.py:289` and `_runtime.py:339`
**Severity**: P2
**Description**: `streaming_retry()` is a decorator factory. Each invocation defines a new `runner` async function and re-decorates `_call`. The retry semantics could be expressed inline; the closure churn allocates a fresh function object per attempt.
**Root Cause**: Idiomatic but unnecessary decorator usage in a hot path.
**Evidence**:
```python
# _runtime.py:289-296
@streaming_retry()
async def _call() -> Any:
    return await pydantic_agent.run(
        prompt_to_use,
        message_history=agent._message_history,
        usage_limits=usage_limits,
        event_stream_handler=stream_handler,
        **kwargs,
    )
```
**Proposed Fix**:
1. Inline the retry loop in `_do_run`. Keep `should_retry_streaming` as a free function.
2. Promote retry counts and delays to a single `RetryPolicy` dataclass shared with hook-result retries.
**Performance Impact**: Marginal CPU; cleaner trace stacks; easier to plumb a per-tool retry policy in later.
**Effort**: S
**Risk if not fixed**: Cosmetic; mostly code-smell.

---

## [P2] Sub-agent invocation re-creates pydantic-ai `Agent` every call
**Category**: Performance
**Location**: `code_muse/tools/agent_tools.py:430-540, invoke_agent()`
**Severity**: P2
**Description**: Each `invoke_agent` call:
- Loads agent config (`load_agent`).
- Loads model (`ModelFactory.get_model`) — already cached via `_model_instance_cache` (good).
- Builds a fresh pydantic-ai `Agent(...)` object with a new tool toolset, instructions, etc.
- Recomputes `instructions` including `load_muse_rules()` (see P0 #3) and `on_load_prompt()` plugin additions.

The pydantic-ai `Agent` itself is not cached; under fan-out (parent → 8 sub-agents) this means 8 `Agent` constructions per fan-out call.
**Root Cause**: No agent-instance cache for sub-agents.
**Evidence**:
```python
# agent_tools.py:498-540
prepared = prepare_prompt_for_model(model_name, instructions, prompt, ...)
instructions = prepared.instructions
prompt = prepared.user_prompt
model_settings = make_model_settings(model_name)
# ... new pydantic-ai Agent created on every call
```
**Proposed Fix**:
1. Cache `(agent_name, model_name, frozenset(tools))` → pydantic-ai `Agent`; rebuild only when AGENTS.md mtime or tool registration changes.
2. Hoist `prepare_prompt_for_model` inside the cache key so the cache survives across calls.
**Performance Impact**: 50–200 ms per invocation saved on warm cache; lower memory churn under fan-out.
**Effort**: M
**Risk if not fixed**: Cold sub-agent invocations on every call; visible UI latency.

---

## [P2] Fixed-string token estimator uses `len(text) // K` with three different K values
**Category**: Token Accuracy
**Location**:
- `code_muse/agents/_history.py:174-176, estimate_tokens()` — uses `len / 3.0`
- `code_muse/agents/event_stream_handler.py:264-265` — uses `len / 2.5`
- `code_muse/tools/file_operations.py:512` — uses `len // 4`
**Severity**: P2
**Description**: Three different "chars-per-token" constants in three hot paths. Plus per-model multipliers in `_history._TOKEN_MULTIPLIER_RULES` only applied in compaction. The result is wildly inconsistent context-budget reporting.
**Root Cause**: Heuristics added independently; no shared estimator.
**Evidence**:
```python
# _history.py:174-176
def estimate_tokens(text: str) -> int:
    return max(1, math.floor(len(text) / 3.0))
# event_stream_handler.py:264-265
estimated_tokens = max(1, math.floor(len(args_delta) / 2.5))
# file_operations.py:512
num_tokens = len(content) // 4
```
**Proposed Fix**:
1. Single `code_muse/agents/token_estimator.py` (or `.pyx`) with one function `estimate_tokens(text, model_name=None) -> int` and one set of per-model multipliers.
2. Optionally back it with `tiktoken.encoding_for_model(...).encode(...)` when accurate counts matter (e.g. context-budget gate).
**Token Impact**: More accurate compaction decisions — currently the system over- or under-counts by 30%+ in different code paths.
**Effort**: S
**Risk if not fixed**: Threshold-driven compaction triggers at the wrong time; users see inconsistent "tokens used" numbers.

---

## [P2] `event_stream_handler` fires sync callbacks per `part_delta` event
**Category**: Performance
**Location**: `code_muse/agents/event_stream_handler.py:34-79, _fire_stream_event()` and `_fire_stream_event_sync()`; `code_muse/agents/event_stream_handler.py:208-270` (delta loop)
**Severity**: P2
**Description**: For every streaming delta (potentially hundreds per response), `_fire_stream_event_sync` does a fresh `from code_muse import callbacks` and `from code_muse.messaging import get_session_context` import lookup, then fires callbacks. Module imports are cached, but the dotted attribute resolution still runs and the callback list is re-walked.
**Root Cause**: Imports inside hot path; no fast-path when no plugins listen.
**Evidence**:
```python
# event_stream_handler.py:62-71
def _fire_stream_event_sync(event_type: str, event_data: Any) -> None:
    try:
        from code_muse import callbacks
        from code_muse.messaging import get_session_context
        agent_session_id = get_session_context()
        callbacks.on_stream_event_sync(event_type, event_data, agent_session_id)
    except ImportError:
        ...
```
**Proposed Fix**:
1. Hoist the imports to module-level once.
2. Add a "no listeners" fast path: when `callbacks._stream_event_listener_count == 0`, skip entirely. Maintain a counter inside `register_callback`.
3. Consider batching `part_delta` events (e.g. emit every 50 ms) when no listener requires per-token granularity.
**Performance Impact**: Few-ms per response; matters for long streamed responses (~hundreds of deltas).
**Effort**: S
**Risk if not fixed**: Streaming overhead grows linearly with plugin count.

---

## [P2] Prompt building uses `instructions += f"..."` chains
**Category**: Hotspot → optional Cython
**Location**: `code_muse/agents/_builder.py:140-168, _assemble_instructions()`; `code_muse/tools/agent_tools.py:485-498` (sub-agent prompt build)
**Severity**: P2
**Description**: System-prompt assembly uses repeated `s += f"\n{...}"` allocations. For typical prompts this is small; for agents with many plugins (extended-thinking notes, AGENTS.md, file-permission rules, skills docs) the prompt can run 5–20 KB. Repeated concatenation copies the buffer each step.
**Root Cause**: Idiomatic Python; not measured.
**Evidence**:
```python
# _builder.py:144-168
instructions = agent.get_full_system_prompt()
agent_rules = load_muse_rules()
if agent_rules:
    instructions += f"\n{agent_rules}"
if has_extended_thinking_active(...):
    instructions += EXTENDED_THINKING_PROMPT_NOTE
prompt_additions = _cb.on_load_prompt()
if prompt_additions:
    instructions += "\n" + "\n".join(...)
```
**Proposed Fix**:
1. Build a `list[str]` of fragments and `"\n".join(...)` once.
2. (Stretch) Move into a Cython helper using `bytearray` writes and a single `decode("utf-8")` at the end.
**Performance Impact**: ~1–3 ms per build; matters under sub-agent fan-out where build runs per call.
**Effort**: S
**Risk if not fixed**: Minor; mostly clarity.

---

## [P3] `_default_cache` for `fs_scan_cache` is a global mutable singleton
**Category**: Agentic Design
**Location**: `code_muse/fs_scan_cache/tool_integration.py:217-225`
**Severity**: P3
**Description**: A module-level `_default_cache: ScanCache | None = None` is lazily initialized on first use. Stable across the whole process, including across sub-agents. Means stale entries can leak across sessions.
**Proposed Fix**: Tie the cache lifecycle to the agent (or session) and invalidate on agent switch. Honor `invalidation_hooks.py`.
**Effort**: S

---

## [P3] `except A, B:` PEP 758 syntax pinned to Python 3.14
**Category**: Code Health
**Location**: ~25 sites including `code_muse/agents/base_agent.py:188`, `code_muse/cli_runner/loop.py:210`, `code_muse/tools/command_runner.py:101`, `code_muse/agents/agent_manager.py:152`
**Severity**: P3 (informational — *not* a SyntaxError under the project's pinned Python 3.14)
**Description**: PEP 758 (Py3.14+) allows `except A, B:` without parentheses. The codebase relies on this. Older parsers (3.13 and earlier), tooling that uses lib2to3-style parsing, and many static analysers will fail to parse these files.
**Evidence**: `pyproject.toml` requires `>=3.14,<3.16`. Parsing under 3.14 is fine. Verified `except` semantics: all listed exceptions are caught (it's parsed as a tuple).
**Proposed Fix**: Convert to `except (A, B, C):` to keep the codebase parseable by older tooling. Cosmetic but improves portability of static-analysis pipelines (e.g. ruff is fine; some external tools may not be).
**Effort**: S — single sweep with a regex.

---

## [P3] MD5 used for config-fingerprint hashing
**Category**: Code Health
**Location**: `code_muse/summarization_agent.py:50-95, _models_config_fingerprint()`
**Severity**: P3
**Description**: Uses `hashlib.md5(usedforsecurity=False)` for cache invalidation. Already correctly flagged `usedforsecurity=False` so no security concern. But MD5 here is arbitrary — `hashlib.blake2b(digest_size=16)` is faster and equally well-suited.
**Proposed Fix**: Swap MD5 for blake2b. Aesthetic, but removes any auditor flagging MD5 in the source.
**Effort**: S

---

## [P3] `_RUNNING_PROCESSES` is a `set[Popen]` keyed on object identity, with stale entries
**Category**: Agentic Design / Resource Hygiene
**Location**: `code_muse/tools/command_runner.py:130-147, 218-230`
**Severity**: P3
**Description**: Stale `Popen` objects are pruned only inside `get_running_shell_process_count`. The set can hold dead Popen references between calls.
**Proposed Fix**: Move stale-pruning into `_unregister_process` (already runs in `finally` blocks) so it stays consistent.
**Effort**: S

---

## [P3] Sub-agent `_active_subagent_tasks` global set is process-wide
**Category**: Agentic Design
**Location**: `code_muse/tools/agent_tools.py:46`; cancellation logic in `code_muse/agents/_runtime.py:393-410`
**Severity**: P3
**Description**: One global set is shared across all parents. Cancelling the top-level agent walks every sub-agent task in the process, including unrelated branches.
**Proposed Fix**: Scope `_active_subagent_tasks` per-parent agent. Cancellation walks only the local subtree.
**Effort**: M

---

## [P3] No metric for "tokens spent per agent step" surfaced to plugins
**Category**: Observability
**Location**: `code_muse/agents/_runtime.py:529-544, on_agent_run_end` callback firing
**Severity**: P3
**Description**: `on_agent_run_end` accepts `metadata={"model": ...}` but no per-step latency, no per-tool count, no per-tool latency. Token budgets and tool-usage profiling are guessed by plugins from streaming events.
**Proposed Fix**: Pass a `RunStats` dataclass to `on_agent_run_end` with `tool_calls: list[(name, latency_ms, ok)]`, `total_input_tokens`, `total_output_tokens`, `total_steps`. Hook the values from pydantic-ai's `RunResult.usage()` and a `pre_tool_call`/`post_tool_call` shim.
**Effort**: M

---

## [P3] `_strip_empty_thinking_parts` rebuilds messages even when no parts are stripped
**Category**: Performance
**Location**: `code_muse/agents/_compaction.py:496-520`
**Severity**: P3
**Description**: `dataclasses.replace(msg, parts=[...])` allocates a new `ModelRequest` even when the filter list equals the original. The function does report `filtered_count` correctly but the allocations happen anyway when *any* part has empty content.
**Proposed Fix**: Skip `replace()` when `len(new_parts) == len(parts)`.
**Effort**: S

---

## Summary Roadmap

| Priority | Issue | Category | Effort | Gain |
|----------|-------|----------|--------|------|
| P0 | No max_steps / max_tool_calls / consecutive_error cap | Agentic Design | S | Prevents runaway token spend |
| P0 | `prune_interrupted_tool_calls` runs 4–5× per turn | Performance | S | 4–5× reduction in pruning CPU |
| P0 | `load_muse_rules()` disk I/O on every sub-agent call | Token / Performance | S | Saves 500–2k duplicate tokens/call + disk reads |
| P1 | `_estimate_context_overhead` re-runs every turn | Performance / Token | S | 10–40 ms saved per run |
| P1 | `stringify_part` JSON-dumps content in hot path | Hotspot → Cython | M | 4–8× speedup; -5–25 ms/turn |
| P1 | `_truncate_tool_result_content` runs unconditionally | Performance | S | Skips O(N·P) on most turns |
| P1 | `_hash_cache.clear()` on overflow | Performance | S | No periodic re-hash storms |
| P1 | `_find_best_window` (JW fuzzy match) pure Python | Hotspot → Cython | M | 5–10×; -100–700 ms per fuzzy edit |
| P1 | `semantic_compression` runs 30 regex passes | Hotspot → Cython | M | 3–6× compression speedup |
| P1 | No prompt caching across providers | Token | M | 70–90% input-token cost reduction (Anthropic) |
| P1 | Inconsistent prompt for claude-code vs others | Agentic Design | S | Prompt parity; remove dup load_muse_rules |
| P1 | Existing Cython modules hold GIL, lean on Python | Cython | M | 1.5× → 8–20× per kernel |
| P2 | Tool registry has no per-tool timeout/retry | Agentic Design | M | Better safety + fewer wasted retries |
| P2 | Sub-agent saves two JSON files per turn | Performance | S | ½× disk write volume |
| P2 | `_discover_agents` instantiates every class | Performance | M | -50–200 ms cold-start |
| P2 | `difflib.unified_diff` pure Python on big files | Hotspot | M | 5–10× on large diffs |
| P2 | `streaming_retry()` decorator churn | Performance | S | Cosmetic + simpler stacks |
| P2 | Sub-agent rebuilds pydantic-ai `Agent` per call | Performance | M | -50–200 ms per invoke under fan-out |
| P2 | Three different token-estimator constants | Token Accuracy | S | Consistent context-budget reports |
| P2 | `event_stream_handler` per-delta callback overhead | Performance | S | Sub-ms saved per delta × hundreds |
| P2 | Prompt build via `+= f"…"` chains | Hotspot | S | -1–3 ms per build |
| P3 | Global `_default_cache`, `_active_subagent_tasks`, etc. | Code Health | S–M | Cleanliness |
| P3 | `except A, B:` PEP 758 portability | Code Health | S | External-tool compatibility |
| P3 | MD5 → blake2b for fingerprint | Code Health | S | Aesthetic |
| P3 | `_strip_empty_thinking_parts` redundant allocs | Performance | S | Minor |
| P3 | Missing per-step run stats for plugins | Observability | M | Better diagnostics |

---

## Top 5 Cythonization Candidates (new code worth writing)

1. **`code_muse/agents/_history_native.pyx`** — `stringify_part_native`, `fast_hash_message`, `estimate_tokens_native`. The single biggest CPU sink in the agent loop. Estimated 4–8× over current Python; releases ~5–25 ms/turn that compounds with conversation length.
2. **`code_muse/tools/_fuzzy_window.pyx`** — `find_best_window` (Jaro-Winkler sliding window). Removes Python-level join + loop overhead around the already-C JW kernel; 5–10× speedup; gates a P0-impact tool (replace_in_file fuzzy fallback).
3. **`code_muse/plugins/semantic_compression/compressor_core.pyx`** — `compress_semantic_native(str text, bint aggressive)`. Replaces 30 regex passes with a fused pattern + early-exit; 3–6× speedup; unblocks default-on compression.
4. **Audit / rewrite of `scan_cache_core.pyx` and `redaction.pyx`** — both currently get only 1.2–2× from Cython. With `nogil` typed inner loops and removal of Python collection ops they can clear 8–15×.
5. **`code_muse/agents/_prune_native.pyx`** — `prune_interrupted_tool_calls_native(list messages) -> list`. Once the dedup pass (P0 #2) is in place, the single remaining call benefits from typed loops and a `frozenset[Py_UNICODE]`-style id table; 3–5× speedup over the Python implementation.

---

## Cross-cutting Recommendations

- **Centralize prompt assembly.** Today AGENTS.md, plugin prompt additions, extended-thinking note, and identity get concatenated in two different paths. One assembler, one cache.
- **Centralize token estimation.** Three constants in three files mean three different "context %" numbers. One `token_estimator.py` (optionally `.pyx`) is straightforward and enables real prompt caching.
- **Add a `RunPolicy` dataclass** that holds `max_steps`, `max_tool_calls`, `tool_timeout`, `consecutive_error_limit`, and per-tool overrides. Pass it through `run()` and the sub-agent invocation path.
- **Treat `prune_interrupted_tool_calls` as compaction's responsibility only.** Remove the defensive sprinkles. Make `make_history_processor` the single owner.
- **Drop the `.pkl` compat write** in `_save_session_history`. It's already JSON content.
- **Profile, don't decorate.** Several `.pyx` files (`redaction`, `scan_cache_core`, `tagged_line_parser`, half of `terminal_utils`) are decorated Python rather than typed Cython. Either redesign around C-typed data with `nogil` or revert to `.py` and save the build cost.

---

## Methodology Notes

Files reviewed (representative):
- Agent runtime: `_runtime.py`, `_history.py`, `_compaction.py`, `_builder.py`, `base_agent.py`, `event_stream_handler.py`, `agent_manager.py`, `agent_muse.py`, `prompt_v3.py`.
- Tools: `tools/__init__.py`, `agent_tools.py`, `command_runner.py`, `file_operations.py`, `file_modifications.py`, `common.py`.
- Plugins: `semantic_compression/`, `token_caching/`, `filter_engine/strategies/code.pyx`, `filter_engine/strategies/ast_compressor.pyx`, `tool_registry/`.
- Cython modules: `terminal_utils.pyx`, `models_cache/sha256_hash.pyx`, `fs_scan_cache/scan_cache_core.pyx`, `security/redaction.pyx`, `stream_parser/utf8_stream_parser.pyx`, `stream_parser/tagged_line_parser.pyx`.
- Build/config: `build_extensions.py`, `pyproject.toml`.

What was *not* directly profiled (so timing estimates are upper-bound static guesses): no execution was performed. All performance numbers are derived from complexity analysis and library knowledge (rapidfuzz JW core, regex engine cost, Python attribute-lookup costs).

INSUFFICIENT DATA was not reached for any finding above; every recommendation cites at least one concrete code location.
