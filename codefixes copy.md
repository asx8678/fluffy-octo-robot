# Code Quality Report

**Generated:** 2026-05-14
**Reviewer:** CodeCritic (senior staff engineer review)
**Scope:** `code-muse` v0.1.37 — Python 3.14+ AI coding agent CLI
**Files Reviewed (key files):**
- `pyproject.toml`, `build_extensions.py`
- `code_muse/main.py`, `code_muse/__main__.py`, `code_muse/__init__.py`
- `code_muse/cli_runner/__init__.py`, `code_muse/cli_runner/args.py`
- `code_muse/callbacks.py`, `code_muse/plugins/__init__.py`
- `code_muse/secret_storage.py`, `code_muse/security/redaction.pyx`
- `code_muse/http_utils.py`, `code_muse/session_storage.py`
- `code_muse/version_checker.py`, `code_muse/round_robin_model.py`
- `code_muse/model_factory.py` (partial)
- `code_muse/agents/agent_manager.py` (partial)
- `code_muse/tools/command_runner.py` (partial)
- `code_muse/tools/file_modifications.py` (partial)
- `code_muse/plugins/code_critic/*` (full)
- `code_muse/plugins/build_filter/strategies/build.py`

> NOTE: This codebase is large (~40+ plugins, hundreds of files). The review
> focused on the entry points, callback/plugin core, security boundaries,
> recently-modified files, and the new `code_critic` plugin. There is more
> to find in the long tail (~80+ tests, every plugin, ~50KB tools files);
> a follow-up pass is warranted.

---

## Executive Summary

Overall health is **mixed**. The architecture is thoughtful — atomic
deferred plugin registration, structured messaging, content-hash plugin
trust, Cython-based redaction, careful subprocess containment — and the
test suite is broad. However, several **CRITICAL** runtime bugs slipped
into recently-modified hot paths (verbose CLI flag, deprecated pydantic-ai
API, tuple-as-union type, unformatted prompt placeholder, broken build
filter strategy), at least one **HIGH** security issue (silent TLS bypass),
and a number of correctness/maintainability problems.

**Issues by severity:** 5 Critical · 9 High · 12 Medium · 11 Low

---

## Critical Issues (Must Fix Now)

| # | File | Line | Category | Issue | Fix |
|---|------|------|----------|-------|-----|
| C1 | `code_muse/cli_runner/__init__.py` | ~63–72 | Bug | `args.verbose` branch references `VerbosityLevel` and `set_verbosity` but neither is imported or even defined anywhere in the package — `--verbose` raises `NameError` at runtime. The `args.ultra_compact` branch only executes `pass`. | Either delete both branches or import the (apparently removed) verbosity API. Wire `--verbose` to actual logging level changes (e.g. `logging.getLogger('code_muse').setLevel(...)`); same for `--ultra-compact`. |
| C2 | `code_muse/plugins/build_filter/strategies/build.py` | 17, 52, 60, 69, 111, 144, 153, 179 | Bug | Function signatures use `verbosity: VerbosityLevel` and bodies reference `VerbosityLevel.VERBOSE` / `VerbosityLevel.VERY_VERBOSE`, but `VerbosityLevel` is never imported. Every call to `compress_make`/`compress_cargo`/etc. raises `NameError`. | Import the enum (`from code_muse.X import VerbosityLevel`) once it actually exists, or replace with a local IntEnum and pass it through from `command_runner`. |
| C3 | `code_muse/tools/file_modifications.py` | 152, 673, 826 | Bug / Type | `EditFilePayload = DeleteSnippetPayload, ReplacementsPayload, ContentPayload` creates a **tuple of three classes**, not a union. It is then used as a type annotation (`payload: EditFilePayload`, `payload: EditFilePayload \| str`). pydantic-ai will fail to derive a JSON schema (or build a nonsense one) and any `isinstance()`-style downstream check that expects a union type will be wrong. | Change to `EditFilePayload = DeleteSnippetPayload \| ReplacementsPayload \| ContentPayload`. The comment in `gemini_schema.py:17` confirms a discriminated union was intended. |
| C4 | `code_muse/plugins/code_critic/critic_agent.py` | 33 | Bug | `get_system_prompt()` returns a string containing the literal placeholder `Your ID is \`code-critic-{id_suffix}\`.` — `.format(id_suffix=...)` is never called, so the model literally sees `{id_suffix}`. | Either compute and substitute a real suffix (e.g. uuid4 hex) before returning, or remove the placeholder entirely. |
| C5 | `code_muse/plugins/code_critic/reviewer.py` | 118 | Bug / API | `text = result.data if hasattr(result, "data") else str(result)` — pydantic-ai 1.x (project pins `pydantic-ai-slim>=1.93.0`) replaced `AgentRunResult.data` with `.output`. The rest of the codebase already uses `.output` (`cli_runner/runner.py`, `agents/_runtime.py`, `tools/agent_tools.py`, `plugins/plan_command/...`). When `data` is missing, the fallback `str(result)` returns a `repr`-style string, NOT the model output, so JSON parsing always fails and every review returns the heuristic/`flagged` fallback. Same bug at `code_muse/plugins/auto_review/reviewer.py:167`. | Replace with `text = getattr(result, "output", None) or getattr(result, "data", None) or str(result)`, or simply `text = result.output`. |

---

## High Priority

| # | File | Line | Category | Issue | Fix |
|---|------|------|----------|-------|-----|
| H1 | `code_muse/http_utils.py` | 51–58 | Security | `_resolve_proxy_config` silently sets `verify = False` (disable TLS verification!) when `MUSE_DISABLE_RETRY_TRANSPORT=1` is set AND no `SSL_CERT_FILE` is configured. The "legacy compatibility" comment understates the risk: a single env flag intended to control retry behaviour also disables MITM protection without any warning emitted. | Decouple the two concerns. `disable_retry` should NEVER touch `verify`. Keep TLS on by default; require an explicit `MUSE_DISABLE_TLS_VERIFY=1` (which already exists below, but only as an additive override) and emit a loud `emit_warning` whenever it is honored. |
| H2 | `code_muse/plugins/code_critic/critic_agent.py` | 53–58 | Security | The agent advertises "read-only access to inspect code" but lists `invoke_agent` in `get_available_tools()`. `invoke_agent` can call any other registered agent — including agents with full file-write and shell execution tools — which silently breaks the read-only contract. | Drop `invoke_agent` from the tool list, or constrain it via `tools_config` to a whitelist of read-only agent names. Update the prompt to match. |
| H3 | `code_muse/http_utils.py` | 199–223 | Bug | `RetryingAsyncClient.send` exits its loop without raising and may return `None` when `last_response` and `last_exception` are both `None` (e.g. `max_retries=0` and no exception). httpx callers will crash on `response.status_code` / `response.aread()`. | Initialize `last_response` to a sentinel and raise `httpx.RequestError("retries exhausted")` (or similar) on the unreachable-but-possible empty-loop path. |
| H4 | `code_muse/version_checker.py` | 13–25 | Bug | `_version_tuple("1.0.0a1")` raises `ValueError`, the bare except returns `None`, and `version_is_newer` returns `False` for ANY pair where either side has a pre-release/post/local segment (`a1`, `rc2`, `+local`, `dev0`). Users on a beta build will never see updates. | Use `packaging.version.Version` from `packaging` (bundled with pip) instead of hand-rolled int tuples: `Version(latest) > Version(current)`. |
| H5 | `code_muse/version_checker.py` | 71 | Bug | `start_version_check` calls `asyncio.create_task(default_version_mismatch_behavior(...))` but never stores the resulting Task. Per CPython docs, the loop only holds **weak** references to running tasks, so the GC may collect it mid-flight and silently cancel the version check. | Hold a module-level `set[asyncio.Task]` and add the task with `add_done_callback(set.discard)` to keep a strong ref until completion. |
| H6 | `code_muse/callbacks.py` | 295–315 | Performance / Robustness | `_trigger_callbacks_sync` runs every async callback via `_executor.submit(asyncio.run, result)` then `future.result(timeout=30)`. A single misbehaving sync caller can stall a hot path for **30 s × N callbacks**. Worse, `asyncio.run` creates and tears down a new event loop per call — cancellation, contextvars, and any caller-side `loop` references are lost. | Use a single dedicated background loop (`asyncio.new_event_loop()` running in one thread) and `asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=...)`. Make the timeout configurable, and surface the timeout as an `emit_warning`, not a silent failure. |
| H7 | `code_muse/cli_runner/__init__.py` | 109–124 | Bug | Model is set early via `set_model_name(early_model)` *before* `ensure_config_exists()` is called, then re-validated in a separate block below. Order-dependent side effects: if the config file does not yet exist, `set_model_name` may write into a partially-initialized state. `early_model` is also assigned but never used after the early call. | Move `ensure_config_exists()` ahead of any config writes; collapse the two `args.model` blocks; remove the unused `early_model` local. |
| H8 | `code_muse/secret_storage.py` | 11–12 | Bug / Code smell | `import orjson` and `import orjson as json` are both present at module scope. `json` is shadowed by orjson's interface — `orjson.dumps` returns `bytes` (it's used correctly here), but anyone reading the file is invited to assume stdlib `json` semantics. The same dual import appears in `model_factory.py`, `tools/file_modifications.py`, `agents/agent_manager.py`, and `plugins/code_critic/reviewer.py`. | Pick one alias project-wide. Either `import orjson` everywhere (preferred — explicit), or `import orjson as json` everywhere; never both in the same file. |
| H9 | `code_muse/plugins/code_critic/reviewer.py` | 87–116 | Correctness | Three issues stacked: (a) `code_snippet[:6000]` truncates silently — multi-thousand-line files are reviewed only as their first 6 KB, and the LLM is never told. (b) Even after C5 is fixed, `_extract_json` always returns a dict with `"verdict"` set, so the `if parsed and "verdict" in parsed` branch is the only code path — the `_fallback_verdict("Could not parse structured review", text)` line is dead. (c) `retries=1` on an agent doing structured-output extraction is too low; pydantic-ai retries are cheap. | (a) Emit a warning when truncation occurs, document the limit, and consider chunked review. (b) Distinguish "real JSON returned" from "heuristic guess" inside `_extract_json` (return `None` on heuristic) so the fallback path becomes reachable. (c) Bump retries to 3. |

---

## Medium Priority

| # | File | Line | Category | Issue | Fix |
|---|------|------|----------|-------|-----|
| M1 | `code_muse/security/redaction.pyx` | 42–44 | Security | `_ENV_ASSIGNMENT_RE` is `r"(?i)([A-Z_]*(?:API_KEY\|SECRET\|TOKEN\|PASSWORD\|AUTH\|CREDENTIALS)[A-Z_]*=)(.+?)(?=[\s&]+[A-Z_][A-Z0-9_]+=\|$)"`. The non-greedy `(.+?)` plus the lookahead means: (a) quoted values containing spaces (`API_KEY="abc def"`) leak the trailing portion if no following assignment follows; (b) values without trailing `\s\|&` AND without `$` may not match at all when embedded inside larger strings; (c) `(?i)` together with `[A-Z_]*` is redundant and confusing. Add unit tests covering quoted, multi-line, and JSON-embedded forms. | Anchor on `=` boundaries more carefully, support `"..."`/`'...'` quoted values, and make case sensitivity explicit. Add `tests/security/test_redaction.py` cases for these forms. |
| M2 | `code_muse/security/redaction.pyx` | 3 | Code smell | `import orjson as json` at module scope is shadowed locally by direct `orjson.loads` / `orjson.dumps` calls in `_redact_json_string`. The alias is dead. | Drop `import orjson as json`; keep only `import orjson`. |
| M3 | `code_muse/security/redaction.pyx` | (whole file) | Quality | `pyproject.toml` has `[tool.ruff] exclude = ["*.pyx"]` — Cython files get NO lint coverage. Style problems and accidental Python-3-isms slip through. | Add a separate `cython-lint` step (or `pyright --strict` over generated `.c` headers) to CI. |
| M4 | `code_muse/callbacks.py` | 270–293 | Robustness | `fire_callbacks` swallows every exception in the callback under `logger.debug(...)`. If a fire-and-forget hook is silently failing, you will never know. The async branch creates a `task` whose `add_done_callback` only logs a constant string — actual exceptions on the task are NOT surfaced (`task.exception()` is never called). | Log at `WARNING`/`ERROR` (not `DEBUG`); in the done-callback, call `t.exception()` and emit a structured warning if non-None. |
| M5 | `code_muse/callbacks.py` | 90–93 | Code smell | `commit_deferred()` resets `_defer_mode = False` early then *also* resets it inline before raising for an unsupported phase. The flag bookkeeping is duplicated and easy to break. | Use a `try/finally` to ensure `_defer_mode = False` exactly once, regardless of code path. |
| M6 | `code_muse/agents/agent_manager.py` | 49–53 | Bug | `get_terminal_session_id()` keys agent-state on `os.getppid()`. Under tmux/screen/SSH, the parent is the user's shell — every new shell invocation is a "new session" and the previous agent selection is lost. On Windows the meaning of PPID is similarly fragile. | Use a stable per-terminal identifier: `MUSE_SESSION_ID` env var if set, else `pty path` (POSIX) / `ConHost ID` (Windows), with PPID as last resort. |
| M7 | `code_muse/agents/agent_manager.py` | 226–252 | Robustness | `_discover_agents` wraps every plugin/agent import in a broad `except Exception` and demotes failures to `emit_warning`. A misnamed agent class or a syntax error in one user agent will be silently skipped — users see "agent not found" with no actionable error. | Capture the traceback and store last-failure-per-agent in a registry; surface it in `/agent` listing. |
| M8 | `code_muse/round_robin_model.py` | 78, 83 | Bug | `system` and `base_url` properties read `self.models[self._current_index]` without acquiring `self._lock`. The index can be mutated under your feet by `_get_next_model` running on another task; readers may briefly see a stale index. | Either snapshot the index inside the property under the lock, or document that these properties are best-effort. |
| M9 | `code_muse/tools/file_modifications.py` | 245–254 | Performance | `original.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")` is run on every read to "sanitize" surrogates — a full second pass through the file's bytes. For 1 MB files this doubles read time. | Only re-encode when `\udc00..\udcff` actually appears in `original` (`if any('\udc00' <= c <= '\udcff' for c in original)` first). |
| M10 | `code_muse/cli_runner/__init__.py` | 220–225 | UX / Maintainability | The `command` positional arg is documented `(deprecated, use -p instead)` and is still parsed and routed differently from `--prompt`. New users hit confusing edge cases when both are supplied. | Either remove (after deprecation period) or make `command` route through `--prompt` exactly. Today they take divergent paths. |
| M11 | `pyproject.toml` | 31–34 | Build | `dev-dependencies` is set inside `[project]`. **PEP 621 has no `dev-dependencies` field.** Setuptools/hatchling will ignore it. The `[dependency-groups]` table at the bottom duplicates the same list — that is the actual source of dev deps under uv. The unused field is misleading. | Delete the `[project] dev-dependencies` block. |
| M12 | `code_muse/plugins/__init__.py` | 24–46 | Robustness | `_clean_stale_pycache` walks the entire package tree and `shutil.rmtree`s any `__pycache__` dir whose parent has no `*.py` files. This can race with another `code-muse` process loading plugins — one process deletes the cache while another reads it, raising `ImportError` mid-load. | Restrict cleanup to dirs older than N seconds and gate behind a env var; default off. Or move to a one-shot `muse-cache --clean` subcommand. |

---

## Low Priority / Nitpicks

| # | File | Line | Category | Issue | Fix |
|---|------|------|----------|-------|-----|
| L1 | `pyproject.toml` | 47–50 | Code smell | `[project.scripts]` table contains a comment `# muse = "..." (duplicate — already defined above)` left behind from a prior edit. | Remove the comment. |
| L2 | `pyproject.toml` | 6 | Maintainability | `requires-python = ">=3.14,<3.16"` excludes 3.15 patch releases nominally allowed; classifier lists 3.14 and 3.15 only. Fine but tight. Document the policy. | Add a one-line rationale to README. |
| L3 | `code_muse/plugins/__init__.py` | 130–158 | DRY | Plugin name validation against `_SAFE_NAME_RE` is performed twice — once in `_load_user_plugins` and again in `_load_single_user_plugin`. | Validate once at the outer loop. |
| L4 | `code_muse/version_checker.py` | 56 | Robustness | `emit_warning(f"Error fetching version: {e}")` runs on every offline startup. Users without internet see a noisy warning. | Demote to `emit_info` with a one-line message, and only every Nth run. |
| L5 | `code_muse/tools/file_modifications.py` | 73 | Code smell | `import orjson as json_repair` aliases orjson under the *function name* `json_repair`. Confusing — there is also a real `json-repair` package in `pyproject.toml`. | Use the real `json_repair.repair_json` from `json-repair`, or rename the alias. |
| L6 | `code_muse/cli_runner/__init__.py` | 30 | Code smell | Wildcard-style imports of `interactive_mode`, `execute_single_prompt`, `run_prompt_with_attachments` re-exported via `__all__` even though they're already module-level names. Adds little. | Drop the redundant `__all__` or trim it to just the public names. |
| L7 | `code_muse/round_robin_model.py` | 61–67 | Robustness | `if not models: raise ValueError(...)` only fires on the variadic form; `RoundRobinModel(models=[])` would bypass it because `__init__` doesn't accept a `models=` kwarg — but the field declaration `models: list[Model]` advertises one. | Document that only the positional form is supported, or convert to a single `models: list[Model]` constructor arg with explicit emptiness check. |
| L8 | `code_muse/tools/command_runner.py` | 134 | Maintainability | `_SHELL_EXECUTOR = ThreadPoolExecutor(max_workers=16, ...)` — magic constant. | Pull from config (`get_value("shell_max_concurrency", default=16)`). |
| L9 | `code_muse/plugins/code_critic/register_callbacks.py` | 82–84 | Robustness | `_emit_verdict` accepts `verdict.get("verdict", "flagged")`; but `review_file` may return `verdict=="error"`, which falls into the `else` branch and is announced as "flagged". | Add an explicit `elif v == "error":` arm to surface the file path/error reason. |
| L10 | `code_muse/version_checker.py` | 12 | Code smell | `def normalize_version(version_str)` — no type hints in this file at all, while the rest of the codebase has them. | Add `version_str: str \| None` / `-> str \| None` and similar for the other helpers. |
| L11 | `code_muse/security/redaction.pyx` | 105–112 | Code smell | `cdef str s` then immediate reassignments (`s = _redact_bearer_tokens(s)`); the `cdef` is fine but the chain hides the fact that `_redact_json_string` may convert *any* string to a sanitized JSON re-emission. Deserves a comment. | Add a doc-comment block describing the order of redactions and why JSON re-emission comes last. |

---

## Missing Components

### Tests missing for
- The `code_muse/plugins/code_critic/` plugin entirely — no `tests/plugins/test_code_critic*.py` exists. Given the plugin is a brand-new agent-orchestration boundary, untested is unacceptable.
- `RetryingAsyncClient.send`'s "all retries exhausted" path (H3) — no test forces the empty-loop case.
- `_resolve_proxy_config` interaction with `MUSE_DISABLE_RETRY_TRANSPORT` and `MUSE_DISABLE_TLS_VERIFY` (H1) — security-sensitive, deserves explicit assertions.
- Pre-release version comparison in `version_checker.py` (H4).
- `start_version_check` task lifetime (H5).
- `EditFilePayload` schema generation (C3) — should fail loudly today.
- `VerbosityLevel` import paths (C1, C2) — a simple `python -c "import code_muse.plugins.build_filter.strategies.build"` would have caught C2.

### Documentation missing for
- The `agent_run_end` metadata contract that the code-critic plugin depends on (`metadata["review_files"]`). Where does this key originate? `AGENTS.md` does not document it.
- `MUSE_DISABLE_RETRY_TRANSPORT` and `MUSE_DISABLE_TLS_VERIFY` env vars — security-critical, undocumented in `docs/SECURITY.md`.
- The `command_line/` directory is supposed to be off-limits per `AGENTS.md`, yet `cli_runner/` clearly modifies global verbosity/model state. Document the boundary.

### Type hints missing
- Most of `code_muse/version_checker.py` (no annotations at all).
- `code_muse/http_utils.py` mixes `bool | str = None` (should be `bool | str | None = None`).
- `code_muse/tools/file_modifications.py:_log_error` accepts `exc: Exception | None` but still passes through `traceback.format_exc()` which only works on the *currently active* exception — not the captured `exc`. Document or fix.

### Error handling gaps
- `code_muse/secret_storage.py:atomic_write_private_bytes` does not clean up the temp file if `os.write` fails — the `.tmp` sibling is left behind.
- `code_muse/agents/agent_manager.py:_save_session_data` swallows `OSError` silently. A persistent session-store failure should at least be logged once per process.

### Linter/type coverage
- `pyproject.toml` enables `[tool.mypy] strict = true` over the whole package, but the `int | None` returns and untyped helpers in `version_checker.py` and elsewhere strongly suggest `mypy` is not actually clean. Run `mypy code_muse` and reduce the strictness gradually if needed, OR fix the gaps.
- `*.pyx` excluded from ruff (M3) — add a `cython-lint` job.
- `requires-python = ">=3.14"` is unusual; CI matrix should pin a 3.14 build to catch issues like C2/C1 before merge.

---

## Positive Notes

What this codebase does well — keep it up:
- **Atomic deferred plugin registration** in `callbacks.py` (`begin_deferred`/`commit_deferred`/`rollback_deferred`) is excellent. Failed plugin imports cannot leave half-registered hooks.
- **`secret_storage.py`** is genuinely well-designed: `O_CREAT | O_EXCL`, mode `0o600` from creation, `fsync` before `os.replace`. This is how it's supposed to be done.
- **Path-policy and workspace-boundary enforcement** in `tools/file_modifications.py` (huge-file gates, fuzzy-replacement caps, surrogate sanitization) shows real care for adversarial inputs.
- **Cython-compiled redaction** in `security/redaction.pyx` is the right call — redaction happens on every log and must be fast.
- **Test breadth** is strong (~80+ test files, integration suite, security suite, plugin-specific tests). The infra is there; just fill the gaps above.
- **Round-robin model dispatch** uses `asyncio.Lock` correctly for the rotation index.
- **Plugin trust model** (content-hash manifest, fail-closed) is the right default.
- **Clear separation** between `messaging/` (UI), `cli_runner/` (orchestration), `tools/` (effects), `agents/` (LLM glue) — the contributors clearly thought about layering.

---

## Next Steps

In priority order:

1. **Fix C1 + C2 first** (the `VerbosityLevel`/`set_verbosity` `NameError`s). Add an integration test that does `python -c "import code_muse.cli_runner; import code_muse.plugins.build_filter.strategies.build"` so this class of bug fails CI immediately.
2. **Fix C5 + auto_review's twin bug** — switch `result.data` to `result.output`. Add a mock-pydantic-ai test that asserts `review_code` returns a structured verdict, not a flagged fallback.
3. **Fix C3 (`EditFilePayload`)** — change to a true union, regenerate any cached schemas, run the file-modification tests.
4. **Fix C4** — drop the unformatted `{id_suffix}` placeholder in the critic prompt.
5. **Fix H1** — decouple `MUSE_DISABLE_RETRY_TRANSPORT` from `verify=False`. This is a quiet privacy regression.
6. **Run `mypy --strict code_muse`** and triage the output — many of the medium issues will surface naturally.
7. **Add unit tests** for `code_critic` and `auto_review` plugins.
8. **Audit the rest** of the long tail: `model_factory.py` (51 KB), `tools/command_runner.py` (50 KB), `tools/file_modifications.py` (41 KB) — all exceed `AGENTS.md`'s "600-line hard cap" by 2-3×. Either split them or relax the rule honestly in the contributing guide.
9. **Decouple verbosity** — implement the actual `VerbosityLevel` enum and propagate it through `command_runner` / `build_filter` rather than relying on a phantom name.
10. **Sweep dual-import duplicates** (`import orjson; import orjson as json`) project-wide as a single PR.

---

*End of report.*
