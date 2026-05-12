# MindPack — Developer Usage Guide

MindPack is a multi-expert advisory plugin for Muse. When an executor agent hits a non-trivial problem, it calls the `ask_mindpack` tool to spin up a panel of domain-specific expert sub-agents, collect their structured reports, and merge them via an LLM judge into a single, ranked advisory output.

Use `ask_mindpack` when:

- You need **multiple perspectives** (architecture vs. risk vs. testing).
- The problem is **ambiguous** or has several viable approaches.
- You want a **ranked comparison of options** before committing.
- A single obvious action does not suffice.

Do **not** use it for simple edits, one-shot lookups, or direct user requests with an obvious answer — it is expensive (multiple LLM calls per invocation).

---

## Plugin Anatomy

All source lives under `code_muse/plugins/mindpack/`:

| File | Purpose |
|------|---------|
| `__init__.py` | Empty — marks the directory as a Python package. |
| `schemas.py` | Shared Pydantic models: `ExpertDescriptor`, `AskMindPackInput`, `AskMindPackOutput`, `MindPackRankedOption`. Pure data contracts — no logic. |
| `memory.py` | `ExpertReport` model + `ReportStore`. In-memory, session-scoped buffer that collects expert reports during a consultation and clears them afterwards. |
| `factory.py` | `ExpertAgentFactory` — builds and runs a **read-only** pydantic-ai sub-agent per expert. Includes prompt builder (`build_expert_prompt`) and a read-only tool allow-list. |
| `judge.py` | `JudgeAgentFactory` + `LLMJudgeMerger` — creates a Judge sub-agent that reviews all expert reports and produces a unified `AskMindPackOutput`. Includes `build_judge_prompt` and graceful fallback logic. |
| `orchestration.py` | `MindPackOrchestrator` — the lifecycle manager. Selects experts, spawns them, collects reports, invokes the judge merger, and cleans up. Also defines `ExpertSelector` and `JudgeMerger` abstract strategies. |
| `tools.py` | Registers the singleton orchestrator, loads the five default experts, and defines the `ask_mindpack` tool function. Re-exports key schema types for backward compat. |
| `register_callbacks.py` | Plugin entry point. Hooks into Muse's `register_tools` callback to expose `ask_mindpack` to agents. |

### Data flow

```text
ask_mindpack(input)
    │
    ▼
MindPackOrchestrator.consult()
    │
    ├─ ExpertSelector.select()          ← picks subset of experts
    │
    ├─ ExpertAgentFactory.invoke_expert() ×N
    │   └─ read-only sub-agent → ExpertReport
    │
    ├─ ReportStore.add_report()         ← buffers reports
    │
    ├─ LLMJudgeMerger.merge()           ← judge sub-agent
    │   └─ JudgeAgentFactory.invoke_judge()
    │       └─ AskMindPackOutput
    │
    └─ ReportStore.clear_session()
```

All expert and judge sub-agents are **read-only**: they can list files, read code, and grep, but they never create, edit, delete, or shell out. The executor retains full agency — MindPack only advises.

---

## Usage Examples

### Defining a new expert type

To add a new expert, create an `ExpertDescriptor` and register it on the orchestrator **before** any consultation runs:

```python
from code_muse.plugins.mindpack.schemas import ExpertDescriptor
from code_muse.plugins.mindpack.tools import orchestrator

my_expert = ExpertDescriptor(
    name="DBA",
    speciality="database schema & query optimisation",
    system_prompt_fragment=(
        "You are DBA, the database specialist. Your job is to "
        "review schema migrations, identify slow queries, and "
        "recommend indexing strategies. Focus on correctness and "
        "performance, and flag any data-loss risks."
    ),
)

orchestrator.register_expert(my_expert)
```

The `name` must be unique across the registry. `speciality` is used in the expert's system prompt header. `system_prompt_fragment` is injected directly — write it as instructions to the expert persona. Optionally set `max_experts_override` to cap how many experts of this type can be spawned in a single consultation.

### Calling ask_mindpack (from an agent's perspective)

The tool is available to any Muse agent that has MindPack loaded. A typical call:

```python
result = ask_mindpack(
    problem_statement="The migration is dropping a NOT NULL column without a default, which will fail on PostgreSQL 14+",
    current_goal="Ship the database migration safely",
    current_plan="ALTER TABLE users DROP COLUMN middle_name",
    what_has_been_tried=["Running migration directly — got constraint violation"],
    relevant_files=["migrations/0042_drop_middle_name.py", "app/models/user.py"],
    observed_errors=["NotNullViolation: column middle_name contains null values"],
    desired_output="compare_options",
    max_experts=3,
)
```

`result` is an `AskMindPackOutput` with:

| Field | What you get |
|-------|-------------|
| `summary` | High-level advisory summary |
| `recommended_plan` | Judge-merged recommended action |
| `ranked_options` | Up to 3 ranked alternatives (best first) |
| `risks` | Consolidated risk list |
| `tests_to_run` | Suggested validation steps |
| `files_to_inspect_or_change` | Files experts recommend touching |
| `expert_consensus` | What experts agreed on |
| `disagreements` | Key divergences between experts |
| `confidence` | Overall confidence 0–1 |

### The `desired_output` parameter

| Value | Use when |
|-------|----------|
| `plan` | You need a step-by-step action plan (default) |
| `review` | You want a critical review of an existing approach |
| `debug_strategy` | You're stuck on a bug and need a debugging roadmap |
| `architecture_decision` | You're weighing structural alternatives |
| `test_strategy` | You need a validation / test design |
| `compare_options` | You want ranked alternatives with pros/cons |

---

## Maintenance

### Updating the judge prompt

The judge's system prompt lives in `code_muse/plugins/mindpack/judge.py` as the `_JUDGE_SYSTEM_PROMPT` constant. Edit it there to change how the judge synthesises reports. Key sections:

- **CRITICAL CONSTRAINTS** — enforces read-only mode; keep this intact.
- **YOUR TASK** — defines the seven-step synthesis process.
- **SYNTHESIS GUIDELINES** — controls how disagreements are resolved and confidence is computed.

After editing, re-run the tests (see below) to verify nothing broke. No other file references the prompt constant directly.

### Updating the expert registry

**Default experts** are defined in `tools.py` in the `_DEFAULT_EXPERTS` list. To change the out-of-the-box panel, edit that list. Each entry is an `ExpertDescriptor`.

To **add experts at runtime** (e.g. from another plugin), import the singleton and call `register_expert`:

```python
from code_muse.plugins.mindpack.tools import orchestrator
from code_muse.plugins.mindpack.schemas import ExpertDescriptor

orchestrator.register_expert(ExpertDescriptor(
    name="Perf",
    speciality="runtime performance & profiling",
    system_prompt_fragment="You are Perf, the performance analyst…",
))
```

To **replace the entire expert selection strategy**, subclass `ExpertSelector` and inject it:

```python
from code_muse.plugins.mindpack.orchestration import ExpertSelector, MindPackOrchestrator

class SemanticExpertSelector(ExpertSelector):
    def select(self, request, registry):
        # Your smarter logic here — e.g. embed request + match to speciality
        return registry[:3]

orchestrator = MindPackOrchestrator(expert_selector=SemanticExpertSelector())
```

To **swap the merger** (e.g. use a rule-based merger instead of LLM), implement `JudgeMerger`:

```python
from code_muse.plugins.mindpack.orchestration import JudgeMerger, MindPackOrchestrator

class RuleBasedMerger(JudgeMerger):
    async def merge(self, request, reports, session_id):
        # Deterministic merge logic
        ...

orchestrator = MindPackOrchestrator(judge_merger=RuleBasedMerger())
```

---

## Testing

All MindPack tests live in `tests/plugins/test_mindpack.py`. They exercise the structural integrity of the pipeline **without calling an LLM** — factory construction, prompt building, report extraction, orchestrator wiring, and the placeholder merger.

### Run the full test suite

```bash
python -m pytest tests/plugins/test_mindpack.py -v
```

### Run a single test class

```bash
python -m pytest tests/plugins/test_mindpack.py::TestBuildExpertPrompt -v
```

### Run with coverage

```bash
python -m pytest tests/plugins/test_mindpack.py --cov=code_muse.plugins.mindpack --cov-report=term-missing
```

### Test structure

| Class | What it covers |
|-------|---------------|
| `TestExpertDescriptor` | Schema defaults and field assignment |
| `TestReadOnlyTools` | No write tools leaked into the read-only allow-list |
| `TestBuildExpertPrompt` | Prompt includes problem, files, errors; optional fields omitted |
| `TestExpertAgentFactory` | Model resolution, fallback report, structured/text/None extraction |
| `TestMinimalAgentProxy` | Proxy name and model name resolution |
| `TestOrchestratorWiring` | DI, expert registration, spawn-and-collect, error fallback |
| `TestPlaceholderJudgeMerger` | Merge produces valid output, confidence averaging, disagreements |
| `TestDefaultExpertSelector` | Select all vs. capped selection |

### Adding new tests

When adding a new expert type or modifying the judge prompt, add tests that validate:

1. **Prompt content** — does the built prompt include your new fields?
2. **Read-only safety** — no write tools appear in `READ_ONLY_TOOLS` or `JUDGE_READ_ONLY_TOOLS`.
3. **Fallback behaviour** — does the orchestrator still produce valid output when a factory or judge throws?
4. **Schema validation** — does your new `ExpertDescriptor` round-trip correctly?

---

## Architecture Notes

- **Read-only guarantee**: Both `READ_ONLY_TOOLS` (experts) and `JUDGE_READ_ONLY_TOOLS` (judge) are explicit allow-lists. Adding a write-capable tool to either list would violate the advisory-only contract. Tests in `TestReadOnlyTools` enforce this.
- **Graceful degradation**: Every layer (expert factory → orchestrator → judge merger) catches exceptions and returns a valid but low-confidence fallback. The executor always receives an `AskMindPackOutput`, never a crash.
- **No recursion guard needed**: Expert and judge agents do not have `ask_mindpack` in their tool set, so recursive consultation is impossible by construction.
- **Ephemeral sessions**: Each `consult()` call gets a unique session ID. The `ReportStore` buffers reports for that session and clears them when the consultation completes. No data persists between consultations.
- **Singleton orchestrator**: `tools.py` creates one `MindPackOrchestrator` instance at import time and registers the five default experts. All `ask_mindpack` calls flow through this singleton. If you need isolated orchestrators (e.g. for testing), construct `MindPackOrchestrator()` directly with injected dependencies.
