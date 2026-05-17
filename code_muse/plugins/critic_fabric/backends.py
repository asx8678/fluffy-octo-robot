"""Pluggable reviewer backend registry for the Critic Fabric.

A *backend* is an async callable with signature::

    async def my_backend(request: CriticRequest) -> CriticVerdict: ...

Backends are registered by name and looked up by the ``CriticRequest.backend``
field.  Built-in aliases (``light``, ``heavy``) map to ``code_critic`` by
default.  Users can register custom backends via ``register_backend()``.

Design notes
------------

- The registry is a module-level dict — simple, explicit, no metaclass magic.
- ``get_backend()`` raises ``KeyError`` with a helpful message for unknown
  names.  Callers that prefer a fallback can use ``get_backend(name, fallback=...)``.
- ``code_critic`` backend is **lazy-imported** to avoid circular imports
  at plugin-load time (code_critic imports truncation_detector which
  is also used by preflight).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from code_muse.plugins.critic_fabric.models import (
    CriticRequest,
    CriticVerdict,
    VerdictKind,
)

logger = logging.getLogger(__name__)

# Type alias for backend callables
BackendFunc = Callable[[CriticRequest], Any]  # returns Awaitable[CriticVerdict]

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, BackendFunc] = {}

# Alias map — multiple names pointing to the same backend key
_ALIASES: dict[str, str] = {
    "light": "code_critic",
    "heavy": "code_critic",
}


def register_backend(name: str, func: BackendFunc, *, alias: bool = False) -> None:
    """Register a reviewer backend under *name*.

    Args:
        name: Unique backend name (e.g. ``"code_critic"``, ``"debate"``).
        func: Async callable ``(CriticRequest) -> CriticVerdict``.
        alias: If True, also register as an alias target for itself.
            (Only useful for the initial ``code_critic`` registration.)
    """
    if name in _REGISTRY and _REGISTRY[name] is not func:
        logger.warning("Overwriting existing backend '%s'", name)
    _REGISTRY[name] = func
    if alias:
        for alias_name, target in list(_ALIASES.items()):
            if target == name:
                _ALIASES[alias_name] = name


def register_alias(alias: str, target: str) -> None:
    """Register *alias* as an alternative name for *target* backend.

    Args:
        alias: The alias name (e.g. ``"light"``).
        target: The existing backend name it resolves to.
    """
    _ALIASES[alias] = target


def get_backend(name: str) -> BackendFunc:
    """Look up a backend by name (resolving aliases).

    Raises:
        KeyError: If *name* and any alias for it are not registered.
    """
    resolved = _ALIASES.get(name, name)
    if resolved not in _REGISTRY:
        available = sorted(set(list(_REGISTRY.keys()) + list(_ALIASES.keys())))
        raise KeyError(
            f"Unknown critic backend '{name}'. Available backends: {available}"
        )
    return _REGISTRY[resolved]


def list_backends() -> list[str]:
    """Return sorted list of all available backend names (including aliases)."""
    names = set(list(_REGISTRY.keys()) + list(_ALIASES.keys()))
    return sorted(names)


# ---------------------------------------------------------------------------
# Built-in code_critic backend
# ---------------------------------------------------------------------------


async def _code_critic_backend(request: CriticRequest) -> CriticVerdict:
    """Backend that delegates to ``code_critic.reviewer._review_code_with_llm``.

    This is the default backend.  It expects the preflight to have
    already passed (the fabric handles that).
    """
    from code_muse.plugins.code_critic.reviewer import _review_code_with_llm

    result_dict = await _review_code_with_llm(
        file_path=request.file_path,
        code_snippet=request.code_snippet,
        operation=request.operation,
        agent_name=request.agent_name,
    )
    return CriticVerdict.from_dict(result_dict, backend="code_critic")


# Register the built-in backend eagerly — the lazy import inside the
# function body avoids circular-import issues at module load.
register_backend("code_critic", _code_critic_backend, alias=True)


# ---------------------------------------------------------------------------
# Debate adapter
# ---------------------------------------------------------------------------


async def _debate_backend(request: CriticRequest) -> CriticVerdict:
    """Thin adapter that wraps the debate reviewer as a critic fabric backend.

    Translates between ``CriticRequest`` / ``CriticVerdict`` and the
    debate plugin's ``ReviewRequest`` / ``ReviewResponse`` schemas.
    Falls back to a flagged verdict when debate is unavailable.
    """
    try:
        from code_muse.plugins.debate.reviewer import run_review
        from code_muse.plugins.debate.schemas import ReviewRequest
        from code_muse.plugins.debate.schemas import VerdictKind as DebateVK
    except ImportError:
        logger.warning("Debate plugin not available — returning flagged verdict")
        return CriticVerdict(
            verdict=VerdictKind.FLAGGED,
            summary="Debate backend unavailable",
            issues=["Debate plugin could not be imported"],
            backend="debate",
        )

    debate_request = ReviewRequest(
        proposal=request.code_snippet[:6000],
        reasoning_summary=request.metadata.get("reasoning_summary", ""),
        checkpoint=request.metadata.get("checkpoint", 1),
    )

    response = await run_review(debate_request)
    if response is None:
        return CriticVerdict(
            verdict=VerdictKind.FLAGGED,
            summary="Debate reviewer returned no response",
            issues=["Debate reviewer did not produce a verdict"],
            backend="debate",
        )

    # Translate debate VerdictKind → CriticFabric VerdictKind
    kind_map = {
        DebateVK.APPROVE: VerdictKind.APPROVED,
        DebateVK.REVISE: VerdictKind.FLAGGED,
        DebateVK.REJECT: VerdictKind.REJECTED,
    }
    vk = kind_map.get(response.verdict.kind, VerdictKind.FLAGGED)

    issues = [f"[{i.severity}] {i.message}" for i in response.verdict.issues]

    return CriticVerdict(
        verdict=vk,
        summary=response.verdict.summary,
        issues=issues,
        raw_response=response.verdict.model_dump_json(),
        backend="debate",
    )


register_backend("debate", _debate_backend)
