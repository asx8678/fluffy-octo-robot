# MUSE Strategic Upgrades Plan
## Compression • Context Management • Agent Quality

**Status**: Draft (May 2026)  
**Scope**: Actionable 6–9 month engineering program  
**Constraint**: All new functionality delivered as plugins under `code_muse/plugins/` via `register_callbacks.py` (see AGENTS.md)  
**Tracking**: Every initiative below must be broken into `bd` issues. No markdown TODO lists for work tracking.

---

## Executive Summary

Muse's core value is **high-quality agentic coding with dramatically lower token usage** than naive LLM agents. The three highest-leverage areas for the next phase of product improvement are:

1. **Compression** — Turn the current good-but-opt-in compression systems into reliable, always-on, high-impact defaults.
2. **Context Management** — Move from reactive truncation/summarization to proactive, task-aware, structure-aware context budgets.
3. **Agent Quality** — Make the critic, reviewer, and planning systems first-class, measurable, and self-improving.

These three pillars are tightly coupled: better compression enables better context decisions, and better context enables higher-quality agent reasoning.

**Target outcomes (6–9 months)**
- 25–40% average reduction in tokens per real-world coding session (measured)
- Visible, trustworthy “context intelligence” (agents rarely blow up on huge histories)
- Critic/reviewer feedback that users actually trust and rarely override
- All changes delivered as plugins; zero permanent core bloat

---

## Guiding Principles

1. **Plugins over core** — Every new feature starts life in `code_muse/plugins/<feature>/register_callbacks.py`.
2. **Measurement before optimization** — No compression or pruning change ships without before/after token and quality data.
3. **Fail closed, degrade gracefully** — Compression or pruning must never lose critical information. When in doubt, keep the original.
4. **Agent-visible + user-visible** — Both the LLM and the human must understand what was compressed, kept, or dropped.
5. **600-line file cap** — Large plugins split into submodules (`strategies/`, `scoring/`, `models.py`, etc.).
6. **Python 3.14+ first** — Leverage subinterpreters, free-threaded awareness, and persistent event loops where they help.
7. **Use `bd` for all task tracking** — This document is the *plan*; `bd ready` + `bd show` are the *worklist*.

---

## Pillar 1: Compression

### Current State (May 2026)

- `plugins/semantic_compression/` — Rule-based (Tier 1 safe + Tier 2 aggressive). Opt-in via config. Fires only on `post_tool_call`. Good heuristics but conservative defaults.
- `plugins/build_filter/` — Solid per-tool compressors (make, cargo, npm, docker, pip, go). Verbosity levels.
- `plugins/context_aware_reader/` — AST-guided partial file reads (new, promising, under-adopted).
- Shell output filtering in `tools/command_runner.py` + `list_filtering` Cython module.
- `token_ratio_learner/` + `token_accuracy/` — Learning real token ratios per model (excellent foundation).

**Gap**: Most compression is either opt-in or narrowly scoped. The agent still sees far more tokens than necessary on common operations.

### Goals

- Semantic + structural compression **on by default** for the highest-impact tools.
- A general “smart output” layer that agents prefer over raw `read_file` / `grep`.
- Measurable, logged token savings on every session.

### Initiative 1.1 — Semantic Compression Default + Visibility (Quick Win)

**Target plugin**: Enhance `plugins/semantic_compression/`

- Change default from opt-in to “enabled for read_file, grep, shell output, and agent context tools”.
- Add strong “already compressed” detector + safety rail (never compress below N content words).
- Emit visible savings: `📦 compressed 34% (1,284 → 847 tokens)` in the message stream.
- Expose `/semantic-compression status|on|off|stats`.

**Success metric**: ≥15% of all tool-result characters passing through the compressor in normal usage.

### Initiative 1.2 — Smart Output Compressor (High Leverage)

**New plugin**: `plugins/smart_output_compressor/`

Responsibilities:
- Post-process `read_file`, `grep`, `list_files`, `glob` results.
- For source files: keep imports + signatures + focus areas; elide function bodies not relevant to current task.
- For command output: apply build_filter + semantic + structural rules in a unified pipeline.
- Register a preferred tool `read_smart` (or make `read_file` context-aware via hook).

Depends on: `context_aware_reader/ast_relevance.py` + task_context signals.

**Phase 1** (4 weeks): Heuristic + tree-sitter based for Python/TS/Go.  
**Phase 2**: Learn from actual agent usage (which sections were actually used later in the session).

### Initiative 1.3 — Unified Compression Engine + Telemetry

**New supporting module** (inside a shared `compression/` support package or a small core-adjacent plugin):

- Common `CompressionResult` model (original_len, compressed_len, strategy, confidence, reversible).
- Every compressor must emit the same shape so `/compression-stats` and the token ledger can aggregate.
- Add a `compression_applied` event on the messaging bus.

### Initiative 1.4 — Learned / Adaptive Compression (Medium-term)

Extend `token_ratio_learner/` + `token_accuracy/` into a feedback loop:
- Record (prompt_segment, compressed_segment, model, actual_tokens_saved, was_useful).
- Periodically propose new rules or deprecate weak ones.
- Optional: tiny local classifier for “worth compressing this output?”.

---

## Pillar 2: Context Management

### Current State

- `agents/_compaction.py` + `_history.py` — Mature truncation + protected-tail + optional LLM summarization. `CompactionCache` is excellent.
- `plugins/task_context/` — New (task lifecycle, scoring, pruning, archival). Hooks `message_history_processor_start`. Promising but early.
- `plugins/context_aware_reader/` — `read_relevant_code` tool exists and returns the correct `ReadFileOutput` shape.
- `summarization_agent.py` — Separate model path; can be expensive and occasionally fails.

**Gap**: Context decisions are still mostly reactive (hit limit → truncate/summarize). The system does not yet maintain an explicit, queryable model of “what matters for the current task”.

### Goals

- Agents **prefer** structure-aware partial reads by default.
- Task boundaries are first-class and drive pruning + recall decisions.
- Compaction is cheap-first, LLM-last, with strong provenance.

### Initiative 2.1 — Make `read_relevant_code` the Default Path (Quick Win + High Impact)

**Plugin**: `plugins/context_aware_reader/`

- Add strong system-prompt language (via `load_prompt`) telling the main agent and specialist agents to call `read_relevant_code` (with `focus_areas` derived from current task) instead of `read_file` when they only need part of a file.
- Auto-extract focus areas from the active `TaskContext` (see 2.2).
- Add a `/read-relevant` command and make it discoverable.
- Measure adoption rate (how often the agent chooses it vs raw `read_file`).

**Target**: Within 2 months, ≥60% of file reads in typical coding sessions use the relevant-code path.

### Initiative 2.2 — Strengthen Task Context as the Central Context Budget Authority

**Plugin**: `plugins/task_context/`

Current pieces (`task_manager.py`, `pruner.py`, `scorer.py`, `detector.py`) are good scaffolding.

Next work:
- **Better task detection** — Combine commit messages, file clusters, explicit `/task start`, and LLM signals.
- **Dependency graph** — Record “Task B touched files that Task A also touched.” Use for intelligent recall.
- **Token-aware scoring** — Replace or augment the current scorer with real tokenizer counts (via `token_accuracy` plugin).
- **Proactive pruning** — Instead of only reacting at `message_history_processor_start`, run a cheap background scorer every N turns and surface “Context budget at 78%. Consider archiving Task T3?” to the user.
- **Recall UX** — `/task recall <id>` injects a compact, human-readable + LLM-usable summary of an archived task (not raw messages).

### Initiative 2.3 — Cheap-First History Compaction

Enhance the compaction pipeline (`agents/_compaction.py` + new helpers in a `plugins/context_compaction/` support plugin):

1. Heuristic / extractive pass (pull decisions, file paths, error signatures, key outputs).
2. Structural pass (drop duplicated tool results, collapse repetitive exploration).
3. Semantic compression pass (reuse Pillar 1 engine).
4. LLM summarization **only** as last resort, using the cheapest viable model, with strong caching by content hash.

Add `CompactionDecision` provenance objects so the user can ask “why was this message dropped?”

### Initiative 2.4 — Context Budget Dashboard

New small plugin or extension: `plugins/context_dashboard/`

`/context` or `/status context` shows:
- Current session token spend vs model limit
- Per-task breakdown (active vs archived)
- Recent compaction / compression events with savings
- Projected turns remaining before hard limit

---

## Pillar 3: Agent Quality

### Current State

- `agents/agent_muse.py`, `critic_light_agent.py`, `critic_heavy_agent.py`
- `plugins/code_critic/` — Strict reviewer returning approved/rejected + detailed feedback. Already has early truncation detection.
- `plugins/universal_critic/` — Orchestrator + routing.
- `plugins/debate/` — Multi-persona review.
- `plugins/auto_review/` — Watches file changes and triggers review.
- Planning agent + agent-creator.

**Gap**: Critics are powerful but fragmented. Feedback quality varies. There is almost no closed-loop learning from “user accepted / overrode / ignored the review.”

### Goals

- One coherent “critic fabric” that different surfaces (auto-review, explicit `/review`, sub-agent escalation) can all use.
- Every review produces structured, machine-readable + human-readable output.
- The system learns which reviewer signals are actually predictive of user acceptance.

### Initiative 3.1 — Unify & Harden the Critic Path (Foundation)

- Create (or designate) `plugins/critic_fabric/` as the single place that owns:
  - `CriticRequest` / `CriticVerdict` models
  - Early truncation + structural sanity checks (Python `ast.parse` + language-specific heuristics for JS/Go/Rust/Zig/etc.)
  - Pluggable reviewer backends (light, heavy, debate, user-defined)
- Move the best parts of `code_critic/reviewer.py`, `universal_critic/orchestrator.py`, and `debate/` into this fabric over time.
- Make the existing `code_critic` and `debate` plugins thin adapters on top of the fabric.

**Immediate sub-task**: Strengthen the truncation detector that was the source of the recent `UnexpectedModelBehavior` and expensive critic calls. Make it run *before* any LLM critic invocation.

### Initiative 3.2 — Structured Review Output + Provenance

Every verdict must include:
- `verdict`: approved | rejected | needs_changes
- `reasons`: list of machine-readable codes + human text
- `locations`: file + line ranges
- `confidence` + `reviewer_id`
- `review_hash` for caching

Store reviews (with content hash of the reviewed artifact) so we can detect “we already reviewed an identical version.”

### Initiative 3.3 — Closed-Loop Learning from User Response

New small plugin `plugins/critic_learning/` (or inside the fabric):

- On user edit after a review, diff the review suggestions against what the user actually did.
- Record “this rejection reason was acted on” vs “ignored”.
- Use the signal to:
  - Re-weight reviewer prompts
  - Demote noisy rules
  - Surface “reviewers you trust most” in `/safety` or `/reviewers`

This is the highest long-term leverage item in the entire plan.

### Initiative 3.4 — Planning Agent Upgrade

- Make plans first-class structured objects (not free text).
- Add plan validation step (does every step have a verification criterion?).
- Allow the planner to call `read_relevant_code` and the new smart compressor when building the plan.
- Store plans with tasks in `task_context/` so later critics can check “did we follow the plan?”

---

## Cross-Cutting: Measurement & Observability (Do This First)

You cannot improve what you do not measure. This work enables everything above.

**Recommended first plugin**: `plugins/upgrade_metrics/`

Capabilities:
- Session-level ledger: tokens in, tokens after each compression stage, tokens after compaction, tokens after critic passes.
- Event stream: `compression_applied`, `context_pruned`, `review_verdict`, `task_archived`.
- Persistence: append-only JSONL under `~/.muse/metrics/` (or SQLite) with rotation.
- Query commands: `/metrics compression`, `/metrics context`, `/metrics quality`.
- Export for later analysis.

Wire this early. Every subsequent initiative should add 2–3 lines of instrumentation using the same event shape.

---

## Phased Roadmap (Illustrative)

| Phase | Duration | Focus | Flagship Deliverables | Must-Have Metrics |
|-------|----------|-------|-----------------------|-------------------|
| **0 — Foundations** | 2–3 weeks | Measurement + quick defaults | `upgrade_metrics` plugin, semantic compression default-on for top 4 tools, truncation detector hardening | Token savings % visible, no regression in review false-negative rate |
| **1 — Compression Wins** | 4–5 weeks | 1.1 + 1.2 | `smart_output_compressor/` v1, `read_relevant_code` strongly preferred in prompts | ≥25% median token reduction on file-heavy sessions |
| **2 — Context Intelligence** | 5–6 weeks | 2.2 + 2.3 | Task dependency graph + cheap-first compaction + `/context` dashboard | Context budget prediction error < 15% |
| **3 — Quality & Learning** | 6–8 weeks | 3.1 + 3.3 | Critic fabric + structured verdicts + initial closed-loop signals | Reviewer acceptance rate tracked and improving |
| **4 — Polish & Self-Improvement** | Ongoing | 1.4 + 3.4 + 2.4 | Learned compression rules, planning structure, critic learning loop | Sustained 30%+ token efficiency gain + rising critic precision |

---

## Success Metrics (Quantitative Targets)

**Compression**
- Median tokens per 10k lines of edited code drops ≥30% vs baseline (measured via `upgrade_metrics`)
- Semantic compression applied to ≥40% of eligible tool outputs

**Context**
- % of sessions that hit hard context limit without graceful compaction < 5%
- `read_relevant_code` used in >50% of file-context requests

**Agent Quality**
- False-negative rate on truncated code in critic < 1% (currently a known pain point)
- User override rate on auto-reviews tracked and trending down
- At least one “reviewer learning” signal collected per 20 reviews

**Overall**
- Average session token spend (model + tools) down 25–40% with no increase in user friction or correctness regressions

---

## Implementation Guidelines

1. **Every initiative owns its plugin directory**  
   `code_muse/plugins/<kebab-name>/register_callbacks.py` is the single registration point.

2. **Split early**  
   `models.py`, `config.py`, `engine.py` / `strategies/`, `scoring/`, `telemetry.py` are the usual good boundaries.

3. **Reuse existing contracts**
   - `ReadFileOutput`
   - `CompactionCache` + `estimate_tokens`
   - `ShellCommandOutput`
   - The messaging bus events

4. **Instrumentation is mandatory**  
   New compression or pruning logic must emit the standard `upgrade_metrics` events.

5. **Tests live with the plugin**  
   `tests/plugins/<name>/` — use the existing test patterns (many good examples already exist).

6. **Linters before every commit**  
   `ruff check --fix && ruff format .`

7. **Work tracking**  
   `bd new "Semantic compression default for read/grep" --priority high`  
   Then `bd update <id> --claim` when you start.

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Over-compression loses critical information | Medium | Strong “reversible” flag + user-visible provenance + easy “show original” command |
| Task detection is noisy | Medium | Make tasks user-overrideable; never auto-archive without confirmation or very high confidence |
| Critic learning creates feedback loops that reinforce bad style | Low | Keep a human-in-the-loop “trust this reviewer” step for the first 3–6 months |
| Measurement overhead becomes visible | Low | Keep the metrics plugin lightweight; default to sampling if needed |
| Plugin surface area grows too large | Medium | Enforce 600-line cap ruthlessly and extract shared support packages under `code_muse/plugins/_support/` if necessary |

---

## How to Use This Document

1. Run `bd prime` to get current context.
2. Create one `bd` issue per initiative (or per major sub-task).
3. Start with **Phase 0** (measurement + semantic compression defaults + truncation hardening). These are the highest-confidence, lowest-risk wins.
4. Revisit this document after each phase and update the “Current State” sections.

This is not a wishlist. It is an engineering program designed to be executed inside the existing Muse plugin architecture while producing measurable, compounding improvements in the three areas that matter most to users and token budgets.

---

*Last updated: May 2026 — Draft for team review*