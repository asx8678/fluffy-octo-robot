# MUSE Code Review — Verified Findings

Reviewer: Kiro CLI
Date: 2026-05-13
Scope: `code_muse/` package, full repo tests, `pyproject.toml`

All findings below were verified by running code or tests against the live
codebase (Python 3.14, repository at HEAD `main`). Each finding lists the
evidence that confirms it.

---

## Severity legend
- **HIGH**: real runtime bug or measurable performance issue on hot path
- **MEDIUM**: latent risk, code-quality regression, or test-suite breakage
- **LOW**: style/clarity issues, false-positive lint noise

---

## HIGH — Confirmed runtime bugs

### H1. `resolve_env_var_in_header` is broken (silent failure)
**File:** `code_muse/http_utils.py:290–303`

```python
def resolve_env_var_in_header(headers: dict[str, str]) -> dict[str, str]:
    resolved_headers = {}
    for key, value in headers.items():
        if isinstance(value, str):
            try:
                expanded = Path(value).expandvars()   # ← does not exist
                resolved_headers[key] = expanded
            except Exception:
                resolved_headers[key] = value
        ...
```

`pathlib.Path` has no `expandvars()` method (that's `os.path.expandvars`).
The call raises `AttributeError`, which is swallowed by the broad
`except Exception` and the function silently returns the unresolved value.

**Verification:**
```
$ python -c "from pathlib import Path; Path('x').expandvars()"
AttributeError: 'PosixPath' object has no attribute 'expandvars'

$ pytest tests/test_http_utils_full_coverage.py::TestResolveEnvVarInHeader::test_resolves_env_vars
FAILED — assert 'Bearer $MY_KEY' == 'Bearer secret'
```

**Impact:** Any header value containing `$VAR` is passed through literally
instead of being expanded. Currently only test-coverage call sites are
affected, but the function is exported and may be wired up later.

**Fix:** Replace `Path(value).expandvars()` with `os.path.expandvars(value)`.

---

### H2. Streaming hot path: ~220× slowdown when `frontend_emitter` is loaded
**Files:**
- `code_muse/callbacks.py:314–349` (`_trigger_callbacks_sync`)
- `code_muse/agents/event_stream_handler.py:44–46, 249` (per-event fire)
- `code_muse/plugins/frontend_emitter/register_callbacks.py:75` (async hook)

For every `PartDeltaEvent` (every streamed token), the agent fires
`_fire_stream_event_sync("part_delta", ...)`. That invokes
`_trigger_callbacks_sync`, which iterates registered callbacks. When a
callback returns a coroutine *and* the caller is in an async context,
the trigger does:

```python
future = _executor.submit(asyncio.run, result)
result = future.result(timeout=None)   # blocks main loop, no timeout
```

The builtin plugin `frontend_emitter` registers an `async def on_stream_event`
hook, so this path executes on every chunk by default.

**Verification (live measured):**
```
1000 events, no callback         :    0.3 ms (0.28 µs/ev)
1000 events, sync callback       :    0.5 ms (0.53 µs/ev)
1000 events, async callback      :  118.1 ms (118.07 µs/ev)
Async vs sync overhead per event :  117.55 µs

builtin plugins loaded: 43
frontend_emitter loaded? True
stream_event callbacks (2):
  code_muse.plugins.tps_meter.register_callbacks._on_stream_event   (sync)
  code_muse.plugins.frontend_emitter.register_callbacks.on_stream_event  (async)
```

**Mechanism (corrected from my first draft):** the `ThreadPoolExecutor`
reuses a worker — it is **not** a thread spawn per event. The dominant
cost is `asyncio.run()` per event, which creates and tears down a fresh
event loop each time.

**Impact:** ~220× per-event overhead vs sync. For a 300-chunk response
that's ~35 ms of pure overhead; for a 5000-chunk reasoning trace it's
~600 ms. Worse, `future.result(timeout=None)` means a slow or hanging
plugin freezes the main event loop indefinitely.

**Fixes (any one):**
1. Convert `frontend_emitter.on_stream_event` to sync (the body does no
   awaiting — it just calls `emit_event` which is sync `put_nowait`).
2. For the `stream_event` phase, use `loop.create_task(coro)` on the
   running loop and don't wait — these hooks are fire-and-forget anyway.
3. Add a non-`None` timeout to `future.result()` so a misbehaving hook
   cannot freeze the session.

---

## MEDIUM — Test-suite regression

### M1. At least 10 unit tests fail on `main`
Verified by per-directory pytest runs:

| Suite | Result |
|---|---|
| `tests/agents/` + `tests/test_http_utils_full_coverage.py` | **4 failed / 501 passed** |
| `tests/tools/` | **2 failed / 1313 passed** |
| `tests/messaging/` | ≥ 4 visible failures (full count blocked by test hangs in `test_subagent_console.py`) |

Confirmed failing tests:
- `tests/test_http_utils_full_coverage.py::TestResolveEnvVarInHeader::test_resolves_env_vars` (caused by H1)
- `tests/agents/test_base_agent_configuration.py::TestMuseDynamicPrompt::test_non_reasoning_sections_unchanged`
  → assertion: `Missing prompt section: agent_run_shell_command`
- `tests/agents/test_compaction.py::TestMakeHistoryProcessor::test_triggers_compaction_over_threshold`
  → assertion: `system message preserved through compaction`
- `tests/agents/test_streaming_retry.py::TestModelAllowsStreaming::test_crof_kimi_disables_streaming`
  → assertion: `assert True is False` (model name `crof-kimi-k2.5-lightning`)
- `tests/tools/test_display.py::TestDisplayNonStreamedResult::test_console_file_attribute_used`
- `tests/tools/test_display.py::TestDisplayNonStreamedResult::test_basic_display_with_provided_console`

**Impact:** CI green-lights regressions. The `agent_creator_agent` test
also fails when run after certain other tests but passes in isolation —
order-dependent test pollution.

**Fix:** triage and either correct the assertions or fix the underlying
behavior. Gate CI so `main` cannot be merged red.

---

### M2. Ruff config blinds the linter to real issues
**File:** `pyproject.toml`

```toml
requires-python = ">=3.14,<3.16"
[tool.ruff]
target-version = "py313"     # ← mismatch
```

Ruff parses the codebase as Python 3.13. The codebase legitimately uses
PEP 758 unparenthesized multi-exception clauses (`except A, B:`) and
PEP 649 lazy annotation evaluation. Result: **13 false-positive
`invalid-syntax` errors and 20 false-positive `F821 undefined-name`
errors** out of 33 ruff "real bugs" reported.

**Verification:** all 8 modules I sampled (incl. `reopenable_async_client`,
`messaging.subagent_console`, `motion`, `gemini_code_assist`,
`plugins.azure_foundry.token`, `plugins.filter_engine.dispatcher`,
`tools.browser.browser_manager`, `tools.ask_user_question.models`)
import cleanly under Python 3.14.

**Impact:** linter output is 95%+ noise → real issues get drowned.

**Fix:** set `target-version = "py314"`.

---

### M3. AGENTS.md 600-line cap is widely violated
**Top offenders (34 files exceed the cap):**

| Lines | File | Cap ratio |
|---|---|---|
| 1552 | `code_muse/plugins/mindpack/mindpack_menu.py` | 2.6× |
| 1407 | `code_muse/tools/common.py` | 2.3× |
| 1403 | `code_muse/tools/command_runner.py` | 2.3× |
| 1331 | `code_muse/command_line/add_model_menu.py` | 2.2× |
| 1203 | `code_muse/model_factory.py` | 2.0× |
| 1171 | `code_muse/config.py` | 2.0× |
| 1156 | `code_muse/messaging/rich_renderer.py` | 1.9× |
| 1099 | `code_muse/tools/file_modifications.py` | 1.8× |
| 1073 | `code_muse/callbacks.py` | 1.8× |
| 1068 | `code_muse/tools/chrome_cdp/__init__.py` | 1.8× |
| (24 more between 600 and 983 lines) | | |

The project's own `AGENTS.md` declares a 600-line **hard cap** with
"split into submodules" guidance. None of the files above were split.

---

### M4. 668 broad `except Exception:` clauses across 163 files
Confirmed via `grep -rn 'except Exception' code_muse/ | wc -l → 668`.
Top offenders:
- `tools/chrome_cdp/__init__.py` (21)
- `claude_cache_client.py` (21)
- `tools/command_runner.py` (20)

Combined with `logger.debug(...)` swallows (as in H1), real bugs are
easily masked. `resolve_env_var_in_header` is a textbook case.

**Recommendation:** narrow the catches to specific exceptions; promote
debug logs to warnings where the swallowed error indicates a programming
bug.

---

### M5. Pydantic-AI deprecation: `retries=` will be removed in v2
**File:** `code_muse/agents/_builder.py:183–187`

```python
return PydanticAgent(
    ...
    retries=3,
)
```

Test output captures the deprecation warning:
> `DeprecationWarning: 'retries' is deprecated and will be removed in v2.
> Use 'tool_retries' instead. Note: in v2, retries will no longer also
> set output_retries as a fallback — pass output_retries explicitly`.

**Fix:** migrate to `tool_retries=3` (and `output_retries=` if needed)
before pydantic-ai v2 lands.

---

## LOW — Style / clarity / minor perf

### L1. `get_cert_bundle_path` falls off without explicit return
**File:** `code_muse/http_utils.py:207–211`

```python
def get_cert_bundle_path() -> str | None:
    ssl_cert_file = os.environ.get("SSL_CERT_FILE")
    if ssl_cert_file and Path(ssl_cert_file).exists():
        return ssl_cert_file
    # implicit None
```

Functionally correct (Python returns `None` implicitly), but readers
can't tell from a glance. Add `return None` for clarity.
**Correction from earlier draft:** I previously called this a "real bug" —
it is not. Style only.

---

### L2. Sparse caching of repeatedly-read values
Only 2 files use `@lru_cache` / `@cache`:
- `code_muse/pydantic_patches.py`
- `code_muse/uvx_detection.py`

`config.py` has its own bespoke cache (good — `_get_cached_config`),
`model_factory.py` has its own. But many small config getters
(`get_http2()`, `get_subagent_verbose()`, `get_banner_color()`, etc.)
call `_get_cached_config()` per invocation, which in turn does a
`stat()` syscall on `~/.muse/muse.cfg`. On streaming hot paths this is
~1 syscall per chunk. Not catastrophic, but consider:
- Memoize the small getters per-process and invalidate on `set_config_value`.

---

### L3. `_clean_stale_pycache` runs an `rglob("*.py")` on every `load_plugin_callbacks()` call
**File:** `code_muse/plugins/__init__.py:480–482`

The walk runs **before** the `_PLUGINS_LOADED` short-circuit. In normal
operation the function is called once per process, so this is a startup
cost only. Still worth deferring to "only when an `ImportError` is
observed" or making it lazy.
**Correction from earlier draft:** I implied "every plugin load" — in
practice it's once per process startup.

---

### L4. `RuntimeWarning: coroutine 'on_stream_event' was never awaited`
**File:** `code_muse/agents/event_stream_handler.py:61` and
`tests/agents/test_agents_remaining_coverage.py`

The `except Exception as e: logger.debug(...)` path silently drops a
coroutine returned by a buggy callback. Symptom of H2's design seam:
the `stream_event` hook accepts both sync and async signatures and the
plumbing has to do non-trivial work to bridge them — and sometimes
fails to.

---

## Recommendations — priority order

1. **Fix H1** (one-line change to `os.path.expandvars`).
2. **Fix H2**: convert `frontend_emitter.on_stream_event` to sync and
   add a non-`None` timeout to `future.result()` in
   `_trigger_callbacks_sync` so plugins can never freeze the session.
3. **Set `target-version = "py314"`** in `pyproject.toml` so the linter
   becomes signal again.
4. **Fix or update the failing tests** and gate CI on a green suite.
5. **Migrate `retries=`** → `tool_retries=` in `agents/_builder.py`.
6. **Plan refactor** of the 34 files exceeding the 600-line cap per the
   project's own AGENTS.md rule.
7. **Audit broad `except Exception` clauses**, especially around silent
   `logger.debug(...)` swallows.

---

## Appendix — verification commands

```bash
# H1
.venv/bin/python -m pytest tests/test_http_utils_full_coverage.py::TestResolveEnvVarInHeader -x

# H2 — measured live with a synthetic async callback
.venv/bin/python -c "
import asyncio, time, threading
from code_muse import callbacks
from code_muse.callbacks import register_callback, on_stream_event_sync, _callbacks

async def main():
    _callbacks['stream_event'].clear()
    async def cb(*a, **k): pass
    register_callback('stream_event', cb)
    t0 = time.perf_counter()
    for i in range(1000):
        on_stream_event_sync('part_delta', {'index': i})
    print(f'{(time.perf_counter()-t0)*1000:.1f} ms')
asyncio.run(main())
"

# M1 — failing tests in agents/http_utils
.venv/bin/python -m pytest tests/agents tests/test_http_utils_full_coverage.py --tb=no -q

# M3 — files over cap
find code_muse -name '*.py' -exec wc -l {} + | awk '$1 > 600 && $2 != "total"' | wc -l

# M4 — broad excepts
grep -rn 'except Exception' code_muse --include='*.py' | wc -l
```
