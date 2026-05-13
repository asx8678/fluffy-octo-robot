"""Multi-Agent Delegation Manager — supervisor agent with sub-agent delegation."""

from code_muse.plugins.delegation_manager.delegation_manager import DelegationManager
from code_muse.plugins.delegation_manager.supervisor_agent import SupervisorAgent


def get_delegation_manager() -> DelegationManager:
    """Get the singleton DelegationManager instance."""
    from code_muse.plugins.delegation_manager.register_callbacks import _get_manager

    return _get_manager()


def get_supervisor_agent() -> SupervisorAgent:
    """Get a fresh SupervisorAgent instance."""
    return SupervisorAgent()


__all__ = [
    "DelegationManager",
    "SupervisorAgent",
    "get_delegation_manager",
    "get_supervisor_agent",
]
