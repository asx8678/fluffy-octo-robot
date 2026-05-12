import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


@dataclass
class ToolRule:
    tool_name: str
    decision: Decision
    command_prefix: str | None = None
    priority: int = 0
    description: str = ""
    source: str = field(default="", repr=False)


def _warn_unknown_fields(rule_table: dict[str, Any], path: str | Path) -> None:
    known = {"toolName", "commandPrefix", "decision", "priority", "description"}
    unknown = set(rule_table.keys()) - known
    if unknown:
        logger.warning("Unknown fields in rule from %s: %s", path, ", ".join(unknown))


def parse_policy_toml(path: str | Path) -> list[ToolRule]:
    path = Path(path)
    import tomllib

    raw = path.read_text(encoding="utf-8")
    data = tomllib.loads(raw)

    schema_version = data.get("schema_version")
    if schema_version is not None and str(schema_version) != "1":
        logger.warning(
            "Policy file %s has schema_version %s; expected 1. "
            "Forward compatibility assumed.",
            path,
            schema_version,
        )

    rules: list[ToolRule] = []
    rule_tables = data.get("rule", [])
    if isinstance(rule_tables, dict):
        # Single [[rule]] can be parsed as dict by some TOML libs
        rule_tables = [rule_tables]

    for idx, rule_table in enumerate(rule_tables):
        if not isinstance(rule_table, dict):
            raise ValueError(
                f"Invalid rule entry at index {idx} in {path}: expected table, got {type(rule_table).__name__}"
            )

        _warn_unknown_fields(rule_table, path)

        tool_name = rule_table.get("toolName")
        if tool_name is None or not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError(f"Rule {idx + 1} in {path}: missing or invalid 'toolName'")

        decision_str = rule_table.get("decision")
        if decision_str is None or not isinstance(decision_str, str):
            raise ValueError(f"Rule {idx + 1} in {path}: missing or invalid 'decision'")
        try:
            decision = Decision(decision_str)
        except ValueError as exc:
            raise ValueError(
                f"Rule {idx + 1} in {path}: invalid decision '{decision_str}'. "
                f"Must be one of: {', '.join(d.value for d in Decision)}"
            ) from exc

        command_prefix = rule_table.get("commandPrefix")
        if command_prefix is not None and not isinstance(command_prefix, str):
            raise ValueError(
                f"Rule {idx + 1} in {path}: 'commandPrefix' must be a string"
            )

        priority = rule_table.get("priority", 0)
        if not isinstance(priority, int):
            raise ValueError(f"Rule {idx + 1} in {path}: 'priority' must be an integer")

        description = rule_table.get("description", "")
        if description is not None and not isinstance(description, str):
            raise ValueError(
                f"Rule {idx + 1} in {path}: 'description' must be a string"
            )

        rules.append(
            ToolRule(
                tool_name=tool_name,
                decision=decision,
                command_prefix=command_prefix if command_prefix else None,
                priority=priority,
                description=description,
                source=str(path),
            )
        )

    return rules


def validate_rules(rules: list[ToolRule]) -> None:
    for rule in rules:
        if not rule.tool_name or not rule.tool_name.strip():
            raise ValueError(f"Invalid rule: tool_name is empty (from {rule.source})")
        if rule.decision == Decision.DENY and not rule.tool_name.strip():
            raise ValueError(
                f"Invalid rule: deny with empty tool_name (from {rule.source})"
            )
