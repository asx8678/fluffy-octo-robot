"""Config: agent settings."""

import configparser

import code_muse.config as _config

PACK_AGENT_NAMES = frozenset(
    [
        "pack-leader",
        "bloodhound",
        "shepherd",
        "terrier",
        "watchdog",
        "retriever",
    ]
)
UC_AGENT_NAMES = frozenset(["helios"])


def get_pack_agents_enabled() -> bool:
    """Return True if pack agents are enabled (default False).

    When False (default), pack agents (pack-leader, bloodhound, shepherd,
    terrier, watchdog, retriever) are hidden from `list_agents` tool and `/agents`
    command. They cannot be invoked by other agents or selected by users.

    When True, pack agents are available for use.
    """
    cfg_val = _config.get_value("enable_pack_agents")
    if cfg_val is None:
        return False
    return str(cfg_val).strip().lower() in {"1", "true", "yes", "on"}


def get_universal_constructor_enabled() -> bool:
    """Return True if the Universal Constructor is enabled (default True).

    The Universal Constructor allows agents to dynamically create, manage,
    and execute custom tools at runtime. When enabled, agents can extend
    their capabilities by writing Python code that becomes callable tools.

    When False, the universal_constructor tool is not registered with agents.
    """
    cfg_val = _config.get_value("enable_universal_constructor")
    if cfg_val is None:
        return True  # Enabled by default
    return str(cfg_val).strip().lower() in {"1", "true", "yes", "on"}


def set_universal_constructor_enabled(enabled: bool) -> None:
    """Enable or disable the Universal Constructor.

    Args:
        enabled: True to enable, False to disable
    """
    _config.set_value("enable_universal_constructor", "true" if enabled else "false")


def get_user_agents_directory() -> str:
    """Get the user's agents directory path.

    Returns:
        Path to the user's Muse agents directory.
    """
    # Ensure the agents directory exists
    _config.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    return str(_config.AGENTS_DIR)


def get_project_agents_directory() -> str | None:
    """Get the project-local agents directory path.

    Looks for a .muse/agents/ directory in the current working directory.
    Unlike get_user_agents_directory(), this does NOT create the directory
    if it doesn't exist -- the team must create it intentionally.

    Returns:
        Path to the project's agents directory if it exists, or None.
    """
    project_agents_dir = _config.Path.cwd() / ".muse" / "agents"
    if project_agents_dir.is_dir():
        return str(project_agents_dir)
    return None


def get_agent_pinned_model(agent_name: str) -> str:
    """Get the pinned model for a specific agent.

    Args:
        agent_name: Name of the agent to get the pinned model for.

    Returns:
        Pinned model name, or None if no model is pinned for this agent.
    """
    return _config.get_value(f"agent_model_{agent_name}")


def set_agent_pinned_model(agent_name: str, model_name: str):
    """Set the pinned model for a specific agent.

    Args:
        agent_name: Name of the agent to pin the model for.
        model_name: Model name to pin to this agent.
    """
    _config.set_config_value(f"agent_model_{agent_name}", model_name)


def clear_agent_pinned_model(agent_name: str):
    """Clear the pinned model for a specific agent.

    Args:
        agent_name: Name of the agent to clear the pinned model for.
    """
    # We can't easily delete keys from configparser, so set to empty string
    # which will be treated as None by get_agent_pinned_model
    _config.set_config_value(f"agent_model_{agent_name}", "")


def get_all_agent_pinned_models() -> dict:
    """Get all agent-to-model pinnings from config.

    Returns:
        Dict mapping agent names to their pinned model names.
        Only includes agents that have a pinned model (non-empty value).
    """
    config = configparser.ConfigParser()
    config.read(_config.CONFIG_FILE)

    pinnings = {}
    if _config.DEFAULT_SECTION in config:
        for key, value in config[_config.DEFAULT_SECTION].items():
            if key.startswith("agent_model_") and value:
                agent_name = key[len("agent_model_") :]
                pinnings[agent_name] = value
    return pinnings


def get_agents_pinned_to_model(model_name: str) -> list:
    """Get all agents that are pinned to a specific model.

    Args:
        model_name: The model name to look up.

    Returns:
        List of agent names pinned to this model.
    """
    all_pinnings = get_all_agent_pinned_models()
    return [agent for agent, model in all_pinnings.items() if model == model_name]


def get_default_agent() -> str:
    """
    Get the default agent name from muse.cfg.

    Returns:
        str: The default agent name, or "planning-agent" if not set.
    """
    return _config.get_value("default_agent") or "planning-agent"


def set_default_agent(agent_name: str) -> None:
    """
    Set the default agent name in muse.cfg.

    Args:
        agent_name: The name of the agent to set as default.
    """
    _config.set_config_value("default_agent", agent_name)
