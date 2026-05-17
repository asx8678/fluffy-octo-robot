"""Critic Fabric — unified critic path for Muse.

Owns the canonical models, preflight checks, and pluggable backend
registry so that every critic consumer (code_critic, universal_critic,
debate, user-defined backends) goes through a single code path.

Architecture
------------

- ``models.py``    — CriticIssue, CriticRequest, CriticVerdict
- ``preflight.py`` — truncation / structural sanity checks (pre-LLM)
- ``backends.py``  — pluggable reviewer backend registry
- ``fabric.py``    — top-level ``review()`` orchestrating preflight → backend

Design decisions
----------------

1. Preflight runs **before** any backend is invoked — truncated code
   never reaches the LLM.
2. Backends are named callables registered via ``register_backend()``.
   Built-in aliases (``light``, ``heavy`` → ``code_critic``) exist
   for ergonomic use.
3. The dict return shape from ``code_critic.reviewer.review_code`` is
   preserved for backward compatibility via ``CriticVerdict.to_dict()``.
"""

from code_muse.plugins.critic_fabric.fabric import review
from code_muse.plugins.critic_fabric.models import (
    CriticIssue,
    CriticRequest,
    CriticVerdict,
    VerdictKind,
)
from code_muse.plugins.critic_fabric.preflight import run_preflight

__all__ = [
    "CriticIssue",
    "CriticRequest",
    "CriticVerdict",
    "VerdictKind",
    "review",
    "run_preflight",
]
