# Code Review Report — muse (v1.4.4)

**Reviewer:** Senior Python Software Architect
**Scope:** Full codebase, with emphasis on recently-added features (Epics 019–024: Content Router, SmartCrusher, AST Code Compressor, Relevance Scoring, CPython 3.14 modernization, Post-Review Remediation).
**Python target:** 3.14–3.15 (per `pyproject.toml`).

Findings are ordered by severity. Each issue follows the required format.

---

## 1. Bug & Error Identification

### 1.1 `compress_git_status` only handles porcelain format — wrong summary for plain `git status`

* **Severity:** Critical
* **Location:** `code_muse/plugins/filter_engine/strategies/git.py` — `compress_git_status()`
* **Issue:** The parser expects `git status --porcelain -b` output (XY-prefixed lines, `## branch...origin` header). The dispatcher, however, executes the **user's literal command**, which is typically plain `git status` — producing human-readable text like `On branch main`, `Changes to be committed:`, `modified:   file.py`. None of that matches the `if line.startswith("##")` or `xy = line[:2]` checks, so every count comes back `0`.
* **Impact:** For the most common git command the agent runs, the compressed summary is *silently wrong*: `branch:unknown ↑0 ↓0 | M:0 A:0 D:0 ??0`. Agents and users are fed false data, which directly defeats the advertised "85% savings on git status." Verified reproducibly — see shell log from review.
* **Recommendation:** Either (a) rewrite the command so filter execution calls `git status --porcelain -b` instead of the user's raw command when classified as `git status`, or (b) implement a second parser for human-readable output (section headers `Changes to be committed:` / `Untracked files:`). Option (a) is simpler and more accurate.

### 1.2 `TrackingDatabase` instantiated per shell command — migrations + cleanup on every call

* **Severity:** Critical (performance + correctness risk)
* **Location:** `code_muse/plugins/token_tracking/record.py` — `record_command()`; `code_muse/plugins/token_tracking/database.py` — `TrackingDatabase.__init__`.
* **Issue:** `record_command` calls `TrackingDatabase()` inline for every filter dispatch. `__init__` unconditionally runs `_ensure_dir()`, `_run_migrations()` (two `try/except sqlite3.OperationalError` probes + possible `executescript`), and `self.cleanup()` (two `DELETE` queries). No singleton, no module-level cache. Each instance also creates its own connection + lock, so WAL isolation between instances is the only thing preventing corruption.
* **Impact:** Every shell command dispatched through the filter pays: directory check, two SQLite introspection queries, and two `DELETE ... WHERE timestamp < datetime('now', '-90 days')` scans — even on a database with thousands of rows and zero expired entries. Latency compounds when the agent spams small commands. On slow disks / network FS this can add tens-of-ms per call. It also makes the `_insert_count % 100` cleanup throttle meaningless (it's reset to 0 on every new instance).
* **Recommendation:** Make `TrackingDatabase` a true module-level singleton. Move migrations + cleanup into `load_plugin_callbacks()` startup path, not per-insert. Example:

  ```python
  _DB: TrackingDatabase | None = None
  def _get_db() -> TrackingDatabase:
      global _DB
      if _DB is None:
          _DB = TrackingDatabase()
      return _DB
  ```
  Then use `_get_db().insert(...)` in `record_command`.

### 1.3 Semantic compression silently mutates every large string tool result

* **Severity:** High
* **Location:** `code_muse/plugins/semantic_compression/register_callbacks.py` — `_on_post_tool_call` + `compressor.compress_semantic`.
* **Issue:** The plugin registers a `post_tool_call` callback that, for any string result ≥200 chars that does **not** pass the `_looks_already_compressed` heuristic, replaces the tool's return value with a grammatically mutilated version (articles, copulas, filler, "that" after bridge verbs all deleted; regex-based passive→active swaps). There is no opt-in list of tools this should apply to — it fires for *every* tool: `read_file`, `grep`, `agent_run_shell_command`, `list_files`, everything.
* **Impact:**
  1. Code, JSON, logs, URL-bearing text, and anything where exact words matter get silently rewritten before the model (or user) sees it.
  2. The passive→active regex `\\w+(?:ed|en|[dt]e?|wn|own)` matches *any* past-tense-shaped token — including identifiers like `closed`, `owned`, `printed`, `created_at` — and swaps surrounding words.
  3. Mutated text is cached as the *new* history. The original is lost for the rest of the session.
  4. `_looks_already_compressed` uses an 8% function-word ratio. Telegraphic but legitimate content (ls/grep output, stack traces) is falsely flagged "already compressed" and passes through unchanged, while prose tool output is mangled.
* **Recommendation:** Do **not** transform tool return values by default. If this feature is desired, gate it on (a) an allow-list of tools whose output is prose (none exist today), and (b) an explicit user opt-in flag. The `load_prompt` hook that *instructs the model* to write compressed output is safe and should be kept; the `post_tool_call` mutation should be removed or become strictly opt-in.

### 1.4 `ContentTypeDetector._is_code` miss rate is near 100% on real code

* **Severity:** High
* **Location:** `code_muse/plugins/filter_engine/content_detector.py` — `_is_code`.
* **Issue:** Requires 5% of the first 500 lowercased tokens to be in `CODE_KEYWORDS` (a hand-picked 29-word set). Real Python files typically have <2% keyword density because identifiers, operators, and punctuation dominate `split()`. Strings like `def foo(): pass` contain 3 tokens and 1 keyword — 33% keyword ratio, technically passes, but anything nontrivial fails the `>5%` test.
* **Impact:** Content-type routing for the `CODE` path is effectively dead. Most code files fall through to `UNKNOWN`, which maps back to the command category — meaning the content detector almost never contributes anything for code. Combined with 1.5 below, the AST compressor is reached only via `compress_read`'s filename-extension regex.
* **Recommendation:** Replace the keyword-density heuristic with structural detection: leading `^\\s*(def |class |function |const |let |import |from |package |func )` on any line, presence of balanced brace/indent structure, or a shebang. Alternatively, drop `CODE` detection from the sniffer entirely and rely on filename extension from the command string.

### 1.5 AST compressor unreachable for most languages via the code path

* **Severity:** High
* **Location:** `code_muse/plugins/filter_engine/strategies/code.py` — `_language_str_to_code_language`; `compress_code`.
* **Issue:** `compress_read` maps file extensions `py|js|ts|tsx|rs|go|java|cpp|c|h|rb|sh|sql` to a language string, then `_language_str_to_code_language` maps **only** `python/javascript/typescript/go` to a `CodeLanguage` enum. Rust, Java, C/C++, Ruby, Bash, SQL silently fall back to `_fallback_compress` (regex comment strip) even though the caller just identified the language correctly. Worse, the generic `compress_code` branch (`grep`, `find`, `ls`, `wc`, etc.) never invokes the AST compressor at all — only `compress_read` does.
* **Impact:** "Epic 021 — AST Code Compression" advertises multi-language support, but in practice only `.py/.js/.ts/.tsx/.go` see AST-aware compression, and only when the command is `cat/head/tail/less/bat/nl`. `cat foo.rs` gets regex-stripping; so does `grep foo *.py`.
* **Recommendation:** Remove `_language_str_to_code_language` and pass `LanguageParser.detect_language()` directly, which already knows all extensions supported by tree-sitter grammars. Explicitly document — or remove — the expectation that `grep`/`find` output is AST-compressed (it isn't; it's line-truncated).

### 1.6 `ContentType.CODE` → `category` creates double-work path

* **Severity:** Medium
* **Location:** `code_muse/plugins/filter_engine/dispatcher.py` — `FilterDispatcher.handle`, `content_strategy_map`.
* **Issue:** When the detector returns `ContentType.CODE`, the map routes back to the original command `category` (usually `code` or `read`). The dispatcher then looks up the `code` strategy, which runs `compress_code`, which itself re-detects the language from the filename in the command. The detector's CODE classification contributes nothing — it's a no-op round trip.
* **Impact:** Extra scan of `stdout` (the `_is_code` loop over 500 tokens), zero effect on output. Architectural smell: two competing language-detection paths that don't share logic.
* **Recommendation:** Either (a) drop `ContentType.CODE` from the detector and the map, or (b) make the map route `CODE` to a content-aware strategy that bypasses filename detection. Don't run both.

### 1.7 `verbosity.get_verbosity()` reads `sys.argv` directly

* **Severity:** Medium
* **Location:** `code_muse/plugins/filter_engine/verbosity.py` — `get_verbosity`.
* **Issue:** Parses `-u`, `-v`, `-vv`, `-vvv` by literal membership in `sys.argv` without integrating with the app's `argparse` in `cli_runner/args.py`. Any user prompt, file path, or model name containing `-v` or `-vv` as a standalone token sets the verbosity level for the entire process.
* **Impact:** A user running `code-muse -p "review -v output of my tool"` ends up in `VERBOSE` mode globally. Worse, `-vvv` silences filtering entirely, so a stray token disables the advertised token savings. Also makes the module untestable without monkey-patching `sys.argv`.
* **Recommendation:** Accept verbosity as an argument to `get_verbosity()` and have the CLI set it explicitly after `argparse`. Fallback to the env var only. Remove the `sys.argv` scan.

### 1.8 Redundant exception tuple entries (`JSONDecodeError, ValueError`, `PermissionError, FileNotFoundError, OSError`)

* **Severity:** Medium
* **Location:** Multiple. Notable: `content_detector.py:_is_json`, `filter_engine/registry.py:_json_smartcrusher`, `test.py:compress_vitest_jest`, `command_line/file_path_completion.py:72`, `tools/common.py:1101/1187/1269/1355`.
* **Issue:** `json.JSONDecodeError` is a subclass of `ValueError`; `PermissionError` and `FileNotFoundError` are subclasses of `OSError`. Listing parent + child in the same `except` tuple is redundant and signals the author didn't check the hierarchy.
* **Impact:** Harmless at runtime, but the pattern usually indicates the same author wrote the Python 2-style `except A, B:` clauses, so these files should be audited together for the comma-vs-tuple confusion. (Python 3.14 *does* parse `except A, B:` as a tuple — so the current code runs — but the style is non-standard and will confuse any future reader on another Python version.)
* **Recommendation:** Replace with the parent class alone: `except OSError:`, `except ValueError:`. For the Python 2-style clauses, run a project-wide codemod to add parentheses: `except (A, B):`.

### 1.9 `_is_search` double `bool()` wrap

* **Severity:** Low
* **Location:** `code_muse/plugins/filter_engine/content_detector.py:209` — `_is_search`.
* **Issue:** `return bool(bool(re.search(...)))` — `bool()` of a `bool` is a no-op.
* **Impact:** Cosmetic; reads as though the author was uncertain of the return type.
* **Recommendation:** `return re.search(...) is not None`.

---

## 2. Architecture & Design Flaws

### 2.1 `interactive_mode` god-function (~560 lines)

* **Severity:** High
* **Location:** `code_muse/cli_runner/loop.py` — `interactive_mode` and its helpers.
* **Issue:** Even after the Phase-3 refactor (commits `0a0a45f`, `3521471`, `8842f8b`, etc.) that extracted `_show_startup_info`, `_handle_initial_command`, `_ensure_prompt_toolkit`, `_maybe_run_onboarding`, `_read_user_input`, `_handle_keyboard_interrupt`, `_handle_eof`, `_cancel_agent_task_if_running`, `_is_shell_passthrough_and_execute`, `_is_exit_command`, `_is_clear_command`, `_handle_slash_command`, `_run_main_input_loop`, `_handle_agent_cancellation`, `_wiggum_loop` — the loop still mixes terminal reset logic, signal handling, attachment parsing, autosave rotation, wiggum looping, and agent cancellation in one place. `_run_main_input_loop` alone has seven distinct responsibilities (input gathering, shell passthrough, exit/clear, slash routing, autosave picker, history persistence, return value).
* **Impact:** High cyclomatic complexity, difficult to test in isolation (most paths need prompt_toolkit + the agent runtime + the message bus), brittle when new input types are added.
* **Recommendation:** Introduce an `InputDisposition` enum/dataclass (`SHELL`, `EXIT`, `CLEAR`, `SLASH_HANDLED`, `SLASH_REWRITE(str)`, `TASK(str)`) returned from a dedicated input-classification step. `_run_main_input_loop` becomes a pure dispatch on that enum. Move terminal-reset side effects into a context manager wrapping the prompt_toolkit call.

### 2.2 Duplicate `_PLUGINS_LOADED` flags — two independent idempotency guards

* **Severity:** Medium
* **Location:** `code_muse/plugins/__init__.py` (`_PLUGINS_LOADED` at module scope) and `code_muse/command_line/command_handler.py` (`_PLUGINS_LOADED` at module scope, plus `_ensure_plugins_loaded` that only flips its own flag on success).
* **Issue:** Two modules each have their own global gate. `command_handler._ensure_plugins_loaded` calls `plugins.load_plugin_callbacks()`, which checks its own flag. The `command_handler` flag is set to `True` even when the plugin module is already loaded (first branch returns without setting flag — actually it does set to True in the except branch too). The flags are not synchronised; if tests clear one but not the other, results diverge.
* **Impact:** Confusing state management, and tests that use `monkeypatch` to reset plugin state must remember to reset both flags.
* **Recommendation:** Move all idempotency to one place (`plugins.load_plugin_callbacks`) and have `command_handler._ensure_plugins_loaded` simply call it — no local flag.

### 2.3 `run_shell_command` callback priority documented as "alphabetical" but not enforced

* **Severity:** Medium
* **Location:** `code_muse/callbacks.py` — `on_run_shell_command` docstring; `code_muse/plugins/__init__.py` — `_load_builtin_plugins` uses `plugins_dir.iterdir()`.
* **Issue:** The docstring claims the priority chain is `filter_engine → policy_engine → shell_minimizer` "alphabetical" but nothing sorts. `Path.iterdir()` order is filesystem-dependent (and on some FSes non-deterministic). A plugin called `aardvark` would jump the queue; a plugin called `zzz_` would end up last silently. The first callback that returns `{"pre_executed": True, ...}` short-circuits the chain, so ordering is semantically meaningful.
* **Impact:** Adding a new `run_shell_command` plugin can break filter_engine's "always runs first" assumption without any warning.
* **Recommendation:** Either (a) explicitly `sorted(plugins_dir.iterdir())` in the loader, or (b) add a real priority field to `register_callback()` with an integer argument, and sort the callback list at trigger time. Option (b) also retires the comment in `filter_engine/register_callbacks.py` that says `# Priority 1 (runs first, alphabetically earliest)` — which is aspirational, not enforced.

### 2.4 Fragile import chain in `filter_engine/__init__.py` — ast_compressor/json_compressor/ast_parser not listed

* **Severity:** Medium
* **Location:** `code_muse/plugins/filter_engine/__init__.py` and `registry.py`.
* **Issue:** `__init__.py` imports `strategies.{code, git, lint, test}` to trigger self-registration but omits `ast_compressor`, `ast_parser`, `json_compressor`, `json_patterns`. Those work today only because:
  * `code.py` transitively imports `ast_compressor` and `ast_parser`.
  * `registry.py` registers inline JSON/diff/log/html/search stubs that lazy-import `json_compressor` at call time.

  Any future refactor that removes the `code.py` → `ast_compressor` import will silently break AST compression with no error — just fallback to regex-stripping.
* **Impact:** Invisible coupling; a reviewer has no single file that declares "here are the strategy implementations."
* **Recommendation:** Explicitly list all strategy submodules in the `from ... import` block, or introduce a `strategies/_register_all.py` that imports everything and is itself imported by `__init__.py`.

### 2.5 `load_prompt` callback returns a raw string of compression instructions

* **Severity:** Medium
* **Location:** `code_muse/plugins/semantic_compression/register_callbacks.py` — `_get_compression_prompt`.
* **Issue:** The hook returns a hard-coded prompt that is concatenated into **every** agent's system prompt, unconditionally, with no way for an agent that doesn't want compressed output (e.g. a code-review agent, JSON agent) to opt out. The prompt also instructs the model to drop articles and copulas from *its responses*, which may produce telegraphic code comments and broken markdown in the user-facing output.
* **Impact:** System-prompt budget bloat (~800 chars) for every agent, and possibly degraded output quality for tasks where readability matters.
* **Recommendation:** Gate by a config flag (`get_config_value("semantic_compression.prompt_injection")` default off) or by agent tag. At minimum, qualify the injection with "optional, when the user explicitly requests compact output."

### 2.6 `StrategyRegistry` priority log messages inverted ("ignoring" logged as `warning`)

* **Severity:** Low
* **Location:** `code_muse/plugins/filter_engine/registry.py` — `StrategyRegistry.register`.
* **Issue:** Both the "winning" override *and* the "losing" registration log at `warning` level. An ignored duplicate with lower priority is expected behaviour (built-in lower-priority stubs get overridden by higher-priority real strategies). Logging both at the same level produces noisy warnings on every startup.
* **Impact:** Log noise; a real priority conflict is indistinguishable from expected overrides.
* **Recommendation:** Log expected override at `debug`; log *collisions at equal priority* at `warning` (which the current code doesn't even detect — `priority <= existing_priority` lumps equal with lower).

### 2.7 Content-type sniffer runs *after* full command execution

* **Severity:** Low
* **Location:** `code_muse/plugins/filter_engine/dispatcher.py` — `FilterDispatcher.handle`.
* **Issue:** Command runs first, full stdout buffered, then `ContentTypeDetector.detect(stdout)` decides routing. For long-running commands (`find /`, `grep -r`) this pays the full I/O + memory cost before any compression decision. Detection itself re-scans the text (`_is_log` samples 50 lines, `_is_code` tokenises up to 500 words).
* **Impact:** No shortcutting for huge outputs; memory pressure on `cat` of a large log.
* **Recommendation:** Streaming sniffer that decides after the first N KB; or sniff based on command + extension first, and fall back to content only on ambiguous categories.

### 2.8 `JSONAgent` / `BaseAgent` coupling to config/puppy/owner globals

* **Severity:** Low
* **Location:** `code_muse/agents/agent_code_muse.py` — `get_system_prompt()` calls `get_puppy_name()` and `get_owner_name()` from `config`.
* **Issue:** Per-request system-prompt construction reaches into global config, so tests that want to stub one value must mock two free functions. Makes per-session prompt variants awkward (e.g., subagents with overridden personas).
* **Recommendation:** Inject the two names into the agent at construction time; let `refresh_agents()` rebuild instances when config changes.

---

## 3. Performance & Bottlenecks

### 3.1 Per-command SQLite migration + cleanup (repeat of 1.2)

* **Severity:** Critical
* **Location:** `token_tracking/record.py` + `database.py`.
* **Issue:** See 1.2. The performance dimension is that every filter dispatch pays for directory `mkdir`, two `SELECT` probes for schema version, and two `DELETE` passes.
* **Impact:** Measurable latency on every shell command routed through the filter engine; disk I/O amplification; SQLite WAL checkpoint pressure.
* **Recommendation:** Singleton the `TrackingDatabase`, run migrations in `_on_startup`, and throttle `cleanup()` to once per session (or once per N inserts *on the singleton*, not per instance).

### 3.2 Full `rglob("*.py")` on every plugin load for content hash

* **Severity:** Medium
* **Location:** `code_muse/plugins/__init__.py` — `compute_plugin_hash`.
* **Issue:** For each user plugin directory, the loader walks the entire tree with `rglob("*.py")`, sorts, then reads every file's bytes into a SHA-256. Runs at startup (before the app is interactive) and inside `_load_single_user_plugin`, even if the plugin is then skipped for not being trusted.
* **Impact:** Slow startup on machines with large user-plugin trees (multi-MB plugins, e.g. bundled ML deps). Hash is also computed for trusted plugins every time — can't be cached because trust is *keyed by* the hash.
* **Recommendation:** Cache the hash by `(mtime_of_plugin_dir, size_sum)` as a cheap short-circuit; recompute SHA-256 only when the cheap key changes. Consider moving trust enforcement to file signatures instead of content hashes.

### 3.3 `_collect_lines` in AST compressor recurses without memoization

* **Severity:** Medium
* **Location:** `code_muse/plugins/filter_engine/strategies/ast_compressor.py` — `_collect_lines._walk`.
* **Issue:** Computes `source[: node.start_byte].count("\n")` and `source[: node.end_byte].count("\n")` for every node. On a 1 MB source file with 10k AST nodes, this is O(nodes × source_length) string slicing + counting.
* **Impact:** AST compression of a 1 MB file takes seconds instead of milliseconds. Works fine for small files (the common case) but a single large `cat` command can block the event loop.
* **Recommendation:** Precompute a line-start byte-offset array once (`offsets = [0]; for i, c in enumerate(source) if c == "\n": offsets.append(i+1)`), then binary-search `bisect.bisect_right(offsets, node.start_byte) - 1` to get the line number in O(log lines).

### 3.4 `ConsoleSpinner` start/stop on every agent call

* **Severity:** Low
* **Location:** `code_muse/cli_runner/runner.py` — `run_prompt_with_attachments`.
* **Issue:** Each user turn instantiates a `ConsoleSpinner` context manager, which starts a thread and a Rich Live display, even if the model response streams back in <100 ms. For the `-p` single-prompt path this is unnecessary.
* **Impact:** ~10 ms overhead per turn; minor flicker on fast responses.
* **Recommendation:** Defer spinner start by 250 ms (debounce); skip entirely in non-interactive `-p` mode.

### 3.5 `ContentTypeDetector._is_log` scans 50 lines × 5 regexes

* **Severity:** Low
* **Location:** `code_muse/plugins/filter_engine/content_detector.py`.
* **Issue:** Each of the first 50 lines is tested against 5 regex patterns until one matches. For a file of 50+ trivial lines, this is 250 regex evaluations before routing.
* **Impact:** Negligible per call, but content detection runs on every shell dispatch.
* **Recommendation:** Combine the five log patterns into a single compiled alternation `re.compile(r"...|...|...")`. Same for HTML and search detectors.

### 3.6 `_load_session_data` / `_save_session_data` rewrite full JSON per session cache hit

* **Severity:** Low
* **Location:** `code_muse/agents/agent_manager.py`.
* **Issue:** Every update to the in-memory session map triggers `_save_session_data`, which serialises the entire dict, writes a `.tmp`, and renames. For sessions with many parallel terminal instances this is O(N) per update.
* **Impact:** Minor; reduces to zero for single-terminal users.
* **Recommendation:** Lazy/debounced write (e.g., save at process exit or every 30 s).

---

## 4. Feature Integration & Wiring

### 4.1 SmartCrusher JSON strategy reachable only via content-type detection

* **Severity:** High
* **Location:** `code_muse/plugins/filter_engine/classifier.py` (no `json` category) + `dispatcher.py` `content_strategy_map`.
* **Issue:** `CommandClassifier.classify()` can return `git`, `test`, `lint`, `code`, `read`, or `unknown`. It **never** returns `json`. The `json` category is only reached when `ContentTypeDetector.detect(stdout) == ContentType.JSON`, i.e. stdout parses cleanly as JSON. That means:
  * A wrapper script that prints a JSON blob with a trailing banner line → classified `unknown` → no compression.
  * `kubectl get pods -o json` with colour ANSI → JSON parse fails → no compression.
  * Any command with stderr mixed into stdout → parse fails → no compression.
* **Impact:** The "SmartCrusher" epic's advertised JSON compression fires only on pristine JSON output, which is rarer than it looks.
* **Recommendation:** Add a `json_command` category to the classifier (match `jq`, `curl ... | python -m json.tool`, `aws ... --output json`, `kubectl ... -o json`, `gh api ...`). Route via the command category in addition to content sniffing.

### 4.2 `FilterDispatcher` error-recovery path writes tee files but doesn't notify

* **Severity:** Medium
* **Location:** `code_muse/plugins/filter_engine/dispatcher.py` — `handle()` except block.
* **Issue:** When a strategy raises, the dispatcher writes raw stdout/stderr to a tee file under `tempfile.gettempdir()/muse_tee/` and returns a `ShellCommandOutput` whose `stdout` is `⚠ Filter error — raw output saved to {tee_path}`. But this surfaces to the agent model, not the user. The user sees only what the model chooses to report, and the tee files are cleaned up 24 h later by the startup hook. There's no `/tee` command to inspect recent tee files.
* **Impact:** Silent degradation when compression bugs occur. A recurring strategy crash leaves the user unaware that output is being redirected.
* **Recommendation:** Emit a warning to the user via `emit_warning()` (visible in the interactive console), plus a new `/tee list` or `/tee recover <path>` slash command to surface recent failures.

### 4.3 Semantic compression `post_tool_call` runs before or after filter_engine depending on registration order

* **Severity:** Medium
* **Location:** `semantic_compression/register_callbacks.py` + `filter_engine/register_callbacks.py`.
* **Issue:** Semantic compression registers a `post_tool_call` callback. Filter engine registers a `run_shell_command` callback. These are different hooks, so they don't conflict directly — but the *order* of `post_tool_call` callbacks (when multiple plugins register) is also determined by plugin-directory iteration order. Which means `semantic_compression` (alphabetically `s`) fires after `agent_skills`, `autonomous_memory`, `token_caching`, `token_tracking`. If any of those return a modified result, semantic compression compresses the already-modified text.
* **Impact:** Tool-result pipelines are order-dependent with no documentation of the expected order.
* **Recommendation:** Same fix as 2.3 — explicit priorities on `register_callback()`. At minimum, document the observed order for `post_tool_call`.

### 4.4 `compress_code` → `compress_ast_code` double-detection

* **Severity:** Low
* **Location:** `code_muse/plugins/filter_engine/strategies/code.py` — `compress_read`.
* **Issue:** `compress_read` runs a regex on the command to derive `language_str`, maps it to `CodeLanguage`, and passes that to `compress_ast_code`. Inside `compress_ast_code`, the first branch is `if language is None and filename: ...` — but `language` is never None here, so the branch is never taken. The function also re-does `LanguageParser.detect_language(source)` if its caller passes no filename, so detection logic exists in two places.
* **Impact:** Two places to update when adding a new language.
* **Recommendation:** Remove `_language_str_to_code_language` and pass the filename from the command into `compress_ast_code`; let the parser be the single source of truth for language detection.

### 4.5 `register_callback` called at module import — plugin load order determines behaviour

* **Severity:** Low
* **Location:** All plugin `register_callbacks.py` files.
* **Issue:** Registrations happen as side effects of `importlib.import_module`. If an error interrupts plugin loading mid-way, partially-registered callbacks remain. There is no transaction, no rollback.
* **Impact:** Crashes during plugin load leave the callback registry in a half-initialised state.
* **Recommendation:** Collect registrations first, commit atomically on full success.

### 4.6 `checkpointing` plugin's `_on_startup` is an empty function — callback registered anyway

* **Severity:** Low
* **Location:** `code_muse/plugins/checkpointing/register_callbacks.py:47-52`.
* **Issue:** `_on_startup` body is `pass` with a comment `# disabled rewind listener`. The function is still registered for the startup phase.
* **Impact:** Wasted callback slot; future readers wonder why a no-op is registered.
* **Recommendation:** Delete the function and the `register_callback("startup", _on_startup)` line (already tracked in `bd/024-03-dead-code-cruft.md`).

---

## 5. Dead Code & Cruft

### 5.1 `filter_engine/cli_flags.py` is pure documentation, zero code

* **Severity:** Low
* **Location:** `code_muse/plugins/filter_engine/cli_flags.py`.
* **Issue:** The file is a docstring + block comment describing flags. No classes, functions, or executable statements. Its purpose is served by the `verbosity.py` docstring already.
* **Impact:** Misleading — a module named `cli_flags` implies it does something.
* **Recommendation:** Delete the file and move its content into `verbosity.py`'s module docstring.

### 5.2 `_compress_dict` level-0 fallback is a redundant dict copy

* **Severity:** Low
* **Location:** `code_muse/plugins/filter_engine/strategies/json_compressor.py` — `_compress_dict`.
* **Issue:** The `if not kept` branch does `kept = {k: data[k] for k in data}`, which is equivalent to `dict(data)` or just `data`. The comment says "keep all keys but format compactly," but since this runs at level 0 (ultra-compact), keeping *all* keys defeats the purpose. It's only reachable when `_select_fields` returns an empty list *and* `data` is non-empty, which happens if every field's importance score is below 0.7.
* **Impact:** Silent fallback to near-full output at the most aggressive compression level.
* **Recommendation:** Either fall back to a real compact mode (e.g., keep only the top-3 highest-scored fields) or raise the threshold so the "kept" list is never empty for non-trivial inputs.

### 5.3 Legacy command fallback block in `command_handler.py`

* **Severity:** Low
* **Location:** `code_muse/command_line/command_handler.py` (historical; bd issue `024-03` mentions lines 224–238 — the current file may have already removed it).
* **Issue:** Was a commented-out example block with no functioning code.
* **Impact:** None if already removed. If still present, it's dead documentation.
* **Recommendation:** Verify removal during Epic 024 work. Issue already tracked.

### 5.4 Redundant in-function imports in `cli_runner/` modules

* **Severity:** Low
* **Location:** `cli_runner/__init__.py`, `cli_runner/loop.py`, `cli_runner/runner.py`.
* **Issue:** `emit_info`/`emit_error`/`emit_success`/`emit_warning`/`emit_system_message` are imported at module scope but also re-imported inside functions (`_handle_initial_command`, `_handle_slash_command`, `execute_single_prompt`, etc.). `get_message_bus` and `AgentResponseMessage` are imported twice in `runner.py` / `loop.py` with the same effect. `auto_save_session_if_enabled` is imported at module scope *and* re-imported inside `_wiggum_loop`.
* **Impact:** Cosmetic; slight performance hit from repeated lookups. Already tracked in `bd/024-04-import-cleanup.md`.
* **Recommendation:** Rely on module-scope imports; only re-import inside functions where circular-import constraints force it.

### 5.5 Commented-out `# TODO: PEP 750 t-string — use templatelib when stable` in `database.py`

* **Severity:** Low
* **Location:** `code_muse/plugins/token_tracking/database.py` — `query_edit_summary`.
* **Issue:** The TODO acknowledges `f""" ... WHERE {where}"""` is a smell, even though `where` is chosen from a fixed safe dict. Leaving the comment without a tracking issue invites copy-paste that forgets the safe-dict constraint.
* **Impact:** Future developer may generalize the pattern to user input.
* **Recommendation:** Replace with a real constant and drop the TODO, or link to a bd issue. A templatelib refactor is premature.

### 5.6 `SESSION_ID` generated at module load with no rotation

* **Severity:** Low
* **Location:** `code_muse/plugins/token_tracking/record.py:13`.
* **Issue:** `SESSION_ID: str = str(uuid.uuid4())` is created once per interpreter. If the user runs `clear` or rotates an autosave session, the tracking `session_id` stays the same, so token-savings reports can't distinguish sub-sessions within one process.
* **Impact:** Less granular reporting, not a correctness bug.
* **Recommendation:** Tie `SESSION_ID` to the autosave session id (`config.get_current_autosave_id()`) and refresh on `clear`/`finalize_autosave_session`.

---

## Summary — Top 5 Fixes To Prioritise

1. **Fix `compress_git_status` to handle non-porcelain output** (1.1). This is the most-used compression path and it's producing wrong numbers today.
2. **Singleton `TrackingDatabase`** (1.2 / 3.1). Per-command migrations and deletes are a silent tax on every shell dispatch.
3. **Gate or remove the `post_tool_call` semantic-compression rewrite** (1.3). Unconditionally mutating every tool result is unsafe.
4. **Repair AST compressor reach** (1.5 / 4.4). Honour the full `LanguageParser.EXTENSION_MAP` and invoke AST compression from the generic code path, not only `cat`/`head`/`tail`.
5. **Introduce real priorities on `register_callback`** (2.3 / 4.3). Two critical pipelines (`run_shell_command` and `post_tool_call`) currently depend on filesystem iteration order; this is a latent integration hazard any new plugin can trigger.

Secondary, easier wins: delete `filter_engine/cli_flags.py` (5.1), stop reading `sys.argv` in `get_verbosity` (1.7), replace redundant `except A, B:` tuples with their parent classes or parenthesised form (1.8), and wire `compute_plugin_hash` to a cheap mtime/size short-circuit (3.2).

None of the "critical" findings block the application from starting — Python 3.14's acceptance of `except A, B:` syntax means the previously-listed "syntax error" issues from earlier reviews are non-fatal. The real integration risks are (a) data corruption of tool results via semantic compression, and (b) wrong/missing compression in the git and JSON paths.
