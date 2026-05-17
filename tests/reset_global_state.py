"""Test utility: reset module-level mutable globals between tests.

This is a pragmatic stopgap until the SessionContext migration is complete.
Import and call `reset_global_state()` in tests that need full isolation
from shared module-level dicts/lists/sets.

Usage in tests::

    from tests.reset_global_state import reset_global_state

    def test_my_thing():
        reset_global_state()  # clear all shared state
        # ... test code ...

Or as a fixture::

    @pytest.fixture(autouse=True)
    def _reset_globals():
        reset_global_state()
        yield
        reset_global_state()

NOTE: This is intentionally NOT an autouse fixture in conftest.py because
many tests don't need it and the import overhead would slow the suite.
Use it explicitly where needed.
"""

from __future__ import annotations


def reset_global_state() -> None:
    """Reset all known module-level mutable globals to their initial values.

    Safe to call multiple times. Idempotent. Does NOT reset:
    - threading.Lock / threading.Event instances (they're reusable)
    - immutable singletons (Console, TextMessage templates, etc.)
    - config constants (DEFAULT_SECTION, etc.)
    - logging.Logger instances

    Only resets mutable containers (dicts, lists, sets) and scalar globals
    that accumulate state across test runs.
    """
    # --- agents/agent_manager.py ---
    from code_muse.agents import agent_manager as am

    am._AGENT_REGISTRY.clear()
    am._DISCOVERY_CACHE.clear()
    am._AGENT_HISTORIES.clear()
    am._SESSION_AGENTS_CACHE.clear()

    # --- agents/_builder.py ---
    from code_muse.agents import _builder as ab

    ab._system_prompt_cache.clear()

    # --- callbacks.py ---
    from code_muse import callbacks as cb

    cb._sorted_cache.clear()
    cb._deferred_registrations.clear()

    # --- config/models.py ---
    from code_muse.config import models as cm

    cm._model_validation_cache.clear()
    cm._default_model_cache = None
    cm._default_vision_model_cache = None

    # --- config/parser.py ---
    from code_muse.config import parser as cp

    cp._config_cache = None

    # --- tools/agent_tools.py ---
    from code_muse.tools import agent_tools as at

    at._model_instance_cache.clear()
    at._subagent_agent_cache.clear()

    # --- tools/chrome_cdp/__init__.py ---
    import code_muse.tools.chrome_cdp as cdp

    cdp._PERSISTENT_SESSIONS.clear()
    cdp._ACTIVE_TABS_CACHE.clear()
    cdp._PAGES_CACHE.clear()
    cdp._PENDING.clear()
    cdp._CHROME_WS = None
    cdp._MSG_COUNTER = 0

    # --- tools/skills_tools.py ---
    from code_muse.tools import skills_tools as st

    st._background_jobs.clear()

    # --- tools/background_jobs.py ---
    from code_muse.tools import background_jobs as bj

    bj._BACKGROUND_JOBS.clear()

    # --- tools/command_runner.py ---
    from code_muse.tools import command_runner as cr

    cr._RUNNING_PROCESSES.clear()
    cr._USER_KILLED_PROCESSES.clear()
    cr._ACTIVE_STOP_EVENTS.clear()

    # --- tools/__init__.py ---
    import code_muse.tools as tools_mod

    tools_mod.REMOVED_LEGACY_TOOLS.clear()

    # --- session_storage_helpers.py ---
    from code_muse import session_storage_helpers as ssh

    ssh._LAST_SAVED_HASHES.clear()

    # --- command_line/command_registry.py ---
    from code_muse.command_line import command_registry as reg

    reg._COMMAND_REGISTRY.clear()

    # --- plugins ---
    try:
        from code_muse.plugins.custom_commands import register_callbacks as cc

        cc._command_cache.clear()
    except (ImportError, AttributeError):
        pass

    try:
        from code_muse.plugins.token_ratio_learner import ratios as ratios

        ratios._LEARNED_RATIOS.clear()
    except (ImportError, AttributeError):
        pass

    try:
        from code_muse.plugins.customizable_commands import register_callbacks as cuc

        cuc._custom_commands.clear()
        cuc._command_descriptions.clear()
    except (ImportError, AttributeError):
        pass

    try:
        from code_muse.plugins.debate import register_callbacks as dr
        from code_muse.plugins.debate import state as ds
        from code_muse.plugins.debate import telemetry as dt

        ds._review_history.clear()
        dt._review_timestamps.clear()
        dr._pending_review_indices.clear()
    except (ImportError, AttributeError):
        pass

    try:
        from code_muse.plugins.policy_engine import policy_file_discovery as pfd

        pfd._file_mtimes.clear()
    except (ImportError, AttributeError):
        pass

    try:
        from code_muse.plugins.universal_critic import orchestrator as uco

        uco._ITERATION_TRACKER.clear()
    except (ImportError, AttributeError):
        pass

    try:
        from code_muse.plugins.agent_skills import register_callbacks as asr

        asr._deactivated_skills.clear()
    except (ImportError, AttributeError):
        pass

    try:
        from code_muse.plugins.task_context import detector as tcd

        tcd._previous_message_vectors.clear()
    except (ImportError, AttributeError):
        pass

    # --- model_factory/_plugin_registry.py ---
    try:
        from code_muse.model_factory import _plugin_registry as pr

        pr._CUSTOM_MODEL_PROVIDERS.clear()
    except (ImportError, AttributeError):
        pass

    # --- messaging/spinner/__init__.py ---
    try:
        import code_muse.messaging.spinner as sp

        sp._active_spinners.clear()
    except (ImportError, AttributeError):
        pass

    # --- summarization_agent.py ---
    from code_muse import summarization_agent as sa

    sa._summarization_agent = None
    sa._cached_model_name = None
    # Note: _thread_pool and _summarization_loop are managed via their locks
    # and have cleanup functions; don't forcibly destroy them here.

    # --- messaging/bus.py ---
    from code_muse.messaging import bus as mb

    mb._global_bus = None

    # --- messaging/message_queue.py ---
    from code_muse.messaging import message_queue as mq

    mq._global_queue = None

    # --- interpreter_pool.py ---
    from code_muse import interpreter_pool as ip

    ip._default_executor = None

    # --- terminal_utils.py ---
    from code_muse import terminal_utils as tu

    tu._original_ctrl_handler = None
    tu._keep_ctrl_c_disabled = False

    # --- command_line/clipboard.py ---
    from code_muse.command_line import clipboard as clip

    clip._clipboard_manager = None
    clip._last_clipboard_capture = 0.0

    # --- _models_config_utils.py ---
    from code_muse import _models_config_utils as mcu

    mcu._models_config_cache = (None, None)
