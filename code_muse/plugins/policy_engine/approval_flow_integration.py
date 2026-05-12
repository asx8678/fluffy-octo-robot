import logging
from typing import Any

from code_muse.plugins.policy_engine.policy_evaluator import (
    evaluate_policy,
    evaluate_tool_policy,
)
from code_muse.plugins.policy_engine.policy_file_discovery import load_all_policies
from code_muse.plugins.policy_engine.policy_toml_schema import Decision, ToolRule

logger = logging.getLogger(__name__)


def integrate_policy_check(
    tool_name: str,
    command: str | None = None,
    rules: list[ToolRule] | None = None,
) -> dict[str, Any] | None:
    if rules is None:
        rules = load_all_policies()

    if command is not None:
        decision, matched_rule = evaluate_policy(tool_name, command, rules)
    else:
        decision, matched_rule = evaluate_tool_policy(tool_name, rules)

    if decision == Decision.ALLOW:
        if command is not None:
            # Shell command path: signal auto_approval to skip confirmation
            logger.info(
                "Policy auto-approved %s (command=%s, rule=%s)",
                tool_name,
                command,
                matched_rule.description if matched_rule else "default",
            )
            return {"auto_approve": True}
        # Non-shell tool path: auto_approve not relevant, just allow
        logger.debug("Policy allowed %s (no confirmation to skip)", tool_name)
        return None

    if decision == Decision.DENY:
        message = _build_block_message(matched_rule, tool_name)
        logger.warning(
            "Policy blocked %s (command=%s): %s", tool_name, command, message
        )
        return {"blocked": True, "error_message": message}

    if decision == Decision.ASK_USER:
        logger.debug("Policy ASK_USER for %s (command=%s)", tool_name, command)
        return None

    # Should never reach here, but default to normal flow
    return None


def _build_block_message(rule: Any, tool_name: str) -> str:
    if rule and getattr(rule, "description", None):
        return f"🚫 Policy: {rule.description}"
    return f"🚫 Policy: blocked {tool_name}"
