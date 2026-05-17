# Threat Model: Blackboard & Experience Store

## System Overview

The **blackboard** is shared mutable state between agents (typed artifacts
with scope/TTL). The **experience store** persists solution capsules across
sessions. Both introduce a new attack surface: shared state + cross-run
memory.

## Assets

| Asset | Description |
|-------|-------------|
| Blackboard artifacts | Typed data (DesignDoc, BugReport, PartialSolution…) posted by agents |
| Experience capsules | Distilled outcomes from completed tasks, stored long-term |
| Agent identity | Which agent produced an artifact (provenance) |
| Repo/workspace context | The git repo root or workspace ID an artifact belongs to |
| Session history | Sub-agent conversation histories (already persisted) |

## Threat Actors

| Actor | Capability | Motivation |
|-------|-----------|------------|
| Malicious prompt injection | Controls a sub-agent via crafted user input | Read other-scope data, poison the experience index |
| Compromised user plugin | Runs arbitrary Python in-process | Direct access to in-memory blackboard, bypass all guards |
| Rogue sub-agent | Legitimate agent given adversarial instructions | Post misleading artifacts, exfiltrate cross-scope data |
| Accident / bug | Unintentional cross-scope write | Data corruption, privacy leak |

## Threats & Mitigations

### T1: Cross-scope data exfiltration
**Scenario**: Agent A in repo-X reads artifacts from repo-Y.
**Impact**: Privacy leak, cross-project contamination.
**Mitigation**: Scope enforcement — artifacts are tagged with a scope
(repo root hash by default). `read_artifact()` checks caller scope against
artifact scope. Cross-scope reads require an explicit policy exception.
**Residual risk**: In-process plugins can bypass Python-level checks.
Documented as a known limitation; process-level isolation is Phase 2.

### T2: Prompt injection via blackboard artifacts
**Scenario**: A malicious artifact contains instructions that trick a
consumer agent into unsafe actions.
**Impact**: Agent executes unintended commands.
**Mitigation**: All artifacts are tagged with `provenance` (agent_name,
task_id, timestamp). Consumer agents receive artifacts in a structured
format (not raw text injection). The `load_prompt` hook can sandbox
blackboard content behind a clear delimiting section.
**Residual risk**: LLM may still follow instructions in artifact content.
Mitigated by provenance visibility (agent can see *who* posted).

### T3: Experience store poisoning
**Scenario**: Low-quality or adversarial capsules are stored and later
retrieved as "solutions", leading agents astray.
**Impact**: Degraded agent quality, wasted tokens.
**Mitigation**: Capsules carry provenance (agent + task + confidence).
Retrieval scoring penalises low-confidence or unreviewed capsules.
A quality threshold is enforced: only capsules from completed tasks
with `confidence >= 0.7` are indexed for retrieval.
**Residual risk**: A compromised agent with high confidence scores can
still inject. Mitigated by human-visible provenance.

### T4: Cross-project leakage via experience retrieval
**Scenario**: Agent working in repo-X retrieves a capsule from repo-Y
that contains sensitive path fragments.
**Impact**: Privacy leak.
**Mitigation**: Capsules are scoped to repo by default. Path redaction
applies `security.redaction.redact_secrets` before storage. Cross-repo
retrieval is opt-in only.
**Residual risk**: Redaction may miss novel sensitive patterns.
Documented; user can purge capsules per-repo.

### T5: Plugin bypass of scope enforcement
**Scenario**: A user plugin directly accesses the in-memory blackboard
dict, bypassing the capability check.
**Impact**: Complete scope enforcement bypass.
**Mitigation**: The blackboard is not a public module attribute. Access
is mediated through the `blackboard_read`/`blackboard_write` tool
functions which enforce scope. This is a Python-level, not
process-level, guarantee.
**Residual risk**: Determined in-process code can reach the private
dict. Documented as a known limitation. Cryptographic isolation or
separate process would be needed for full protection (Phase 2).

## Accepted Limitations (Phase 1)

1. **In-process trust boundary**: All plugins share the same Python
   process. A malicious plugin can bypass Python-level guards. The
   trust model assumes the `plugin_trust` system is the gate for which
   plugins run at all.
2. **No cryptographic provenance**: Artifact provenance is metadata,
   not signed. A compromised agent could forge it. Signing is deferred
   to Phase 2.
3. **No rate limiting**: An agent can post unlimited artifacts. TTL
   and memory caps prevent unbounded growth, but not flooding.
4. **No audit log**: Events are emitted to `upgrade_metrics` but there
   is no separate tamper-proof audit log. Phase 2 item.

## Review Notes

This threat model was created as part of Initiative 4.0 (z30.0) and
should be reviewed before 4.2 (blackboard) or 4.3 (experience store)
are marked complete. Limitations are accepted for Phase 1 with the
understanding that they are documented and mitigated by defence in
depth (plugin trust + scope enforcement + provenance visibility).
