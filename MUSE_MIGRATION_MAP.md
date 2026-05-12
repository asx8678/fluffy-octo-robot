# MUSE_MIGRATION_MAP — Complete Rebrand Plan

## Source: muse / Muse → Target: Muse

---

## Phase 1: Package Rename (code_muse → code_muse)

### Files to rename
| Old Path | New Path | Impact |
|----------|----------|--------|
| `code_muse/` | `code_muse/` | Root package — all imports break |
| `code_muse/agents/agent_code_muse.py` | `code_muse/agents/agent_muse.py` | Class `CodePuppyAgent` → `MuseAgent` |
| `code_muse/agents/agent_qa_kitten.py` | `code_muse/agents/agent_qa_melpomene.py` | Class `QualityAssuranceKittenAgent` → `QualityAssuranceMelpomeneAgent` |

### Imports to update (700+ files)
- `from code_muse.*` → `from code_muse.*`
- `import code_muse.*` → `import code_muse.*`
- Test files: all `tests/*.py` import from `code_muse`

---

## Phase 2: Structural Constants & Config

| Constant | Old Value | New Value | File(s) |
|---|---|---|---|
| `DEFAULT_SECTION` | `"puppy"` | `"muse"` | `config.py`, `config_agent.py`, `config_model.py`, `config_commands.py` |
| `CONFIG_FILE` | `puppy.cfg` | `muse.cfg` | `config.py` |
| `_MUSE_DIR` | `".muse"` | `".muse"` | `_builder.py` |
| `get_puppy_name()` | function name | `get_agent_name()` | `config.py` + all callers |
| `get_owner_name()` | function name | `get_owner_name()` (keep) | `config.py` + callers |
| `code_muse_overlay()` | function name | `muse_overlay()` | `prompt_v3.py` + callers |
| `load_puppy_rules()` | function name | `load_muse_rules()` | `_builder.py` + callers |

### Config directory paths
| Old Path | New Path | Files |
|---|---|---|
| `~/.muse/` | `~/.muse/` | `config.py` (get_xdg_dir fallback) |
| `.muse/` | `.muse/` | `_builder.py`, `json_agent.py`, `skills/`, docs |
| `~/.muse/` | `~/.muse/` | `checkpointing/`, `autonomous_memory/`, `custom_commands/`, `policy_engine/`, `token_tracking/`, `filter_engine/` |

### Environment variables
| Old | New | Files |
|---|---|---|
| `MUSE_DISABLE_RETRY_TRANSPORT` | `MUSE_DISABLE_RETRY_TRANSPORT` | `http_utils.py`, tests |
| `MUSE_DISABLE_TLS_VERIFY` | `MUSE_DISABLE_TLS_VERIFY` | `http_utils.py`, tests |
| `MUSE_NO_TUI` | `MUSE_NO_TUI` | `loop.py`, tests |
| `MUSE_NO_COLOR` | `MUSE_NO_COLOR` | `common.py` |
| `MUSE_TEST_FAST` | `MUSE_TEST_FAST` | tests |
| `MUSE_SKIP_TUTORIAL` | `MUSE_SKIP_TUTORIAL` | `onboarding_wizard.py`, tests |
| `MUSE_PLUGIN_TRUST_MANIFEST` | `MUSE_PLUGIN_TRUST_MANIFEST` | `plugins/__init__.py`, tests |
| `MUSE_TRUST_ALL_USER_PLUGINS` | `MUSE_TRUST_ALL_USER_PLUGINS` | `plugins/__init__.py`, tests |
| `MUSE_USE_INTERPRETER_POOL` | `MUSE_USE_INTERPRETER_POOL` | `universal_constructor/runner.py` |
| `MUSE_KEEP_TEMP_HOME` | `MUSE_KEEP_TEMP_HOME` | test harness |
| `MUSE_SELECTIVE_CLEANUP` | `MUSE_SELECTIVE_CLEANUP` | test harness |

---

## Phase 3: Project Metadata (pyproject.toml → pyproject.toml)

| Field | Old | New |
|---|---|---|
| `[project].name` | `"code-muse"` | `"code-muse"` |
| `[project].description` | `"Code generation agent"` | `"Muse — eternal guide of creators in the arts and sciences. An elegant AI coding assistant."` |
| `[project].scripts` | `code-muse`, `code-puppy`, `pup` | `muse` |
| `[project.urls].Repository` | `github.com/asx8678/muse` | `github.com/asx8678/muse` |
| `[tool.hatch.build].packages` | `["code_muse"]` | `["code_muse"]` |
| `[tool.mypy].files` | `["code_muse"]` | `["code_muse"]` |
| All hatch sdist includes | `code_muse/...` | `code_muse/...` |

---

## Phase 4: Agent Name & Display Changes

| Agent File | Old Name | Old Display | New Name | New Display |
|---|---|---|---|---|
| `agent_muse.py` (was agent_code_muse.py) | `code-puppy` | `Muse` | `muse` | `Muse` |
| `agent_qa_melpomene.py` (was agent_qa_kitten.py) | `qa-kitten` | `Quality Assurance Kitten` | `qa-melpomene` | `Quality Assurance Melpomene` |
| `agent_manager.py` default | `"code-puppy"` | - | `"muse"` | - |

---

## Phase 5: Token Replacements in Strings & Docs

### Tone shifts in prompts
| Old | New |
|---|---|
| `"The most loyal digital puppy"` | `"The divine guide of creators"` |
| `"Advanced web browser automation — Web Browser Puppy"` | `"Advanced web browser automation — Melpomene's browser"` |
| `"angry puppies"` (README) | Remove/replace with graceful phrasing |
| `"woof"` examples | Replace with `"thus"` or remove |
| `"bark"`, `"tail wag"` | Remove |

### Image assets
| Old | New |
|---|---|
| `code_muse.gif` | `muse.gif` |
| `code_muse.png` | `muse.png` |

---

## Phase 6: Documentation Rewrites

| File | Changes |
|---|---|
| `README.md` | Replace all branding, tone, taglines. Keep technical content. |
| `AGENTS.md` | Replace path references + branding |
| `CONTRIBUTING.md` | Replace path references + branding |
| `FEATURES.md` | Replace branding |
| `docs/AGENT_SKILLS.md` | Replace all `~/.muse/` with `~/.muse/` |
| `docs/HOOKS.md` | Replace paths |
| `docs/SECURITY.md` | Replace env var names + paths |
| `docs/TESTING.md` | Replace env var names + paths |
| `docs/RELEASING.md` | Replace package name |
| `docs/MIND_PACK.md` | Replace branding |

---

## Execution Order

1. **Package directory rename**: `code_muse/` to `code_muse/`
2. **Agent file renames**: `agent_code_muse.py` to `agent_muse.py`, `agent_qa_kitten.py` to `agent_qa_melpomene.py`
3. **Global import update**: `from code_muse` to `from code_muse` in all .py files
4. **Config constants**: `DEFAULT_SECTION`, `CONFIG_FILE`, path dirs, env vars
5. **Function/variable renames**: `get_puppy_name`, `code_muse_overlay`, `load_puppy_rules`, `_MUSE_DIR`
6. **pyproject.toml**: Project name, scripts, hatch config
7. **Documentation + strings**: README, AGENTS.md, docs/, tone shifts
8. **Image assets + root folder rename**
9. **Validation**: Import check, CLI check, test run, grep for remaining terms
