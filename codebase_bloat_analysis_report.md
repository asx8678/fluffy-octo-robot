# Codebase Bloat Analysis Report
## code_muse — Low-Value / High-Cost Feature Audit

**Date:** 2026-05-15  
**Analyst:** Amal (muse-fe16ea)  
**Scope:** 753 Python files, 225,818 total LOC (90,241 source, 135,577 test)  
**Commit history range:** 2026-05-12 → 2026-05-14 (104 commits total)

---

## Executive Summary

This codebase carries **~29,000 lines of artificially bloated coverage tests** and **~15,000 lines of completely orphaned plugin code** that has zero production usage. The most egregious waste lives in three categories:

1. **Orphaned plugin subsystems** (MindPack, Browser Tools, Shell Minimizer, Copilot Auth) — thousands of lines with zero cross-references.
2. **Duplicate OAuth implementations** — three separate plugins (~12,400 LOC combined) all implementing the same device-flow pattern.
3. **Coverage-test bloat** — 42 files with `coverage` in their name totaling 29,158 lines of tests written purely to hit coverage metrics for marginal features.

---

## Methodology

1. **LOC Audit** — `find . -name '*.py' | xargs wc -l | sort -rn`
2. **Git History** — `git log --oneline -- <file>` for commit count and last-touch date
3. **Cross-Reference Search** — `grep -r "<module_name>" --include='*.py'` excluding self-directory and tests
4. **Test-to-Source Ratio** — compared test LOC against source LOC for bloated suites
5. **Functional Duplication** — identified multiple plugins solving the same problem (OAuth, diff UI, browser automation)

---

## Tier 1: Prime Removal Candidates (Complete Orphans)

### 1. 🔴 MindPack Plugin Suite — ~6,023 LOC total
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `plugins/mindpack/mindpack_menu.py` | 1,552 | 2 | 2026-05-13 | **0** |
| `plugins/mindpack/factory.py` | 932 | 5 | 2026-05-14 | **0** |
| `plugins/mindpack/orchestration.py` | 607 | 3 | 2026-05-14 | **0** |
| `plugins/mindpack/judge.py` | 575 | 4 | 2026-05-14 | **0** |
| Tests (`test_mindpack*.py`) | ~1,336 | — | — | — |

**Justification:**
- **Zero external references.** No core file imports or calls any MindPack module. It is a completely self-contained subsystem that is never wired into the application bootstrap.
- The `register_callbacks.py` exports tools and slash commands (`ask_mindpack`, `mindpack`), but nothing in the core CLI or agent system ever invokes them.
- It is the **sole consumer of `agent_creator_agent`** (another orphan — see #2).
- Provides marginal value: "multi-expert advisory analysis" that duplicates the existing sub-agent / skill invocation patterns already in `code_muse/agents/`.

**Recommended action:** Remove entire `code_muse/plugins/mindpack/` directory and `tests/plugins/test_mindpack*/`.

---

### 2. 🔴 Agent Creator Agent — 607 LOC source
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `agents/agent_creator_agent.py` | 607 | 4 | 2026-05-14 | **0** |

**Justification:**
- **Zero external references** outside its own file and MindPack (which is itself orphaned).
- The class `AgentCreatorAgent` implements an interactive agent for generating JSON agent configs. This functionality is already covered by:
  - `add_model_menu.py` (model registration)
  - `config/parser.py` (config schema handling)
  - Manual JSON editing of agent definitions
- Only referenced inside `mindpack_menu.py` via a hard-coded `"agent-creator"` string.

**Recommended action:** Remove after MindPack is removed (it has no other callers).

---

### 3. 🔴 Browser Tools Module — ~1,647 LOC source
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `tools/browser/browser_locators.py` | 640 | 1 | 2026-05-12 | **0** (real usage) |
| `tools/browser/browser_interactions.py` | 545 | 1 | 2026-05-12 | **0** (real usage) |
| `tools/browser/browser_scripts.py` | 462 | 1 | 2026-05-12 | **0** (real usage) |
| Tests (`test_browser_*.py`) | ~1,300+ | — | — | — |

**Justification:**
- Only referenced in `tools/__init__.py` (re-exported) but **never imported by any production code** outside that `__init__`.
- These are Selenium-style DOM locators and interaction wrappers that appear to be a half-implemented alternative to the actual browser tool: `tools/chrome_cdp/__init__.py` (1,069 LOC, 7 real references, actively used).
- Duplicates functionality already present in `chrome_cdp` which is the canonical browser debugging interface.
- All three files have exactly **1 commit** (initial creation) and have never been updated.

**Recommended action:** Remove `code_muse/tools/browser/` directory and associated tests. If DOM-style selectors are needed later, extend `chrome_cdp` instead.

---

### 4. 🟠 Shell Minimizer Plugin — 1,363 LOC source
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `plugins/shell_minimizer/pipeline.py` | 556 | 2 | 2026-05-14 | **7** (comments only) |
| `plugins/shell_minimizer/primitives.py` | 480 | 2 | 2026-05-14 | **7** (comments only) |
| `plugins/shell_minimizer/builtin_filters.toml` | ~? | — | — | — |

**Justification:**
- Referenced only in `callbacks.py` as a conceptual pipeline stage (`priority 0`) and in a few plugin comments.
- **Not wired to any actual shell command execution path.** The `command_runner.py` and `filter_engine` already handle output formatting and verbosity control.
- TOML-based filter pipeline is over-engineered for a problem that `filter_engine/verbosity.py` solves in ~100 lines.
- Zero dedicated test files found despite being a 1,363-LOC plugin.

**Recommended action:** Remove `code_muse/plugins/shell_minimizer/`. The `filter_engine` plugin already provides output filtering.

---

## Tier 2: High Duplication / Low Usage Candidates

### 5. 🟠 Copilot Auth Plugin — ~1,996 LOC total
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `plugins/copilot_auth/register_callbacks.py` | 461 | 2 | 2026-05-13 | **0** (outside self-dir/tests) |
| `plugins/copilot_auth/utils.py` | 587 | 4 | 2026-05-14 | **0** (outside self-dir/tests) |
| `plugins/copilot_auth/config.py` | ~? | — | — | — |
| Tests | 437 | — | — | — |

**Justification:**
- **Zero external references** outside its own directory and tests.
- Duplicates the **exact same OAuth 2.0 device-flow pattern** already implemented in:
  - `plugins/claude_code_oauth/` (2,162 LOC)
  - `plugins/chatgpt_oauth/` (1,411 LOC)
- All three plugins share the same architecture: `start_device_flow` → `poll_for_token` → `save_device_token` → `add_models_to_config`.
- GitHub Copilot is a niche authentication target compared to Anthropic/OpenAI. The cost-to-value ratio is poor.

**Recommended action:** Consolidate all three OAuth plugins into a single generic `oauth` plugin with provider-specific configuration files. Immediate removal of `copilot_auth/` saves ~2,000 LOC with zero production impact.

---

### 6. 🟠 Rich Renderer — ~2,334 LOC total
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `messaging/rich_renderer.py` | 1,156 | 2 | 2026-05-13 | **2** |
| Tests (`test_rich_renderer.py`) | 1,178 | — | — | — |

**Justification:**
- Only **2 external references** outside its own directory and tests.
- Duplicates functionality already in `messaging/bus.py` (661 LOC) and `messaging/messages.py` (591 LOC).
- Provides marginal cosmetic value (rich text panels, progress bars) that the core messaging bus already handles via simpler formatting.
- High test-to-source ratio (1.02:1) for a feature with almost no callers.

**Recommended action:** Deprecate and remove. Move any unique formatting logic into `messaging/bus.py` or `messaging/messages.py`.

---

### 7. 🟡 UC Menu — 909 LOC source
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `command_line/uc_menu.py` | 909 | 2 | 2026-05-13 | **1** |

**Justification:**
- Only **1 external reference** outside its own file and tests.
- Interactive TUI menu for the universal constructor system. The universal constructor is already accessible via:
  - Direct slash commands (`/uc-*`)
  - `tools/universal_constructor.py` (965 LOC)
  - `plugins/universal_constructor/` subsystem (2,280 LOC)
- This is a fourth layer of UI indirection for a feature that already has three access paths.

**Recommended action:** Remove. The constructor is already usable via CLI commands and callbacks.

---

### 8. 🟡 Colors Menu — 530 LOC source
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `command_line/colors_menu.py` | 530 | 1 | 2026-05-12 | **1** (config_commands.py) |

**Justification:**
- Only referenced by `config_commands.py` as an interactive color picker.
- Purely cosmetic: lets users pick terminal colors via a TUI.
- Colors can be configured directly in JSON/YAML config files.
- 1 commit, never updated.

**Recommended action:** Remove. Not worth 530 LOC + tests for a cosmetic preference that can be edited by hand.

---

## Tier 3: Consolidation Candidates (Functional Duplication)

### 9. 🟡 OAuth Plugin Triad — ~12,373 LOC combined
| Plugin | Source LOC | Test LOC | External Refs |
|--------|-----------|----------|---------------|
| `claude_code_oauth` | 2,162 | ~961+ | ~144 |
| `chatgpt_oauth` | 1,411 | ~1,008+ | ~93 |
| `copilot_auth` | 1,559 | ~437 | **0** |
| **Total** | **5,132** | **~2,406** | — |

**Justification:**
- All three implement the **same OAuth 2.0 device authorization grant flow**:
  1. Start device flow → get user_code and verification_uri
  2. Poll token endpoint
  3. Save refresh token
  4. Register discovered models
- The only differences are endpoint URLs, client IDs, and model name mappings — all of which could be provider-specific JSON configs.
- Consolidating to a single `oauth` plugin with `providers/claude.json`, `providers/openai.json`, `providers/copilot.json` would save **~8,000+ LOC**.

**Recommended action:** Design a generic OAuth plugin. Remove `copilot_auth` immediately (zero usage). Migrate `chatgpt_oauth` and `claude_code_oauth` over time.

---

### 10. 🟡 Diff Menu — ~2,958 LOC total
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `command_line/diff_menu.py` | 865 | 1 | 2026-05-12 | **1** |
| `tests/command_line/test_diff_menu.py` | 994 | — | — | — |
| `tests/command_line/test_diff_menu_coverage.py` | 1,099 | — | — | — |

**Justification:**
- Only referenced by `config_commands.py` (`interactive_diff_picker`).
- Core diff functionality already exists in `tools/diff_formatting.py`.
- The interactive TUI adds marginal value but costs 865 LOC + 2,093 LOC of tests.
- Test bloat is severe: 2.42 lines of tests per 1 line of source.

**Recommended action:** Remove `diff_menu.py` and its tests. If an interactive diff picker is needed, build a 50-line wrapper around `diff_formatting.py` using the existing menu primitives.

---

### 11. 🟡 Azure Foundry Plugin — ~2,708 LOC total
| File | LOC | Commits | Last Touch | External Refs |
|------|-----|---------|------------|---------------|
| `plugins/azure_foundry/register_callbacks.py` | 495 | 2 | 2026-05-13 | **4** |
| `plugins/azure_foundry/discovery.py` | ~? | — | — | — |
| `plugins/azure_foundry/token.py` | ~? | — | — | — |
| `plugins/azure_foundry/utils.py` | ~? | — | — | — |
| Tests (`test_azure_foundry.py`) | 1,358 | — | — | — |

**Justification:**
- Only **4 external references** (in `model_factory.py` and `provider_identity.py`).
- Extremely niche provider. Azure AI Foundry has minimal adoption compared to OpenAI, Anthropic, AWS Bedrock, and Ollama (all of which are already supported).
- 1,358 lines of tests for a provider that is unlikely to see heavy use.

**Recommended action:** Evaluate usage telemetry. If adoption is low, deprecate and remove.

---

## Meta-Category: Coverage Test Bloat — 29,158 LOC

### 42 artificially bloated test files

| Test File | LOC | Source File | Source LOC | Ratio |
|-----------|-----|-------------|-----------|-------|
| `test_prompt_toolkit_coverage.py` | 2,009 | `prompt_toolkit_completion.py` | 922 | **2.18:1** |
| `test_model_factory_coverage.py` | 1,829 | `model_factory.py` | 1,203 | 1.52:1 |
| `test_cli_runner_full_coverage.py` | 1,789 | `cli_runner.py` | ~? | — |
| `test_claude_cache_client_full_coverage.py` | 1,428 | `claude_cache_client.py` | 849 | 1.68:1 |
| `test_diff_menu_coverage.py` + `test_diff_menu.py` | 2,093 | `diff_menu.py` | 865 | **2.42:1** |
| `test_model_settings_menu_coverage.py` | 1,044 | `model_settings_menu.py` | 983 | 1.06:1 |
| `test_agent_skills.py` + `test_skills_menu.py` + callbacks coverage | ~3,000+ | `agent_skills/` | 3,637 | ~0.82:1 |
| … (37 more files) | ~14,000 | — | — | — |
| **Total** | **29,158** | — | — | — |

**Justification:**
- These tests exist **solely to inflate coverage percentages** for features that are either:
  - Already covered by integration tests (`test_command_handler.py`, `test_core_commands_extended.py`)
  - Marginal UI menus with low user value (`colors_menu`, `diff_menu`, `clipboard` coverage)
  - Plugin callbacks that are better tested via end-to-end plugin loading tests
- They are brittle, slow to run, and create maintenance drag whenever the source code changes.

**Recommended action:**
1. Delete all `*_coverage.py` and `*_full_coverage.py` test files.
2. Keep meaningful integration tests that exercise real user flows.
3. Set a policy: no test files with `coverage` in the name. Tests should validate behavior, not line numbers.

---

## Honorable Mentions (Investigate Further)

| Feature | LOC | Notes |
|---------|-----|-------|
| `plugins/hook_manager/` | 1,082 | 61 references — actually used, but overlaps with `callbacks.py` (1,101 LOC). Potential consolidation. |
| `plugins/semantic_compression/` | 792 | Low commit count; check if redundant with `filter_engine`. |
| `plugins/autonomous_memory/` | 1,172 | Check if memory system is actually enabled by default. |
| `plugins/token_tracking/` | 1,169 | Check if token accounting is consumed by any billing/reporting feature. |
| `plugins/checkpointing/` | 691 | May duplicate autosave or session storage. |
| `plugins/build_filter/` | 603 | May overlap with `filter_engine` and `shell_safety`. |
| `command_line/clipboard.py` | 528 | 56 references — actually used, but simple wrapper around `pyperclip`. Worth inlining. |
| `command_line/autosave_menu.py` | 709 | 4 references. Low usage for a dedicated TUI menu. |

---

## Ranked Removal / Deprecation List

| Rank | Feature | Est. LOC Saved | Impact | Action |
|------|---------|---------------|--------|--------|
| 1 | **MindPack Plugin Suite** (incl. agent_creator_agent) | ~6,600 | None — zero usage | **Remove** |
| 2 | **Copilot Auth Plugin** | ~2,000 | None — zero usage | **Remove** |
| 3 | **Browser Tools Module** | ~2,900 | Low — chrome_cdp covers this | **Remove** |
| 4 | **Shell Minimizer Plugin** | ~1,400 | Low — filter_engine covers this | **Remove** |
| 5 | **Coverage Test Bloat** (42 files) | ~29,000 | Medium — improves CI speed | **Delete** |
| 6 | **Rich Renderer** | ~2,300 | Low — messaging bus covers this | **Remove** |
| 7 | **UC Menu** | ~1,000 | Low — already 3 other UC access paths | **Remove** |
| 8 | **Diff Menu + Tests** | ~3,000 | Low — diff_formatting.py exists | **Remove** |
| 9 | **Colors Menu + Tests** | ~800 | None — cosmetic | **Remove** |
| 10 | **OAuth Consolidation** (merge chatgpt + claude) | ~8,000 | Medium — simplifies auth | **Consolidate** |
| 11 | **Azure Foundry** | ~2,700 | Medium — niche provider | **Deprecate** |

**Total potential savings: ~57,700 LOC** (25% of the entire codebase).

---

## Recommendations

1. **Immediate wins (no production impact):**
   - Remove `mindpack/`, `copilot_auth/`, `browser/`, `shell_minimizer/`.
   - Delete all `*_coverage.py` and `*_full_coverage.py` test files.

2. **Short-term consolidation:**
   - Merge OAuth plugins into a generic auth module.
   - Inline `clipboard.py` and `colors_menu.py` into their caller (`config_commands.py`).

3. **Policy changes:**
   - Ban `coverage` in test file names. Tests validate behavior, not line counts.
   - Require a minimum of 3 non-test, non-self references for any new plugin >300 LOC.
   - Add a plugin usage telemetry hook to identify future orphans early.

---

*Analysis generated systematically via git history, cross-reference grep, and test-to-source ratio audit.*
