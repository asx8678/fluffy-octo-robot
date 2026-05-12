import logging
from fnmatch import fnmatch

from code_muse.plugins.policy_engine.policy_toml_schema import Decision, ToolRule

logger = logging.getLogger(__name__)


def _tool_name_matches(tool_name: str, rule_tool_name: str) -> bool:
    if rule_tool_name == "*":
        return True
    # Support fnmatch wildcards (e.g., "agent_run_*")
    return fnmatch(tool_name, rule_tool_name)


def evaluate_policy(
    tool_name: str,
    command: str | None,
    rules: list[ToolRule],
) -> tuple[Decision, ToolRule | None]:
    matched: list[ToolRule] = []
    for rule in rules:
        if not _tool_name_matches(tool_name, rule.tool_name):
            continue
        if rule.command_prefix is not None:
            if command is None:
                # command_prefix specified but no command provided — skip
                continue
            if not command.startswith(rule.command_prefix):
                continue
        matched.append(rule)

    if not matched:
        logger.debug(
            "Policy: no rules matched for tool=%s command=%s — default ALLOW",
            tool_name,
            command,
        )
        return (Decision.ALLOW, None)

    # Sort by priority descending
    matched.sort(key=lambda r: r.priority, reverse=True)
    highest_priority = matched[0].priority
    top_rules = [r for r in matched if r.priority == highest_priority]

    if len(top_rules) > 1:
        decisions = {r.decision for r in top_rules}
        if len(decisions) > 1:
            logger.warning(
                "Policy conflict: %d rules at priority %d with different decisions "
                "for tool=%s command=%s. Using first registered: %s",
                len(top_rules),
                highest_priority,
                tool_name,
                command,
                top_rules[0],
            )

    chosen = top_rules[0]
    logger.debug(
        "Policy: matched rule for tool=%s command=%s → %s (priority=%d, source=%s)",
        tool_name,
        command,
        chosen.decision.value,
        chosen.priority,
        chosen.source,
    )
    return (chosen.decision, chosen)


def evaluate_tool_policy(
    tool_name: str,
    rules: list[ToolRule],
) -> tuple[Decision, ToolRule | None]:
    return evaluate_policy(tool_name, None, rules)
