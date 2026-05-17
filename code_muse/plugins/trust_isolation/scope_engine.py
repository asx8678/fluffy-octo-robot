"""Scope enforcement engine — the core guardrail for trust & isolation.

This module enforces that agents cannot read or write artifacts outside
their declared scope without an explicit policy exception. It is the
primary guardrail required by Initiative 4.0 (z30.0).

Design principles:
- Same-scope access is always allowed (zero friction for common case).
- Cross-scope access requires an explicit policy entry.
- Denied access raises ``ScopeViolationError``, never silently passes.
- All decisions are logged to the event stream for audit.
"""

from __future__ import annotations

import logging
from fnmatch import fnmatch

from code_muse.plugins.trust_isolation.models import (
    Artifact,
    Capability,
    CapabilityPolicy,
    ExperienceCapsule,
    Provenance,
    Scope,
)

logger = logging.getLogger(__name__)


class ScopeViolationError(PermissionError):
    """Raised when an agent attempts an out-of-scope operation.

    This is the enforcement mechanism — it's a hard block, not a warning.
    The calling tool must handle this and return an error to the agent.
    """

    def __init__(
        self,
        message: str,
        *,
        caller_scope: Scope | None = None,
        target_scope: Scope | None = None,
        capability: Capability | None = None,
    ) -> None:
        super().__init__(message)
        self.caller_scope = caller_scope
        self.target_scope = target_scope
        self.capability = capability


class ScopeEngine:
    """Evaluates scope policies and enforces isolation boundaries.

    Thread safety: all public methods are pure (no mutable state).
    Policies are loaded at init and treated as immutable.
    """

    def __init__(self, policies: list[CapabilityPolicy] | None = None) -> None:
        self._policies: list[CapabilityPolicy] = policies or []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_read(
        self,
        caller: Provenance,
        artifact: Artifact,
    ) -> None:
        """Check that *caller* can read *artifact*.

        Raises:
            ScopeViolationError: If the caller's scope doesn't contain
                the artifact's scope and no policy exception exists.
        """
        self._check(
            caller=caller,
            target_scope=artifact.scope,
            capability=Capability.BLACKBOARD_READ,
            operation="read",
            artifact_id=artifact.artifact_id,
        )

    def check_read_capsule(
        self,
        caller: Provenance,
        capsule: ExperienceCapsule,
    ) -> None:
        """Check that *caller* can read *capsule* from the experience store."""
        self._check(
            caller=caller,
            target_scope=capsule.scope,
            capability=Capability.EXPERIENCE_READ,
            operation="read",
            artifact_id=capsule.capsule_id,
        )

    def check_write(
        self,
        caller: Provenance,
        target_scope: Scope,
    ) -> None:
        """Check that *caller* can write to *target_scope*."""
        self._check(
            caller=caller,
            target_scope=target_scope,
            capability=Capability.BLACKBOARD_WRITE,
            operation="write",
            artifact_id=None,
        )

    def check_write_capsule(
        self,
        caller: Provenance,
        target_scope: Scope,
    ) -> None:
        """Check that *caller* can write a capsule to *target_scope*."""
        self._check(
            caller=caller,
            target_scope=target_scope,
            capability=Capability.EXPERIENCE_WRITE,
            operation="write",
            artifact_id=None,
        )

    def add_policy(self, policy: CapabilityPolicy) -> None:
        """Add a policy exception (e.g. allow cross-scope read for admin)."""
        self._policies.append(policy)
        logger.info(
            "Scope policy added: agent=%s cap=%s scope=%s allowed=%s",
            policy.agent_pattern,
            policy.capability,
            policy.scope_pattern,
            policy.allowed,
        )

    def list_policies(self) -> list[CapabilityPolicy]:
        """Return a snapshot of current policies."""
        return list(self._policies)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check(
        self,
        caller: Provenance,
        target_scope: Scope,
        capability: Capability,
        operation: str,
        artifact_id: str | None,
    ) -> None:
        """Core policy evaluation.

        1. If caller scope contains target scope → ALLOW (same-scope)
        2. If any explicit policy matches → use that policy
        3. Otherwise → DENY (raise ScopeViolationError)
        """
        caller_scope = caller.scope

        # Same-scope: always allowed
        if caller_scope.contains(target_scope):
            logger.debug(
                "Scope check PASS: %s %s caller=%s target=%s (same scope)",
                operation,
                capability,
                caller_scope.scope_id,
                target_scope.scope_id,
            )
            return

        # Check explicit policies (highest priority first)
        matching = [
            p
            for p in self._policies
            if self._policy_matches(p, caller, target_scope, capability)
        ]

        if matching:
            # Use the most specific match (first by convention)
            policy = matching[0]
            if policy.allowed:
                logger.info(
                    "Scope check PASS via policy: %s %s caller=%s target=%s "
                    "policy=%s/%s/%s",
                    operation,
                    capability,
                    caller_scope.scope_id,
                    target_scope.scope_id,
                    policy.agent_pattern,
                    policy.capability,
                    policy.scope_pattern,
                )
                return
            else:
                # Explicit deny
                raise ScopeViolationError(
                    f"Scope policy explicitly denies {capability} "
                    f"for agent '{caller.agent_name}' "
                    f"(caller scope: {caller_scope.scope_id}, "
                    f"target scope: {target_scope.scope_id})",
                    caller_scope=caller_scope,
                    target_scope=target_scope,
                    capability=capability,
                )

        # No policy match and not same-scope → DENY
        raise ScopeViolationError(
            f"Scope violation: agent '{caller.agent_name}' cannot {operation} "
            f"across scope boundary "
            f"(caller: {caller_scope.scope_id}, "
            f"target: {target_scope.scope_id})",
            caller_scope=caller_scope,
            target_scope=target_scope,
            capability=capability,
        )

    @staticmethod
    def _policy_matches(
        policy: CapabilityPolicy,
        caller: Provenance,
        target_scope: Scope,
        capability: Capability,
    ) -> bool:
        """Check if a policy entry matches the current request."""
        # Capability must match exactly
        if policy.capability != capability:
            return False

        # Agent pattern must match caller agent name
        if not fnmatch(caller.agent_name, policy.agent_pattern):
            return False

        # Scope pattern matching
        if policy.scope_pattern == "self":
            # "self" means caller's own scope (already handled above)
            return caller.scope.contains(target_scope)
        elif policy.scope_pattern == "*":
            # Wildcard: any scope
            return True
        else:
            # Specific scope ID
            return target_scope.scope_id == policy.scope_pattern


# ---------------------------------------------------------------------------
# Module-level singleton (shared across tools/plugins in-process)
# ---------------------------------------------------------------------------

_engine: ScopeEngine | None = None


def get_scope_engine() -> ScopeEngine:
    """Return the global scope engine singleton.

    The engine is created on first access and lives for the process
    lifetime. Policies can be added at runtime via ``add_policy()``.
    """
    global _engine
    if _engine is None:
        _engine = ScopeEngine()
        logger.debug("Scope engine initialised (default: same-scope-only)")
    return _engine


def reset_scope_engine() -> None:
    """Reset the scope engine (for testing)."""
    global _engine
    _engine = None
