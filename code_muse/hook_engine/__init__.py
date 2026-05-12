"""Hook engine package for Muse."""

from . import aliases
from .engine import HookEngine
from .models import (
    EventData,
    ExecutionResult,
    HookConfig,
    HookRegistry,
    ProcessEventResult,
)

__all__ = [
    "HookEngine",
    "HookConfig",
    "EventData",
    "ExecutionResult",
    "ProcessEventResult",
    "HookRegistry",
    "aliases",
]
