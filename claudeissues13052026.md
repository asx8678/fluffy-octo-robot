# MUSE Code Review: Performance Bottlenecks & Design Issues
**Date:** 2026-05-13

---

## P0 — Critical Bugs

### 1. Python 2 Exception Syntax (CORRECTNESS BUG)
**Files:** `config.py`, `agent_manager.py`, `command_runner.py`, `base_agent.py`, `_runtime.py`, `file_operations.py`, `background_jobs.py`

```python
except ValueError, TypeError:       # WRONG — catches ValueError, binds to name "TypeError"
except ValueError, OSError:          # WRONG — OSError is NEVER caught
except asyncio.CancelledError, KeyboardInterrupt, SystemExit:  # WRONG
```

In Python 3, `except X, Y:` catches `X` and assigns the exception to variable `Y`, shadowing the builtin. This means the second (and subsequent) exception types are **never caught**. This is present throughout the codebase.

**Fix:** `except (ValueError, TypeError):` — parenthesized tuple.

---

## P1 — Critical Performance Issues

### 2. Agent Discovery on Every Operation
**File:** `code_muse/agents/agent_manager.py`

`_discover_agents()` is called on `get_available_agents()`, `set_current_agent()`, `load_agent()`, `get_agent_descriptions()`, `refresh_agents()`, `clone_agent()`, `delete_clone_agent()`. Each call:
- Clears the entire `_AGENT_REGISTRY`
- Re-imports all agent modules via `pkgutil.iter_modules`
- Instantiates every Python agent class
- Globs and parses every JSON agent file
- Fires plugin callbacks

**Fix:** Cache discovery results; only re-scan on explicit refresh or file change.

---

### 3. Synchronous HTTP Call Blocks Startup
**File:** `code_muse/version_checker.py`

```python
response = httpx.get(f"https://pypi.org/pypi/{package_name}/json", timeout=5.0)
```

Blocks the event loop for up to 5 seconds on every startup.

**Fix:** Use `httpx.AsyncClient` or fire-and-forget background task.

---

### 4. Eager Plugin Loading at Import Time
**File:** `code_muse/cli_runner/__init__.py:53`

```python
plugins.load_plugin_callbacks()  # Top-level, before main() runs
```

Imports ~40+ plugin modules, each pulling in heavy deps (pydantic_ai, httpx, anthropic, openai, prompt_toolkit). This is the single biggest startup cost.

**Fix:** Move inside `main()` after arg parsing; only load plugins needed for the chosen mode.

---

### 5. Double Recursive Directory Scan at Import
**File:** `code_muse/__init__.py:65-84`

```python
_rebuild_stale_cython_modules(_PACKAGE_ROOT)  # rglob("*.pyx") #1
_pyx_files = list(_PACKAGE_ROOT.rglob("*.pyx"))  # rglob("*.pyx") #2
```

Two full recursive scans of the package tree on every import.

**Fix:** Reuse the result from `_rebuild_stale_cython_modules` or scan once.

---

### 6. O(n²) Directory Deduplication in `_list_files`
**File:** `code_muse/tools/file_operations.py:~270`

```python
if not any(f.path == partial_path and f.type == "directory" for f in results):
    results.append(...)
```

For every file, for every path component, scans the entire `results` list. On a 10k-file project with depth 4, this is ~40,000 linear scans.

**Fix:** Use a `set()` to track added directory paths.

---

### 7. Redundant `stat()` Calls Per File
**File:** `code_muse/tools/file_operations.py:~240-260`

```python
if not fp.exists():       # stat #1
if fp.is_file():          # stat #2
    size = fp.stat().st_size  # stat #3
elif fp.is_dir():         # stat #4
```

3-4 syscalls per file. On 10k files, that's 30-40k unnecessary syscalls.

**Fix:** Single `fp.stat()`, then check `stat.S_ISREG(st.st_mode)`.

---

### 8. Temporary Ignore File Created Per Tool Call
**File:** `code_muse/tools/file_operations.py:~215`

Both `_list_files` and `_grep` write a ~200-line temp file on every invocation. `DIR_IGNORE_PATTERNS` is static.

**Fix:** Write once at module load (or lazily), reuse the path.

---

### 9. `should_ignore_path` is O(patterns × path_depth)
**File:** `code_muse/tools/common.py:~260`

For each path, iterates ~250 patterns. For `**` patterns (most of them), iterates all path parts creating new `Path` objects.

**Fix:** Pre-compile into a single regex or trie. Or rely on ripgrep's built-in ignore handling.

---

### 10. Message Bus Busy-Wait Polling
**File:** `code_muse/messaging/bus.py:310`

```python
async def get_message(self) -> AnyMessage:
    while True:
        try:
            return self._outgoing.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.01)  # 100 wakeups/sec
```

Burns CPU and adds 0-10ms latency to every message.

**Fix:** Use `asyncio.Queue` or `asyncio.Event` signaling.

---

## P2 — Moderate Performance Issues

### 11. Callback System Sorts on Every Trigger
**File:** `code_muse/callbacks.py`

`get_callbacks(phase)` calls `sorted()` by priority on every trigger.

**Fix:** Pre-sort at registration time.

---

### 12. Config File Stat on Every Access
**File:** `code_muse/config.py`

```python
mtime = CONFIG_FILE.stat().st_mtime  # Every get_value() call
```

**Fix:** Time-based cache invalidation (e.g., check at most once per second).

---

### 13. Model Config Fingerprint Hashes 7+ Files
**File:** `code_muse/model_factory.py`

`_models_config_fingerprint()` stats and hashes multiple files on every `load_config()` call.

**Fix:** Add cooldown period before recomputing.

---

### 14. `shutil.which("rg")` Called Every Tool Invocation
**File:** `code_muse/tools/file_operations.py:~190`

PATH search on every `_list_files` and `_grep` call.

**Fix:** Cache at module level with lazy init.

---

### 15. `_find_best_window` is O(n*m) with String Joins
**File:** `code_muse/tools/common.py:~680`

```python
for i in range(len(haystack_lines) - win_size + 1):
    window = "\n".join(haystack_lines[i : i + win_size])  # O(m) per iteration
```

990 string allocations for a 1000-line file with 10-line snippet.

**Fix:** Rolling window or pre-computed offsets.

---

### 16. `_AGENT_HISTORIES` Grows Unbounded
**File:** `code_muse/agents/agent_manager.py`

Full message history stored for every agent switch, never evicted. `ModelMessage` objects can contain large tool results.

**Fix:** Bound to N agents or evict oldest.

---

### 17. `_hash_cache` Nuclear Eviction
**File:** `code_muse/agents/_history.py:89`

```python
if len(_hash_cache) >= _HASH_CACHE_MAX:
    _hash_cache.clear()  # Drops ALL 8192 entries at once
```

Causes thundering-herd of re-computations.

**Fix:** LRU eviction or partial clear.

---

### 18. Dead Code: Double Agent Build
**File:** `code_muse/agents/_builder.py`

```python
probe_agent = _new_pydantic_agent(toolsets=[])  # Pass 1: never used
final_pydantic = _new_pydantic_agent(toolsets=final_toolsets)  # Pass 2: actual
```

The probe pass collects `_existing_tool_names` which is assigned to a local with `# noqa: F841`.

**Fix:** Remove the dead probe pass.

---

### 19. Double-Render in SynchronousInteractiveRenderer
**File:** `code_muse/messaging/renderers.py`

Messages rendered both via listener callback (on emit) AND by background polling thread.

**Fix:** Use one consumption path, not both.

---

### 20. Duplicate Messaging Systems
**Files:** `messaging/bus.py` vs `messaging/message_queue.py`

Two complete parallel messaging systems with identical features (singletons, buffering, renderer tracking, prompt correlation). Double memory usage.

**Fix:** Consolidate into one.

---

## P3 — Design Issues

### 21. Global Mutable State Everywhere
**File:** `code_muse/agents/agent_manager.py`

```python
_AGENT_REGISTRY, _AGENT_HISTORIES, _CURRENT_AGENT, _SESSION_AGENTS_CACHE
```

Makes testing difficult, creates hidden coupling.

---

### 22. Thread Safety: TOCTOU Races
**File:** `code_muse/agents/agent_manager.py`

Split lock acquisitions allow race conditions between check and use.

---

### 23. Thread Safety: Background Job Registry
**File:** `code_muse/tools/background_jobs.py`

```python
_BACKGROUND_JOBS: dict[int, BackgroundJob] = {}  # No lock, mutated from multiple threads
```

Data race in free-threaded Python 3.14.

---

### 24. `os.times()[0]` Used for Timestamps
**File:** `code_muse/tools/background_jobs.py`

Returns CPU user time, not wall-clock time. Background jobs that sleep show ~0 seconds.

**Fix:** Use `time.time()`.

---

### 25. Silent Output Truncation
**File:** `code_muse/tools/command_runner.py:~310`

```python
stdout_lines: deque[str] = deque(maxlen=256)
```

First lines silently dropped with no marker. LLM makes decisions on incomplete data.

**Fix:** Prepend `[... N lines truncated ...]`.

---

### 26. Eager Import of All SDK Clients
**File:** `code_muse/model_factory.py:1-20`

```python
from anthropic import AsyncAnthropic
from openai import AsyncAzureOpenAI
from pydantic_ai.models.anthropic import AnthropicModel
```

All providers loaded at startup even if user only uses one.

**Fix:** Lazy-import inside factory methods.

---

### 27. Eager Import of Command/TUI Modules
**File:** `code_muse/command_line/command_handler.py`

```python
import code_muse.command_line.config_commands  # noqa: F401
import code_muse.command_line.core_commands  # noqa: F401
```

Pulls in prompt_toolkit, agent_menu, model_picker at module load. Only needed when user runs specific commands.

---

### 28. `BaseMessage` UUID + datetime on Every Instantiation
**File:** `code_muse/messaging/messages.py:46`

```python
class BaseMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

High-frequency messages (ShellLineMessage during command output) generate hundreds of unused UUIDs.

**Fix:** Make `id` lazy or use a cheaper identifier for non-correlated messages.

---

### 29. Circular Import Risk
**File:** `code_muse/config.py`

Bottom-of-file re-exports from submodules create fragile import ordering.

---

### 30. Broad Exception Catching
**Multiple files**

`except Exception` with silent `continue` hides bugs throughout the codebase.

---

## Summary

| Priority | # | Issue | Effort | Impact |
|----------|---|-------|--------|--------|
| **P0** | 1 | `except X, Y` syntax bug | Low | Critical — exceptions not caught |
| **P1** | 2 | Agent discovery every operation | Medium | High — repeated FS + import work |
| **P1** | 3 | Sync HTTP blocks startup | Low | High — up to 5s delay |
| **P1** | 4 | Eager plugin loading | Medium | High — slow startup |
| **P1** | 5 | Double rglob at import | Low | Medium — startup cost |
| **P1** | 6 | O(n²) directory dedup | Low | High — slow on large repos |
| **P1** | 7 | Redundant stat calls | Low | Medium — 3-4x syscall overhead |
| **P1** | 8 | Temp file per tool call | Low | Medium — unnecessary I/O |
| **P1** | 9 | O(patterns × depth) ignore check | Medium | Medium — CPU waste |
| **P1** | 10 | MessageBus busy-wait | Medium | Medium — CPU + latency |
| **P2** | 11 | Callback sort per trigger | Low | Low-Medium |
| **P2** | 12 | Config stat per access | Low | Low-Medium |
| **P2** | 13 | Model fingerprint cost | Low | Low |
| **P2** | 14 | rg path not cached | Low | Low |
| **P2** | 15 | O(n*m) fuzzy matching | Medium | Medium on large files |
| **P2** | 16 | Unbounded agent histories | Low | Medium — memory leak |
| **P2** | 17 | Nuclear hash cache eviction | Low | Low |
| **P2** | 18 | Dead probe agent build | Low | Low — wasted init |
| **P2** | 19 | Double-render | Low | Low — wasted CPU |
| **P2** | 20 | Duplicate messaging systems | High | Medium — maintenance |
| **P3** | 21-30 | Design issues | Varies | Maintainability |

---

# Second Pass — Universal Constructor, Session Persistence, Token Systems

## P0 — Security Vulnerabilities

### 31. Signed Legacy Pickle Loaded WITHOUT Signature Verification (RCE)
**File:** `code_muse/session_storage.py:186-192`

```python
# Signed legacy pickle — safe to load without allow_legacy
if raw.startswith(_LEGACY_SIGNED_HEADER):
    pickle_data = _extract_pickle_payload(raw)
    return _unsafe_pickle_loads_for_explicit_legacy_migration_only(pickle_data)
```

The comment claims signature is verified, but `_extract_pickle_payload` just **skips** the header + 32 bytes without checking the signature value. An attacker who can write a file starting with `CPSESSION\x01` + 32 arbitrary bytes + malicious pickle payload gets arbitrary code execution **without** the user passing `--import-legacy-pickle-session`.

This contradicts the README's claim: "legacy pickle sessions are rejected unless explicitly imported."

**Fix:** Verify the HMAC signature before deserialization, or refuse to load any pickle without the explicit flag.

---

### 32. Universal Constructor AST Safety Checks Are Trivially Bypassable
**File:** `code_muse/plugins/universal_constructor/safety.py:178-228`

```python
def _get_call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    elif isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""
```

Bypasses:
```python
# All bypass the AST checks:
__builtins__.__dict__['__import__']('subprocess').run([...])
getattr(os, 'system')('rm -rf /')
exec('import subprocess; subprocess.run(...)')  # via decorator
```

The check only inspects one level of attribute access. String-based dynamic imports, `getattr` indirection, decorator-based execution, and metaclass abuse are all invisible.

**Fix:** AST-based safety is fundamentally insufficient for untrusted code. Need real sandboxing (seccomp, namespace isolation) or remove the feature.

---

### 33. UC Module Imports Execute Arbitrary Code at Scan Time
**File:** `code_muse/plugins/universal_constructor/registry.py:148-160`

```python
spec.loader.exec_module(module)  # Runs ALL top-level code
```

Combined with bypassable safety checks (#32), placing a malicious file in `~/.muse/plugins/universal_constructor/` triggers code execution on the next `scan()` — which happens at **startup** via `register_callbacks.py:28`.

**Fix:** Defer module imports until the tool is actually invoked, with the user explicitly approving each new tool.

---

### 34. UC Cloudpickle Fallback Is an RCE Vector
**File:** `code_muse/plugins/universal_constructor/runner.py:237-280`

```python
wrapper_code = f"""
import cloudpickle, json, sys, traceback
with open({repr(pickle_path)}, "rb") as f:
    func = cloudpickle.load(f)
"""
```

Pickle deserialization is arbitrary code execution. The README explicitly claims "JSON-only serialization" but this code path uses pickle. Combined with the temp-file TOCTOU (#36), an attacker who can win the race window gets RCE.

**Fix:** Remove the cloudpickle fallback entirely or gate it behind an explicit opt-in.

---

### 35. UC Subprocess Has No Real Sandboxing
**File:** `code_muse/plugins/universal_constructor/runner.py:72-108`

The subprocess inherits the full parent environment (API keys, tokens) with no:
- chroot/jail
- seccomp filters
- network namespace isolation
- filesystem restrictions
- `setrlimit` (memory, CPU, file descriptors)

A "blocked" tool that bypasses #32 has full access to the user's shell environment, secrets, and network.

**Fix:** Use `setrlimit` for resource caps at minimum; ideally run in a container or namespace.

---

### 36. UC Temp File TOCTOU
**File:** `code_muse/plugins/universal_constructor/runner.py:148-163`

Files are created and closed before subprocess opens them. Symlink attack window on `/tmp` allows a malicious local process to replace `result_file` with attacker-controlled JSON, faking tool results.

**Fix:** Use `tempfile.mkdtemp()` with restrictive perms and pass the directory; or use pipes instead of files.

---

### 37. UC Approval Store Has No Integrity Protection
**File:** `code_muse/plugins/universal_constructor/safety.py:252-280`

`~/.local/state/code_muse/uc_approvals.json` is plain JSON. Any process running as the user can modify it to pre-approve malicious tools.

**Fix:** HMAC-sign approval entries with a key derived from machine ID or user keychain.

---

## P0 — Correctness Bugs

### 38. UC InterpreterPool Path Has File-Deleted-Before-Read Bug
**File:** `code_muse/plugins/universal_constructor/runner.py:186-192`

```python
finally:
    for p in (result_path, stdout_path, stderr_path):
        with contextlib.suppress(OSError):
            os.unlink(p)
# Falls through to:
try:
    with open(result_path, encoding="utf-8") as f:  # ALREADY DELETED
```

The `finally` deletes temp files, then the code tries to read them. This path always fails with "Failed to read tool result."

**Fix:** Read result before unlinking, or move unlinks to outer try/finally.

---

### 39. More Python 2 `except X, Y:` Syntax (Additional Locations)

Beyond what was found in the first pass:
- `code_muse/session_storage.py:95` — `except UnicodeDecodeError, ValueError:`
- `code_muse/session_storage.py:430` — `except KeyboardInterrupt, EOFError:`
- `code_muse/plugins/universal_constructor/safety.py:109`
- `code_muse/plugins/universal_constructor/registry.py:137`
- `code_muse/plugins/universal_constructor/registry.py:163`

In Python 3, `EOFError`, `ValueError`, and `OSError` are **never caught** at these sites because the syntax binds the second name as a variable.

---

### 40. `cleanup_sessions()` Defined but Never Called
**File:** `code_muse/session_storage.py:339`

The function exists but `grep` shows zero call sites. Autosave sessions accumulate **indefinitely** on disk, with no rotation or pruning.

**Fix:** Wire it into shutdown or schedule periodically.

---

## P1 — Performance Issues

### 41. Sync I/O Blocking Async Event Loop on Every Autosave
**Files:** `code_muse/session_storage.py:227-285`, `code_muse/cli_runner/loop.py:400`

```python
async def _render_and_autosave(...):
    _render_response(...)
    await asyncio.sleep(0.1)
    auto_save_session_if_enabled()  # Sync I/O — writes 3 files
```

`save_session()` is fully synchronous: `json.dump` + `_atomic_write_json` writing `.json`, `.pkl`, and `_meta.json`. Called from async context after every agent response. For 500-message sessions, this can stall the UI.

**Fix:** Use `aiofiles` (already imported elsewhere) or `asyncio.to_thread`.

---

### 42. Full Session Rewrite on Every Autosave
**File:** `code_muse/session_storage.py:244-249`

Every autosave re-serializes and writes the **entire** message history to 3 files. There is no incremental/append strategy. For long sessions this becomes expensive on every turn.

**Fix:** Append-only JSONL format, or write deltas with periodic compaction.

---

### 43. SQLite Commit on Every Tool Call (WAL fsync per edit)
**File:** `code_muse/plugins/token_tracking/database.py:130-155`

Every `replace_in_file`, `create_file`, `delete_snippet` and every shell command triggers `INSERT` + `commit()` inline in `_on_post_tool_call`. Each commit forces a WAL fsync (~1-5ms on macOS). The agent blocks on this on the critical path.

**Fix:**
1. Add `PRAGMA synchronous=NORMAL` (safe with WAL, ~50% fsync reduction)
2. Add `PRAGMA busy_timeout=5000`
3. Batch inserts — accumulate and flush every N seconds in a background task

---

### 44. UC Subprocess Spawn ~200-300ms Per Call
**File:** `code_muse/plugins/universal_constructor/runner.py:175-180`

```python
ctx = multiprocessing.get_context("spawn")
process = ctx.Process(target=_run_in_subprocess, ...)
process.start()
```

`spawn` reimports everything. No process pool, no worker reuse. For tools called in a loop, this is devastating.

**Fix:** Worker pool with persistent processes; reload modules selectively.

---

## P2 — Moderate Issues

### 45. No `fsync` in `_atomic_write_json`
**File:** `code_muse/session_storage.py:148-152`

```python
def _atomic_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)  # No fsync — power loss = empty/partial file
```

Codebase has a correct pattern in `secret_storage.py` but session storage doesn't use it.

---

### 46. `_write_state()` Is NOT Atomic
**File:** `code_muse/plugins/autonomous_memory/session_scanner.py:72-75`

```python
with state_file.open("w") as fh:
    json.dump(data, fh, indent=2)  # Crash mid-write = permanent corruption
```

No temp file, no rename, no fsync.

---

### 47. State File `processed` List Grows Unbounded
**File:** `code_muse/plugins/autonomous_memory/session_scanner.py`

The `processed` list in `.memory_state.json` only ever appends. Sessions deleted from disk leave stale entries forever. Reads slow down over months.

---

### 48. No Compression on Session Files

Sessions stored as pretty-printed JSON (`indent=2`). Tool outputs can push individual sessions to 5-20MB. No gzip/zstd. The class named `InMemoryCompressedHistoryStore` is misleading — it stores raw Python objects, no compression.

---

### 49. Linear Scan to Count Messages
**File:** `code_muse/plugins/autonomous_memory/session_scanner.py:46-54`

```python
return sum(1 for line in fh if '"role": "user"' in line or '"role":"user"' in line)
```

Reads every byte of every session file on every scan. No caching of counts, no index.

---

### 50. Eager Module Import for All UC Tools at Scan
**File:** `code_muse/plugins/universal_constructor/registry.py:130-145`

If a user has 50 tools, all 50 get imported at startup, even if none are called.

**Fix:** Lazy import on first invocation.

---

### 51. UC Registry Singleton Has Race Condition
**File:** `code_muse/plugins/universal_constructor/registry.py:268-278`

```python
_registry: UCRegistry | None = None

def get_registry() -> UCRegistry:
    global _registry
    if _registry is None:        # Race window
        _registry = UCRegistry()
    return _registry
```

No lock — concurrent first calls can create multiple instances.

---

### 52. `sys.modules` Pollution

UC loaded modules use `hash()`-based names injected into `sys.modules` and never cleaned up. Names are non-deterministic, so stale entries can't be identified later.

---

## P3 — Design Issues

### 53. Duplicate Safety Logic in UC

`sandbox.py` (advisory) and `safety.py` (blocking) both define `DANGEROUS_IMPORTS`/`DANGEROUS_CALLS` with different sets and semantics. Drift risk; ambiguous which is authoritative.

---

### 54. No Resource Limits on UC Subprocess

Wall-clock timeout exists, but no memory/CPU/FD/disk limits. A malicious tool can DoS the system via OOM or CPU exhaustion before the timeout fires.

---

### 55. Dead Code: `detect_cache_breakpoint`
**File:** `code_muse/plugins/token_caching/cacheable_prefix_detection.py`

Exported from `__init__.py` but `grep` shows zero call sites. Misleading — suggests caching optimization that doesn't exist; actual cache control is handled in the API client.

---

### 56. Misleading Token-Savings Story

The README's "60-90% token savings" refers to **shell output compression** in `filter_engine`/`shell_minimizer` plugins. The `token_tracking` plugin merely **records** those savings after the fact, **adding overhead** (per-command DB writes). The `token_caching` plugin tracks Anthropic prompt-cache hit rates — a different feature. The naming creates confusion about which module produces the savings.

---

### 57. `find_available_port` Sequential Scan of 920 Ports
**File:** `code_muse/http_utils.py:352-363`

In the worst case, creates/destroys 920 sockets sequentially. Wrapped in `to_thread`, but wasteful design. Doesn't run if `-p` mode is used either way (per finding #10 above).

---

## Updated Summary

**Total findings: 57**

**Most critical (immediate action):**

| # | Issue | Why |
|---|-------|-----|
| 31 | Signed pickle without signature verification | RCE on session load |
| 32-35 | UC sandbox is bypassable | RCE on tool registration |
| 1, 39 | `except X, Y:` syntax across the codebase | Silent uncaught exceptions |
| 38 | UC InterpreterPool reads deleted files | Path always fails |
| 40 | `cleanup_sessions()` never called | Unbounded disk growth |

**Biggest performance wins:**

| # | Issue | Win |
|---|-------|-----|
| 4 | Move plugin loading to after arg parse | Massive startup speedup |
| 3 | Async version check | Up to 5s saved on startup |
| 2 | Cache agent discovery | 10x+ on agent operations |
| 41-42 | Async + incremental session save | Eliminates per-turn UI lag |
| 43 | Batch SQLite writes + WAL pragmas | Removes fsync from hot path |
| 6 | Use set for dir dedup | O(n²) → O(n) on file listing |

---

# Third Pass — Filter Engine, Autonomous Memory, Pydantic Integration

## P0 — Security

### 58. Secret Scanner Warns But Does NOT Block Memory Writes
**File:** `code_muse/plugins/autonomous_memory/register_callbacks.py:133-136`

```python
if secrets:
    logger.warning(f"Secrets detected in consolidated memory: {secret_names}")
# Memory file is still written with secrets included
```

Detected secrets (API keys, tokens, JWTs) are logged but the write proceeds. Memory files are injected into every future system prompt.

**Fix:** Block the write and surface the error to the user.

---

## P1 — Performance

### 59. Dead Probe Pass in Agent Builder
**File:** `code_muse/agents/_builder.py:119-148`

```python
probe_agent = _new_pydantic_agent(toolsets=[])
register_tools_for_agent(probe_agent, ...)
_existing_tool_names: set[str] = set(...)  # noqa: F841  ← never used
# Pass 2: identical build
final_pydantic = _new_pydantic_agent(toolsets=[])
register_tools_for_agent(final_pydantic, ...)
```

`_existing_tool_names` is suppressed with `# noqa: F841`. The probe agent is fully constructed and discarded. Every agent build pays double initialization cost.

**Fix:** Remove the probe pass entirely.

---

### 60. Two Async Wrapper Layers on Every Tool Call
**File:** `code_muse/pydantic_patches.py`

`patch_tool_call_json_repair` and `patch_tool_call_callbacks` both wrap `ToolManager._call_tool` independently. Call chain: `callbacks_wrapper → json_repair_wrapper → real_call_tool`. Every tool invocation goes through two try/except async wrappers plus `json_repair.repair_json()` even when JSON is valid.

**Fix:** Merge both patches into a single wrapper.

---

### 61. History Processor Runs 4 Full Passes Per Compaction
**File:** `code_muse/agents/_compaction.py`

During compaction: `sum_tokens()` → `filter_huge_messages()` → `_truncate_tool_result_content()` → `split_for_protected_summarization()` — four separate O(n) iterations over the full message list. The `CompactionCache` reduces recomputation but not iteration count.

**Fix:** Combine into a single annotating pass.

---

### 62. Sync File I/O on Every System Prompt Assembly
**File:** `code_muse/plugins/autonomous_memory/memory_injection.py:30-42`

`load_memory_injection()` calls `Path.exists()` + `Path.stat()` + `Path.read_text()` synchronously on every `get_model_system_prompt` callback — i.e., every agent turn.

**Fix:** Cache the file content with mtime-based invalidation (same pattern as `config.py`).

---

### 63. `strip_lines_regex` / `keep_lines_regex` Recompile Patterns Per Call
**File:** `code_muse/plugins/shell_minimizer/primitives.py:130-158`

```python
def strip_lines_regex(input: str, patterns: list[str]) -> str:
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]  # Every call
```

The pipeline compiler already has the pattern strings at compile time. Python's `re` LRU cache (512 entries) partially mitigates this, but the `re.compile()` call overhead remains.

**Fix:** Accept `list[re.Pattern]` instead of `list[str]`; compile in `compile_pipeline()`.

---

### 64. Tree-Sitter Parser Objects Not Cached
**File:** `code_muse/plugins/filter_engine/strategies/ast_parser.py:95-130`

```python
parser = tree_sitter.Parser(language_obj)  # New object per parse
tree = parser.parse(source.encode("utf-8"))
```

`Language` and `Parser` objects are created fresh on every code compression call. For repeated calls on the same language, this is wasteful.

**Fix:** Cache `{language: Parser}` at module level.

---

### 65. Filter Engine Classifier: Up to 90 Regex Checks for Unknown Commands
**File:** `code_muse/plugins/filter_engine/classifier.py`

Unknown commands fall through all ~90 pre-compiled patterns before returning `"unknown"`. Most commands are known (git, pytest, etc.) and short-circuit early, but custom/unusual commands pay the full cost.

**Fix:** First-token prefix dispatch (`{"git": git_category, "pytest": test_category, ...}`) before regex fallback.

---

### 66. `_compress_segment` Applies 36+ Sequential Regex Substitutions
**File:** `code_muse/plugins/semantic_compression/compressor.py:200-240`

Each substitution creates a new string. For large text segments this is 36+ allocations. Semantic compression is opt-in, but when enabled it runs on every tool result.

**Fix:** Combine related patterns into alternation groups where semantics allow.

---

## P2 — Moderate Issues

### 67. `patch_message_history_cleaning` Disables All History Validation
**File:** `code_muse/pydantic_patches.py`

```python
# Replaces pydantic-ai's _clean_message_history with identity
monkeypatch(_agent_graph, "_clean_message_history", lambda messages: messages)
```

Silently passes malformed history through. Any structural corruption in `_message_history` will reach the API without validation.

---

### 68. No Insertion-Time Size Cap on Tool Results
**File:** `code_muse/agents/_compaction.py`

Tool results are kept in full until compaction fires (threshold-based). A single tool result returning 100k+ characters sits in memory until 7+ subsequent tool calls push it out of the recent window. Compaction only truncates old results, not new ones at insertion.

**Fix:** Cap tool result content at insertion time (e.g., 50k chars), not only during compaction.

---

### 69. `_compacted_message_hashes` Set Grows Unboundedly
**File:** `code_muse/agents/base_agent.py` (or `_compaction.py`)

Every compacted message's hash (int) is retained forever in `_compacted_message_hashes` to prevent re-insertion. For very long sessions this accumulates thousands of entries. Each is 28 bytes in CPython — minor but unbounded.

---

### 70. Lease Lock Has TOCTOU Race
**File:** `code_muse/plugins/autonomous_memory/lease_lock.py:52-70`

```python
if lock_path.exists():
    lock_path.unlink()
# Race window here
with lock_path.open("w") as fh:  # Not O_EXCL
    json.dump(...)
```

Two concurrent processes can both break a stale lock and both write their lease. Low severity in practice (manual-only path), but the fix is trivial.

**Fix:** Use `open(lock_path, "x")` (exclusive create) which is atomic on POSIX.

---

### 71. Secret Scanner OpenAI Regex Is Outdated
**File:** `code_muse/plugins/autonomous_memory/secret_scanner.py:18`

```python
"openai_api_key": r"sk-[0-9a-zA-Z]{48}"
```

OpenAI now issues `sk-proj-...` keys with variable length. Current regex misses all project-scoped keys.

---

### 72. Unbounded `processed` List in Memory State File
**File:** `code_muse/plugins/autonomous_memory/session_scanner.py:67`

The `processed` list in `.memory_state.json` only appends. Sessions deleted from disk leave stale entries forever. After months of use, state file reads slow down.

**Fix:** Prune entries for paths that no longer exist on disk during each scan.

---

### 73. No Cap on Session Transcript Size Before BM25 Chunking
**File:** `code_muse/plugins/autonomous_memory/extraction.py:215`

For a session with thousands of messages, the full transcript string and all chunks are held in memory simultaneously during extraction. No size guard before chunking.

---

## P3 — Design Issues

### 74. `pydantic_patches.py` Applied Before Any pydantic-ai Import
**File:** `code_muse/cli_runner/__init__.py:6-8`

Patches are applied at module import time, before `main()` runs. Any import of `cli_runner` (e.g., in tests) silently mutates pydantic-ai's internals. Makes testing and debugging harder.

**Fix:** Apply patches lazily inside `main()` or gate behind a flag.

---

### 75. History Processor Registered via pydantic-ai `history_processors` But Also Called Manually
**File:** `code_muse/agents/_builder.py` + `_runtime.py`

The history processor is both registered in pydantic-ai's pipeline AND called explicitly in `_runtime.py` before/after runs (finding #7 from pass 1 — double `prune_interrupted_tool_calls`). This dual-registration creates ambiguity about when processing actually occurs.

---

### 76. Semantic Compression Runs on Tool Results, Not Just Shell Output
**File:** `code_muse/plugins/semantic_compression/register_callbacks.py`

The `post_tool_call` hook compresses ALL tool results when enabled, including structured data (JSON, file contents) where removing articles/copulas corrupts meaning. The `_looks_already_compressed` heuristic is a weak guard.

---

## Updated Total: 76 Findings

**New critical items from this pass:**
- **#58** — Secret scanner doesn't block writes (secrets end up in every future system prompt)
- **#59** — Dead probe pass (double agent construction on every build)
- **#60** — Double async wrapper on every tool call
- **#67** — History validation disabled globally via monkeypatch

**Biggest remaining quick wins:**
- Remove probe pass (#59) — 1 line delete
- Merge pydantic patches (#60) — reduces tool call overhead
- Cache memory injection file (#62) — eliminates 3 syscalls per agent turn
- Fix secret scanner to block writes (#58) — security fix
- Pre-compile patterns in pipeline compiler (#63) — eliminates per-call `re.compile`
