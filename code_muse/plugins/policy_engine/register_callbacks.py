import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info
from code_muse.plugins.policy_engine.approval_flow_integration import (
    integrate_policy_check,
)
from code_muse.plugins.policy_engine.policy_file_discovery import (
    clear_policy_cache,
    load_all_policies,
)

logger = logging.getLogger(__name__)

# Load policies at import time so they're available immediately.
# This is safe because load_all_policies caches results and logs warnings
# for invalid files rather than raising.
_INITIALIZED_RULES = load_all_policies()
logger.info(
    "Policy engine initialized with %d rule(s)",
    len(_INITIALIZED_RULES),
)


async def _on_run_shell_command(
    context: Any,
    command: str,
    cwd: str | None = None,
    timeout: int = 60,
) -> dict[str, Any | None]:
    """Policy check for shell commands.

    Returns:
        - {"auto_approve": True} if policy says ALLOW
        - {"blocked": True, "error_message": "..."} if policy says DENY
        - None for ASK_USER or no match (normal confirmation flow)
    """
    return integrate_policy_check("agent_run_shell_command", command)


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> dict[str, Any | None]:
    """Policy check for all tool calls.

    Returns:
        - {"blocked": True, "error_message": "..."} if policy says DENY
        - None otherwise (ALLOW, ASK_USER, or no match)
    """
    result = integrate_policy_check(tool_name, None)
    if result and result.get("blocked"):
        return result
    return None


def _on_custom_command(command: str, name: str) -> Any:
    """Handle /policies and /policies reload commands."""
    if name == "policies":
        parts = command.split(maxsplit=1)
        subcommand = parts[1].strip().lower() if len(parts) > 1 else ""

        if subcommand == "reload":
            clear_policy_cache()
            rules = load_all_policies(force_reload=True)
            emit_info(f"[Run] Policy rules reloaded: {len(rules)} active rule(s)")
            return True

        # Default /policies — list loaded rules
        rules = load_all_policies()
        if not rules:
            emit_info("[Warn] No policy rules loaded.")
            return True

        lines: list[str] = ["[Run] Active rules:"]
        seen_sources: set[str] = set()
        for rule in rules:
            prefix = f"  [{rule.priority}] {rule.tool_name}"
            if rule.command_prefix:
                prefix += f" (prefix='{rule.command_prefix}')"
            prefix += f" → {rule.decision.value}"
            if rule.description:
                prefix += f" — {rule.description}"
            lines.append(prefix)
            if rule.source:
                seen_sources.add(rule.source)

        if seen_sources:
            lines.append("")
            lines.append("Sources:")
            for src in sorted(seen_sources):
                lines.append(f"  • {src}")

        emit_info("\n".join(lines))
        return True

    return None


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("policies", "List loaded policy rules"),
        ("policies reload", "Reload policy rules from disk"),
    ]


register_callback("run_shell_command", _on_run_shell_command, priority=50)
register_callback("pre_tool_call", _on_pre_tool_call, priority=50)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
