"""Register delegation manager callbacks.

Registers:
    - Supervisor agent via register_agents hook
    - Delegation tools via register_tools hook
    - /supervisor command for easy activation
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success

logger = logging.getLogger(__name__)

# Lazy manager singleton
_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        from code_muse.plugins.delegation_manager.delegation_manager import (
            DelegationManager,
        )

        _manager = DelegationManager()
    return _manager


def _register_agents():
    """Register the supervisor agent."""
    from code_muse.plugins.delegation_manager.supervisor_agent import SupervisorAgent

    return [{"name": "supervisor", "class": SupervisorAgent}]


def _register_delegation_tools() -> list[dict[str, Any]]:
    """Dynamically create delegation tools for all available agents."""
    from code_muse.agents.agent_manager import load_agent
    from code_muse.agents import get_available_agents

    manager = _get_manager()

    tools = []
    agents = get_available_agents()

    for agent_name in agents:
        # Skip self
        if agent_name == "supervisor":
            continue
        # Create delegation function using the manager
        try:
            agent_config = load_agent(agent_name)
            delegate_func = manager.create_delegation_function(agent_name, agent_config)
            tool_name = f"delegate_to_{agent_name.replace('-', '_')}"
            tools.append(
                {
                    "name": tool_name,
                    "register_func": lambda a, f=delegate_func: a.tool(f),
                }
            )
        except Exception as e:
            logger.warning(f"Could not create delegation tool for {agent_name}: {e}")

    return tools


def _on_custom_command_help():
    return [
        (
            "supervisor",
            "Switch to Supervisor agent for multi-agent task orchestration",
        ),
    ]


async def _on_custom_command(command: str, name: str):
    if name != "supervisor":
        return None

    from code_muse.agents.agent_manager import set_current_agent

    success = set_current_agent("supervisor")
    if success:
        emit_success(
            "Switched to Supervisor agent. I can delegate tasks to specialized sub-agents!"
        )
    else:
        emit_info("Could not find Supervisor agent.")
    return True


def _on_startup():
    """Pre-warm the manager on startup."""
    _get_manager()


# Register all callbacks
register_callback("startup", _on_startup)
register_callback("register_agents", _register_agents)
register_callback("register_tools", _register_delegation_tools)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("custom_command", _on_custom_command)

logger.debug("Delegation Manager plugin callbacks registered")
