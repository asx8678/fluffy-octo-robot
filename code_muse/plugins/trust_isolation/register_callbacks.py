"""Callback registration for the Trust & Isolation plugin.

Hooks into:
- ``pre_tool_call``: Enforces scope boundaries before blackboard/experience
  tool calls execute.
- ``post_tool_call``: Logs scope decisions for audit trail.
- ``load_prompt``: Adds provenance awareness instructions to agent prompts.
- ``custom_command``: ``/scope`` commands for policy management.
- ``startup``: Initialises the scope engine.

This plugin is the **Phase 0 prerequisite** (z30.0) — it must be in
place before any blackboard or experience store code ships.
"""

from __future__ import annotations

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning
from code_muse.plugins.trust_isolation.models import (
    Artifact,
    Capability,
    CapabilityPolicy,
    Provenance,
    Scope,
)
from code_muse.plugins.trust_isolation.scope_engine import (
    ScopeViolationError,
    get_scope_engine,
)
from code_muse.tools.subagent_context import get_subagent_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------


def _current_provenance() -> Provenance:
    """Build a Provenance for the current agent context.

    Uses subagent_context to identify the calling agent, and derives
    scope from the current working directory.
    """
    agent_name = get_subagent_name() or "muse"
    return Provenance(
        agent_name=agent_name,
        scope=Scope(),
    )


# ---------------------------------------------------------------------------
# Tool-level scope enforcement (guardrail #1)
# ---------------------------------------------------------------------------

# Tool names that require scope enforcement.
_SCOPED_TOOLS: frozenset[str] = frozenset(
    {
        "blackboard_read",
        "blackboard_write",
        "blackboard_query",
        "experience_read",
        "experience_write",
        "experience_search",
    }
)


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> dict[str, Any] | None:
    """Enforce scope boundaries before blackboard/experience tool calls.

    Returns ``{"blocked": True, "error_message": "..."}`` if the
    operation violates scope policy. Returns ``None`` to allow.
    """
    if tool_name not in _SCOPED_TOOLS:
        return None

    engine = get_scope_engine()
    provenance = _current_provenance()

    try:
        # Extract target scope and artifact/capsule from tool_args
        if tool_name.startswith("blackboard"):
            capability = (
                Capability.BLACKBOARD_READ
                if "read" in tool_name or "query" in tool_name
                else Capability.BLACKBOARD_WRITE
            )
            target_scope_str = tool_args.get("scope")
            target_scope = (
                Scope(scope_id=target_scope_str)
                if target_scope_str
                else provenance.scope
            )

            if capability == Capability.BLACKBOARD_READ:
                # Check read on the artifact if provided
                artifact_data = tool_args.get("artifact")
                if artifact_data and isinstance(artifact_data, dict):
                    artifact_scope = artifact_data.get("scope", target_scope.scope_id)
                    artifact = Artifact(
                        scope=Scope(scope_id=artifact_scope),
                        provenance=provenance,
                    )
                    engine.check_read(provenance, artifact)
                else:
                    # Query: check that caller can read from target scope
                    if not provenance.scope.contains(target_scope):
                        engine._check(
                            caller=provenance,
                            target_scope=target_scope,
                            capability=Capability.BLACKBOARD_READ,
                            operation="read",
                            artifact_id=None,
                        )
            else:
                engine.check_write(provenance, target_scope)

        elif tool_name.startswith("experience"):
            capability = (
                Capability.EXPERIENCE_READ
                if "read" in tool_name or "search" in tool_name
                else Capability.EXPERIENCE_WRITE
            )
            target_scope_str = tool_args.get("scope")
            target_scope = (
                Scope(scope_id=target_scope_str)
                if target_scope_str
                else provenance.scope
            )

            if capability == Capability.EXPERIENCE_READ:
                if not provenance.scope.contains(target_scope):
                    engine._check(
                        caller=provenance,
                        target_scope=target_scope,
                        capability=Capability.EXPERIENCE_READ,
                        operation="read",
                        artifact_id=None,
                    )
            else:
                engine.check_write_capsule(provenance, target_scope)

    except ScopeViolationError as e:
        logger.warning(
            "Scope violation blocked: %s (agent=%s, tool=%s)",
            e,
            provenance.agent_name,
            tool_name,
        )
        return {
            "blocked": True,
            "error_message": str(e),
        }

    return None  # Allow the tool call


# ---------------------------------------------------------------------------
# Audit logging on post_tool_call
# ---------------------------------------------------------------------------


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> Any:
    """Log scope decisions for audit trail (via upgrade_metrics)."""
    if tool_name not in _SCOPED_TOOLS:
        return None

    try:
        from code_muse.plugins.upgrade_metrics import emit_metric

        provenance = _current_provenance()
        blocked = isinstance(result, dict) and result.get("blocked", False)

        emit_metric(
            "scope_check",
            {
                "tool": tool_name,
                "agent": provenance.agent_name,
                "scope": provenance.scope.scope_id,
                "blocked": blocked,
                "duration_ms": round(duration_ms, 2),
            },
        )
    except ImportError:
        logger.debug("upgrade_metrics not available — skipping scope audit")
    except Exception:
        logger.debug("Failed to emit scope audit metric", exc_info=True)

    return None


# ---------------------------------------------------------------------------
# Provenance instructions in agent prompt (guardrail #2)
# ---------------------------------------------------------------------------


def _on_load_prompt() -> str | None:
    """Add provenance/scope awareness to agent system prompts.

    This ensures agents know about the trust model and can make
    informed decisions about blackboard/experience store access.
    """
    return (
        "\n## Trust & Isolation Model\n"
        "All blackboard artifacts and experience capsules are scoped to "
        "your current repository/workspace. You cannot read or write "
        "artifacts outside your scope. Every artifact carries provenance "
        "(which agent created it and when). Use this provenance to "
        "evaluate the trustworthiness of artifacts you consume.\n"
        "If a scope violation occurs, you will receive a clear error — "
        "do not attempt to work around it.\n"
    )


# ---------------------------------------------------------------------------
# /scope slash commands
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | str | None:
    """Handle ``/scope`` commands for policy management."""
    if name != "scope":
        return None

    parts = command.split(maxsplit=2)
    sub = parts[1].strip().lower() if len(parts) > 1 else "status"

    engine = get_scope_engine()

    if sub == "status":
        provenance = _current_provenance()
        policies = engine.list_policies()
        lines = [
            "🔒 Trust & Isolation Status:",
            f"   Current scope: {provenance.scope.scope_id}",
            f"   Agent: {provenance.agent_name}",
            f"   Policies loaded: {len(policies)}",
        ]
        if policies:
            lines.append("")
            lines.append("   Active policies:")
            for p in policies:
                status = "✓ ALLOW" if p.allowed else "✗ DENY"
                lines.append(
                    f"     {status}  agent={p.agent_pattern} "
                    f"cap={p.capability} scope={p.scope_pattern}"
                )
        emit_info("\n".join(lines))
        return True

    if sub == "allow":
        # /scope allow <agent_pattern> <capability> <scope_pattern>
        if len(parts) < 5:
            emit_info(
                "Usage: /scope allow <agent_pattern> <capability> <scope_pattern>\n"
                "Example: /scope allow critic blackboard:read repo:abc123"
            )
            return True
        agent_pat = parts[2]
        try:
            cap = Capability(parts[3])
        except ValueError:
            emit_warning(
                f"Unknown capability: {parts[3]}. "
                f"Valid: {[c.value for c in Capability]}"
            )
            return True
        scope_pat = parts[4]
        engine.add_policy(
            CapabilityPolicy(
                agent_pattern=agent_pat,
                capability=cap,
                scope_pattern=scope_pat,
                allowed=True,
            )
        )
        emit_success(f"🔓 Policy added: allow {agent_pat} {cap} scope={scope_pat}")
        return True

    if sub == "deny":
        if len(parts) < 5:
            emit_info("Usage: /scope deny <agent_pattern> <capability> <scope_pattern>")
            return True
        agent_pat = parts[2]
        try:
            cap = Capability(parts[3])
        except ValueError:
            emit_warning(f"Unknown capability: {parts[3]}")
            return True
        scope_pat = parts[4]
        engine.add_policy(
            CapabilityPolicy(
                agent_pattern=agent_pat,
                capability=cap,
                scope_pattern=scope_pat,
                allowed=False,
            )
        )
        emit_success(f"🔒 Policy added: deny {agent_pat} {cap} scope={scope_pat}")
        return True

    if sub == "help":
        lines = [
            "🔒 Trust & Isolation Commands:",
            "   /scope status                          — Show current scope & policies",
            "   /scope allow <agent> <cap> <scope>     — Add allow policy",
            "   /scope deny <agent> <cap> <scope>       — Add deny policy",
            "   /scope help                            — Show this help",
            "",
            "   Capabilities: " + ", ".join(c.value for c in Capability),
        ]
        emit_info("\n".join(lines))
        return True

    emit_info("Usage: /scope status|allow|deny|help")
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("scope status", "Show current scope & isolation policies"),
        ("scope allow", "Add a cross-scope allow policy"),
        ("scope deny", "Add a cross-scope deny policy"),
        ("scope help", "Show trust & isolation command help"),
    ]


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Initialise the scope engine on app boot."""
    get_scope_engine()
    logger.debug("Trust & Isolation plugin initialised")


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("pre_tool_call", _on_pre_tool_call, priority=10)
register_callback("post_tool_call", _on_post_tool_call, priority=10)
register_callback("load_prompt", _on_load_prompt)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
