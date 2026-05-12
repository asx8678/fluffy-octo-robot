"""Filter Engine plugin for Muse.

Intercepts shell commands, classifies them, applies compression strategies,
and returns compact results to reduce token usage.
"""

from code_muse.plugins.filter_engine.classifier import CommandClassifier
from code_muse.plugins.filter_engine.dispatcher import FilterDispatcher
from code_muse.plugins.filter_engine.register_callbacks import (
    filter_engine_callback,
)
from code_muse.plugins.filter_engine.registry import StrategyRegistry

# Import strategies so they self-register with the strategy registry
from code_muse.plugins.filter_engine.strategies import (  # noqa: F401
    code,
    git,
    lint,
    test,
)
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel, get_verbosity

__all__ = [
    "CommandClassifier",
    "FilterDispatcher",
    "StrategyRegistry",
    "VerbosityLevel",
    "filter_engine_callback",
    "get_verbosity",
]
