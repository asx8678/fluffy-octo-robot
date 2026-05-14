"""Debate Mode plugin for Muse — checkpoint-gated reasoning.

A plugin where the primary planning model thinks in discrete proposals,
voluntarily calls a ``request_review`` tool at the end of each proposal,
and a second verifier model returns a structured verdict.  The planner
then continues or revises based on that verdict.

Architecture
------------
File structure under ``code_muse/plugins/debate/``:

- ``schemas.py``      — Pydantic models (Verdict, ReviewRequest, ReviewResponse)
- ``config.py``       — Configuration accessors (muse.cfg) + toggle
- ``state.py``        — Session state, budget, agent-run tracking, review history
- ``reviewer.py``     — Reviewer LLM caller (pydantic-ai Agent)
- ``ui.py``           — Terminal rendering: verdicts, progress, history, status
- ``telemetry.py``    — Latency, verdict metrics, NDJSON logging, success rates
- ``register_callbacks.py`` — Hook & tool registration, slash commands
- ``prompts/``        — Prompt templates for planner and reviewer

Key Design Decisions
--------------------
1. ``request_review`` is a REAL tool — the tool function itself calls
   the reviewer LLM and returns the verdict.
2. ``pre_tool_call`` hook is used ONLY for gating (budget enforcement,
   loop detection) — returns ``{'blocked': True}`` when limits are hit.
3. ``load_prompt`` hook injects the planner addendum into the system
   prompt when debate mode is enabled — tells the planner it must
   call ``request_review`` after each proposal.
4. ``agent_run_start`` / ``agent_run_end`` hooks track the agent lifecycle
   so the debate state knows when reviews are in-context.
5. Terminal UI uses Muse standard emit functions (``emit_info``,
   ``emit_success``, ``emit_warning``) — no Rich Live/Console
   allocations from plugin code.
6. Telemetry writes NDJSON lines to ``~/.muse/state/debate_telemetry.jsonl``
   for offline analysis, plus in-memory session snapshots.
7. ``/debate`` slash commands: ``on``, ``off``, ``toggle``, ``status``,
   ``stats``, ``metrics``, ``history``, ``reset`` — all wired through
   ``custom_command`` and ``custom_command_help`` hooks.
8. Zero core Muse files modified — plugin only.
"""

from code_muse.plugins.debate.config import (
    get_debate_max_loops,
    get_debate_max_reviews,
    get_debate_reviewer_model,
    is_debate_enabled,
    set_debate_enabled,
)
from code_muse.plugins.debate.schemas import (
    Issue,
    ReviewRequest,
    ReviewResponse,
    Verdict,
    VerdictKind,
)
from code_muse.plugins.debate.state import DebateState

__all__ = [
    # Schemas
    "Issue",
    "ReviewRequest",
    "ReviewResponse",
    "Verdict",
    "VerdictKind",
    # Config
    "is_debate_enabled",
    "set_debate_enabled",
    "get_debate_reviewer_model",
    "get_debate_max_reviews",
    "get_debate_max_loops",
    # State
    "DebateState",
]
