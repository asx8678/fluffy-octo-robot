"""Debate Mode plugin for Muse — checkpoint-gated reasoning.

A plugin where the primary planning model thinks in discrete proposals,
voluntarily calls a ``request_review`` tool at the end of each proposal,
and a second verifier model returns a structured verdict.  The planner
then continues or revises based on that verdict.

Architecture
------------
File structure under ``code_muse/plugins/debate/``:

- ``schemas.py``      — Pydantic models (Verdict, ReviewRequest, ReviewResponse)
- ``config.py``       — Configuration accessors (muse.cfg)
- ``state.py``        — Session state & budget tracking
- ``reviewer.py``     — Reviewer LLM caller
- ``ui.py``           — Terminal rendering
- ``telemetry.py``    — Latency and verdict metrics
- ``register_callbacks.py`` — Hook & tool registration
- ``prompts/``        — Prompt templates for planner and reviewer

Key Design Decisions
--------------------
1. ``request_review`` is a REAL tool — the tool function itself calls
   the reviewer LLM and returns the verdict.
2. ``pre_tool_call`` hook is used ONLY for gating (budget enforcement,
   loop detection) — returns ``{'blocked': True}`` when limits are hit.
3. Zero core Muse files modified — plugin only.
"""

from code_muse.plugins.debate.config import (
    get_debate_max_loops,
    get_debate_max_reviews,
    get_debate_reviewer_model,
    is_debate_enabled,
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
    "get_debate_reviewer_model",
    "get_debate_max_reviews",
    "get_debate_max_loops",
    # State
    "DebateState",
]
