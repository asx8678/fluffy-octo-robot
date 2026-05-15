import asyncio
import atexit
import concurrent.futures
import logging
import traceback
from collections.abc import Callable
from typing import Any, Literal

PhaseType = Literal[
    "startup",
    "shutdown",
    "invoke_agent",
    "agent_exception",
    "version_check",
    "edit_file",
    "create_file",
    "replace_in_file",
    "delete_snippet",
    "delete_file",
    "run_shell_command",
    "load_model_config",
    "load_models_config",
    "load_prompt",
    "agent_reload",
    "custom_command",
    "custom_command_help",
    "file_permission",
    "pre_tool_call",
    "post_tool_call",
    "stream_event",
    "register_tools",
    "register_agents",
    "register_model_type",
    "get_model_system_prompt",
    "prepare_model_prompt",
    "agent_run_start",
    "agent_run_end",
    "agent_run_result",
    "register_model_providers",
    "message_history_processor_start",
    "message_history_processor_end",
    "on_message",
    "agent_run_context",
    "agent_run_cancel",
    "should_skip_fallback_render",
]
CallbackFunc = Callable[..., Any]

# (priority, func) tuples — higher priority runs first.
_callbacks: dict[PhaseType, list[tuple[int, CallbackFunc]]] = {
    "startup": [],
    "shutdown": [],
    "invoke_agent": [],
    "agent_exception": [],
    "version_check": [],
    "edit_file": [],
    "create_file": [],
    "replace_in_file": [],
    "delete_snippet": [],
    "delete_file": [],
    "run_shell_command": [],
    "load_model_config": [],
    "load_models_config": [],
    "load_prompt": [],
    "agent_reload": [],
    "custom_command": [],
    "custom_command_help": [],
    "file_permission": [],
    "pre_tool_call": [],
    "post_tool_call": [],
    "stream_event": [],
    "register_tools": [],
    "register_agents": [],
    "register_model_type": [],
    "get_model_system_prompt": [],
    "prepare_model_prompt": [],
    "agent_run_start": [],
    "agent_run_end": [],
    "agent_run_result": [],
    "register_model_providers": [],
    "message_history_processor_start": [],
    "message_history_processor_end": [],
    "on_message": [],
    "agent_run_context": [],
    "agent_run_cancel": [],
    "should_skip_fallback_render": [],
}

# Pre-sorted cache: populated lazily by get_callbacks(), invalidated on
# register/unregister/clear. Avoids sorting the (priority, func) tuples
# on every dispatch.
_sorted_cache: dict[PhaseType, list[CallbackFunc]] = {}

logger = logging.getLogger(__name__)
# FREE-THREADED: ThreadPoolExecutor is compatible with free-threaded Python 3.14 —
# no GIL contention for I/O-bound callback work.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

# ---------------------------------------------------------------------------
# Deferred (atomic) registration support
# ---------------------------------------------------------------------------

# When True, register_callback buffers calls instead of committing them.
_defer_mode: bool = False
_deferred_registrations: list[tuple[PhaseType, CallbackFunc, int]] = []


def begin_deferred() -> None:
    """Enter deferred registration mode.

    While active, ``register_callback`` buffers calls instead of committing
    them.  Call ``commit_deferred()`` to apply the batch or
    ``rollback_deferred()`` to discard it.
    """
    global _defer_mode
    _defer_mode = True
    _deferred_registrations.clear()


def commit_deferred() -> list[str]:
    """Commit all buffered registrations atomically.

    Validates the full batch first, then applies every registration.  If any
    application fails after partial commit, all successfully committed entries
    are rolled back and a ``RuntimeError`` is raised.

    Returns a list of non-fatal validation warnings (empty on success).
    """
    global _defer_mode
    _defer_mode = False

    batch = list(_deferred_registrations)
    _deferred_registrations.clear()

    if not batch:
        return []

    # --- Phase 1: validate everything before touching state ---
    warnings: list[str] = []
    seen_keys: set[tuple[PhaseType, int, str]] = set()
    for phase, func, _priority in batch:
        if phase not in _callbacks:
            _defer_mode = False
            raise ValueError(
                f"Deferred registration references unsupported phase: {phase}"
            )
        if not callable(func):
            raise TypeError(f"Deferred callback must be callable, got {type(func)}")
        key = (phase, id(func), func.__name__)
        if key in seen_keys:
            warnings.append(
                f"Duplicate deferred registration: {func.__name__} for '{phase}'"
            )
        seen_keys.add(key)

    # --- Phase 2: apply; rollback on any unexpected error ---
    committed: list[tuple[PhaseType, CallbackFunc, int]] = []
    try:
        for phase, func, priority in batch:
            # Bypass the duplicate-is-func check in register_callback so that
            # deferred registrations for *different* plugins can coexist.
            # We still guard against the exact-same-func duplicate at commit
            # time.
            if any(f is func for _, f in _callbacks[phase]):
                warnings.append(
                    f"Skipping duplicate: {func.__name__} already in '{phase}'"
                )
                continue
            _callbacks[phase].append((priority, func))
            _sorted_cache.pop(phase, None)  # Invalidate sorted cache
            committed.append((phase, func, priority))
            logger.debug(
                f"Committed deferred callback {func.__name__} for "
                f"phase '{phase}' (priority={priority})"
            )
    except Exception:
        # Rollback everything we managed to commit
        for phase, func, _priority in committed:
            for idx, (_, existing_func) in enumerate(_callbacks[phase]):
                if existing_func is func:
                    del _callbacks[phase][idx]
                    _sorted_cache.pop(phase, None)  # Invalidate sorted cache
                    break
        logger.error(
            "Deferred commit failed; rolled back %d registrations",
            len(committed),
        )
        raise

    logger.debug("Committed %d deferred registrations", len(committed))
    return warnings


def rollback_deferred() -> None:
    """Discard all buffered registrations without committing."""
    global _defer_mode
    count = len(_deferred_registrations)
    _defer_mode = False
    _deferred_registrations.clear()
    logger.debug("Rolled back %d deferred registrations", count)


def _shutdown_executor() -> None:
    """Gracefully shut down the callback ThreadPoolExecutor.

    Called automatically at interpreter exit via ``atexit``.  Plugins that
    spawn long-running threads inside callbacks should clean themselves up
    in response to the ``shutdown`` hook; this function only terminates the
    executor that runs those callbacks.
    """
    try:
        _executor.shutdown(wait=True, cancel_futures=True)
        logger.debug("Callback executor shut down cleanly")
    except Exception as exc:
        logger.warning(f"Callback executor shutdown error: {exc}")


atexit.register(_shutdown_executor)


def register_callback(phase: PhaseType, func: CallbackFunc, priority: int = 0) -> None:
    if phase not in _callbacks:
        raise ValueError(
            f"Unsupported phase: {phase}. Supported phases: {list(_callbacks.keys())}"
        )

    if not callable(func):
        raise TypeError(f"Callback must be callable, got {type(func)}")

    # In deferred mode, buffer the registration for later atomic commit
    if _defer_mode:
        _deferred_registrations.append((phase, func, priority))
        _sorted_cache.pop(phase, None)  # Invalidate sorted cache
        logger.debug(
            f"Buffered deferred callback {func.__name__} for "
            f"phase '{phase}' (priority={priority})"
        )
        return

    # Prevent duplicate registration of the same callback function
    # This can happen if plugins are accidentally loaded multiple times
    for _existing_priority, existing_func in _callbacks[phase]:
        if existing_func is func:
            logger.debug(
                f"Callback {func.__name__} already registered for phase '{phase}', skipping"
            )
            return

    _callbacks[phase].append((priority, func))
    _sorted_cache.pop(phase, None)  # Invalidate sorted cache
    logger.debug(
        f"Registered async callback {func.__name__} for phase '{phase}' (priority={priority})"
    )


def unregister_callback(phase: PhaseType, func: CallbackFunc) -> bool:
    if phase not in _callbacks:
        return False

    for idx, (_existing_priority, existing_func) in enumerate(_callbacks[phase]):
        if existing_func is func:
            del _callbacks[phase][idx]
            _sorted_cache.pop(phase, None)  # Invalidate sorted cache
            logger.debug(
                f"Unregistered async callback {func.__name__} from phase '{phase}'"
            )
            return True
    return False


def clear_callbacks(phase: PhaseType | None = None) -> None:
    if phase is None:
        for p in _callbacks:
            _callbacks[p].clear()
        logger.debug("Cleared all async callbacks")
    else:
        if phase in _callbacks:
            _callbacks[phase].clear()
            logger.debug(f"Cleared async callbacks for phase '{phase}'")
    _sorted_cache.clear()


def get_callbacks(phase: PhaseType) -> list[CallbackFunc]:
    """Return callbacks for *phase* sorted by priority (highest first).

    Uses a pre-sorted cache that is invalidated on register/unregister/clear.
    """
    cached = _sorted_cache.get(phase)
    if cached is not None:
        return list(cached)

    callbacks = _callbacks.get(phase, [])
    if not callbacks:
        _sorted_cache[phase] = []
        return []

    # Sort by priority descending, then by registration order (stable sort)
    sorted_callbacks = sorted(callbacks, key=lambda item: item[0], reverse=True)
    result = [func for _priority, func in sorted_callbacks]
    _sorted_cache[phase] = result
    return list(result)


def count_callbacks(phase: PhaseType | None = None) -> int:
    if phase is None:
        return sum(len(callbacks) for callbacks in _callbacks.values())
    return len(_callbacks.get(phase, []))


def fire_callbacks(phase: PhaseType, *args, **kwargs) -> None:
    """Fire callbacks without blocking; async callbacks run in the background.

    Useful for observation hooks (like ``on_message``) that must not delay
    the caller.  Exceptions are logged and swallowed.
    """
    callbacks = get_callbacks(phase)
    if not callbacks:
        return

    for callback in callbacks:
        try:
            result = callback(*args, **kwargs)
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(result)
                    task.add_done_callback(
                        lambda t: logger.debug("Fire-and-forget callback completed")
                    )
                except RuntimeError:
                    _executor.submit(asyncio.run, result)
        except Exception as e:
            logger.debug(f"Fire-and-forget callback {callback.__name__} failed: {e}")


def _trigger_callbacks_sync(phase: PhaseType, *args, **kwargs) -> list[Any]:
    if not _callbacks.get(phase):
        return []
    callbacks = get_callbacks(phase)
    if not callbacks:
        logger.debug(f"No callbacks registered for phase '{phase}'")
        return []

    results = []
    for callback in callbacks:
        try:
            result = callback(*args, **kwargs)
            # Handle async callbacks - if we get a coroutine, run it
            if asyncio.iscoroutine(result):
                try:
                    asyncio.get_running_loop()
                    # We're in an async context (e.g., the TUI).
                    # Run the coroutine in a separate thread so it gets
                    # its own event loop. 30s timeout prevents a
                    # misbehaving hook from freezing the session.
                    future = _executor.submit(asyncio.run, result)
                    result = future.result(timeout=30)
                except RuntimeError:
                    # No running loop — we're in a sync/worker thread.
                    result = asyncio.run(result)
            results.append(result)
            logger.debug(f"Successfully executed callback {callback.__name__}")
        except Exception as e:
            logger.error(
                f"Callback {callback.__name__} failed in phase '{phase}': {e}\n"
                f"{traceback.format_exc()}"
            )
            results.append(None)

    return results


async def _trigger_callbacks(phase: PhaseType, *args, **kwargs) -> list[Any]:
    """Trigger all registered callbacks for *phase* in priority order.

    Hook execution order: callbacks run from highest priority to lowest.
    For ``run_shell_command``, the caller (``command_runner.py``) iterates
    through results in priority order and the **first non-None** result
    containing ``{"pre_executed": True, ...}`` wins — subsequent results
    are ignored.

    Intended priority chain for ``run_shell_command``:
    """
    if not _callbacks.get(phase):
        return []
    callbacks = get_callbacks(phase)

    if not callbacks:
        logger.debug(f"No callbacks registered for phase '{phase}'")
        return []

    logger.debug(f"Triggering {len(callbacks)} async callbacks for phase '{phase}'")

    results = []
    for callback in callbacks:
        try:
            result = callback(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            results.append(result)
            logger.debug(f"Successfully executed async callback {callback.__name__}")
        except Exception as e:
            logger.error(
                f"Async callback {callback.__name__} failed in phase '{phase}': {e}\n"
                f"{traceback.format_exc()}"
            )
            results.append(None)

    return results


async def on_startup() -> list[Any]:
    callbacks = get_callbacks("startup")
    results: list[Any] = []
    failed_names: list[str] = []
    for callback in callbacks:
        try:
            result = callback()
            if asyncio.iscoroutine(result):
                result = await result
            results.append(result)
            logger.debug(f"Successfully executed async callback {callback.__name__}")
        except Exception as e:
            logger.error(
                f"Async callback {callback.__name__} failed in phase 'startup': {e}\n"
                f"{traceback.format_exc()}"
            )
            failed_names.append(callback.__name__)
            results.append(None)
    if failed_names:
        count = len(failed_names)
        names_str = ", ".join(failed_names)
        # TODO: PEP 750 t-string — use templatelib when stable
        logger.warning(f"{count} startup callback(s) failed: {names_str}")
        from code_muse.messaging import emit_warning

        # TODO: PEP 750 t-string — use templatelib when stable
        emit_warning(f"⚠️ {count} plugin(s) failed to load: {names_str}")

    # Report Cython status from the core package
    import code_muse

    if code_muse.CYTHON_ENABLED:
        from code_muse.messaging import emit_success

        emit_success(
            # TODO: PEP 750 t-string — use templatelib when stable
            f"✅ Cython enabled — {code_muse.PYX_MODULE_COUNT} modules compiled"
        )
    else:
        from code_muse.messaging import emit_warning

        emit_warning("⚠️ Cython not available — running in pure Python mode")
    return results


async def on_shutdown() -> list[Any]:
    return await _trigger_callbacks("shutdown")


async def on_invoke_agent(*args, **kwargs) -> list[Any]:
    return await _trigger_callbacks("invoke_agent", *args, **kwargs)


async def on_agent_exception(exception: Exception, *args, **kwargs) -> list[Any]:
    return await _trigger_callbacks("agent_exception", exception, *args, **kwargs)


async def on_version_check(*args, **kwargs) -> list[Any]:
    return await _trigger_callbacks("version_check", *args, **kwargs)


def on_load_model_config(*args, **kwargs) -> list[Any]:
    return _trigger_callbacks_sync("load_model_config", *args, **kwargs)


def on_load_models_config() -> list[Any]:
    """Trigger callbacks to load additional model configurations.

    Plugins can register callbacks that return a dict of model configurations
    to be merged with the built-in models.json. Plugin models override built-in
    models with the same name.

    Returns:
        List of model config dicts from all registered callbacks.
    """
    return _trigger_callbacks_sync("load_models_config")


def on_edit_file(*args, **kwargs) -> Any:
    return _trigger_callbacks_sync("edit_file", *args, **kwargs)


def on_create_file(*args, **kwargs) -> Any:
    return _trigger_callbacks_sync("create_file", *args, **kwargs)


def on_replace_in_file(*args, **kwargs) -> Any:
    return _trigger_callbacks_sync("replace_in_file", *args, **kwargs)


def on_delete_snippet(*args, **kwargs) -> Any:
    return _trigger_callbacks_sync("delete_snippet", *args, **kwargs)


def on_delete_file(*args, **kwargs) -> Any:
    return _trigger_callbacks_sync("delete_file", *args, **kwargs)


async def on_run_shell_command(*args, **kwargs) -> Any:
    """Trigger callbacks for shell command execution.

    Execution order and resolution rule:
        Callbacks fire in priority order (highest first).  The caller
        (``command_runner.py``) iterates the result list and the **first
        non-None** dict containing ``"pre_executed": True`` wins — all
        remaining results are ignored.

    Intended priority chain for ``run_shell_command``:

        2. ``policy_engine`` / ``shell_safety`` (priority 50) — enforces allow/deny/ask-user rules
        3. ``shell_minimizer`` (priority 0) — compresses known command output

    Future handlers **must** pass an explicit ``priority`` argument to
    ``register_callback()`` to position themselves correctly in the
    pipeline.

    Args:
        *args: Positional arguments passed to callbacks (context, command, ...).
        **kwargs: Keyword arguments passed to callbacks (cwd, timeout, ...).

    Returns:
        List of results from all registered callbacks.
    """
    return await _trigger_callbacks("run_shell_command", *args, **kwargs)


def on_agent_reload(*args, **kwargs) -> Any:
    return _trigger_callbacks_sync("agent_reload", *args, **kwargs)


def on_load_prompt():
    return _trigger_callbacks_sync("load_prompt")


def on_custom_command_help() -> list[Any]:
    """Collect custom command help entries from plugins.

    Each callback should return a list of tuples [(name, description), ...]
    or a single tuple, or None. We'll flatten and sanitize results.
    """
    return _trigger_callbacks_sync("custom_command_help")


def on_custom_command(command: str, name: str) -> list[Any]:
    """Trigger custom command callbacks.

    This allows plugins to register handlers for slash commands
    that are not built into the core command handler.

    Args:
        command: The full command string (e.g., "/foo bar baz").
        name: The primary command name without the leading slash (e.g., "foo").

    Returns:
        Implementations may return:
        - True if the command was handled (and no further action is needed)
        - A string to be processed as user input by the caller
        - None to indicate not handled
    """
    return _trigger_callbacks_sync("custom_command", command, name)


def on_file_permission(
    context: Any,
    file_path: str,
    operation: str,
    preview: str | None = None,
    message_group: str | None = None,
    operation_data: Any = None,
) -> list[Any]:
    """Trigger file permission callbacks.

    This allows plugins to register handlers for file permission checks
    before file operations are performed.

    Args:
        context: The operation context
        file_path: Path to the file being operated on
        operation: Description of the operation
        preview: Optional preview of changes (deprecated - use operation_data instead)
        message_group: Optional message group
        operation_data: Operation-specific data for preview generation (recommended)

    Returns:
        List of boolean results from permission handlers.
        Returns True if permission should be granted, False if denied.
    """
    # PERF-08: Skip callback overhead entirely in yolo mode
    from code_muse.config import get_yolo_mode

    if get_yolo_mode():
        return [True]

    # For backward compatibility, if operation_data is provided, prefer it over preview
    if operation_data is not None:
        preview = None
    return _trigger_callbacks_sync(
        "file_permission",
        context,
        file_path,
        operation,
        preview,
        message_group,
        operation_data,
    )


async def on_pre_tool_call(
    tool_name: str, tool_args: dict, context: Any = None
) -> list[Any]:
    """Trigger callbacks before a tool is called.

    This allows plugins to inspect, modify, or log tool calls before
    they are executed.

    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments being passed to the tool
        context: Optional context data for the tool call

    Returns:
        List of results from registered callbacks.
    """
    return await _trigger_callbacks("pre_tool_call", tool_name, tool_args, context)


async def on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> list[Any]:
    """Trigger callbacks after a tool completes.

    This allows plugins to inspect tool results, log execution times,
    or perform post-processing.

    Args:
        tool_name: Name of the tool that was called
        tool_args: Arguments that were passed to the tool
        result: The result returned by the tool
        duration_ms: Execution time in milliseconds
        context: Optional context data for the tool call

    Returns:
        List of results from registered callbacks.
    """
    return await _trigger_callbacks(
        "post_tool_call", tool_name, tool_args, result, duration_ms, context
    )


async def on_stream_event(
    event_type: str, event_data: Any, agent_session_id: str | None = None
) -> list[Any]:
    """Trigger callbacks for streaming events.

    This allows plugins to react to streaming events in real-time,
    such as tokens being generated, tool calls starting, etc.

    Args:
        event_type: Type of the streaming event
        event_data: Data associated with the event
        agent_session_id: Optional session ID of the agent emitting the event

    Returns:
        List of results from registered callbacks.
    """
    return await _trigger_callbacks(
        "stream_event", event_type, event_data, agent_session_id
    )


def on_stream_event_sync(
    event_type: str, event_data: Any, agent_session_id: str | None = None
) -> list[Any]:
    """Synchronous version of on_stream_event — no task creation.

    Used for high-frequency events (part_delta) where async overhead
    would be wasteful. Callbacks are fired synchronously in the caller's
    thread.
    """
    return _trigger_callbacks_sync(
        "stream_event", event_type, event_data, agent_session_id
    )


def on_register_tools() -> list[dict[str, Any]]:
    """Collect custom tool registrations from plugins.

    Each callback should return a list of dicts with:
    - "name": str - the tool name
    - "register_func": callable - function that takes an agent and registers the tool

    Example return: [{"name": "my_tool", "register_func": register_my_tool}]
    """
    return _trigger_callbacks_sync("register_tools")


def on_register_agents() -> list[dict[str, Any]]:
    """Collect custom agent registrations from plugins.

    Each callback should return a list of dicts with either:
    - "name": str, "class": Type[BaseAgent] - for Python agent classes
    - "name": str, "json_path": str - for JSON agent files

    Example return: [{"name": "my-agent", "class": MyAgentClass}]
    """
    return _trigger_callbacks_sync("register_agents")


def on_register_model_types() -> list[dict[str, Any]]:
    """Collect custom model type registrations from plugins.

    This hook allows plugins to register custom model types that can be used
    in model configurations. Each callback should return a list of dicts with:
    - "type": str - the model type name (e.g., "claude_code")
    - "handler": callable - function(model_name, model_config, config) -> model instance

    The handler function receives:
    - model_name: str - the name of the model being created
    - model_config: dict - the model's configuration from models.json
    - config: dict - the full models configuration

    The handler should return a model instance or None if creation fails.

    Example callback:
        def register_my_model_types():
            return [{
                "type": "my_custom_type",
                "handler": create_my_custom_model,
            }]

    Example return: [{"type": "my_custom_type", "handler": create_my_custom_model}]
    """
    return _trigger_callbacks_sync("register_model_type")


def on_get_model_system_prompt(
    model_name: str, default_system_prompt: str, user_prompt: str
) -> list[dict[str, Any]]:
    """Allow plugins to provide custom system prompts for specific model types.

    This hook allows plugins to override the system prompt handling for custom
    model types (like claude_code models). Each callback receives
    the model name and should return a dict if it handles that model type, or None.

    Args:
        model_name: The name of the model being used (e.g., "claude-code-sonnet")
        default_system_prompt: The default system prompt from the agent
        user_prompt: The user's prompt/message

    Each callback should return a dict with:
    - "instructions": str - the system prompt/instructions to use
    - "user_prompt": str - the (possibly modified) user prompt
    - "handled": bool - True if this callback handled the model

    Or return None if the callback doesn't handle this model type.

    Example callback:
        def get_my_model_system_prompt(model_name, default_system_prompt, user_prompt):
            if model_name.startswith("my-custom-"):
                return {
                    "instructions": "You are MyCustomBot.",
                    "user_prompt": f"{default_system_prompt}\n\n{user_prompt}",
                    "handled": True,
                }
            return None  # Not handled by this callback

    Returns:
        List of results from registered callbacks (dicts or None values).
    """
    return _trigger_callbacks_sync(
        "get_model_system_prompt", model_name, default_system_prompt, user_prompt
    )


def on_prepare_model_prompt(
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    prepend_system_to_user: bool = True,
) -> list[dict[str, Any | None]]:
    """Allow plugins to fully prepare the prompt (instructions + user prompt) for a model.

    This is the hook fired from ``model_utils.prepare_prompt_for_model`` to let
    plugins take over prompt preparation for specific model families (e.g.
    claude-code OAuth models which need a hard-coded instruction string and
    have the system prompt prepended to the user message).

    Unlike ``get_model_system_prompt`` (which is used by augmenting plugins like
    agent_skills), this hook is for plugins that want to *fully handle* the
    prompt prep for a given model. The first callback returning ``handled=True``
    wins; the rest are ignored.

    Args:
        model_name: The name of the model being used.
        system_prompt: The default system prompt from the agent.
        user_prompt: The user's prompt/message.
        prepend_system_to_user: Whether the caller wants system prompt prepended
            to the user prompt (only meaningful for plugins that manipulate the
            user prompt, like claude-code).

    Each callback should return a dict with:
        - ``"handled"``: bool — True if this callback fully prepared the prompt.
        - ``"instructions"``: str — the system prompt/instructions to use.
        - ``"user_prompt"``: str — the (possibly modified) user prompt.
        - ``"is_claude_code"``: bool — (optional) flag preserved on PreparedPrompt.

    Or return ``None`` to indicate "I don't handle this model".

    Returns:
        List of results (dicts or ``None``) from registered callbacks.
    """
    return _trigger_callbacks_sync(
        "prepare_model_prompt",
        model_name,
        system_prompt,
        user_prompt,
        prepend_system_to_user,
    )


async def on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> list[Any]:
    """Trigger callbacks when an agent run starts.

    This fires at the beginning of run, before the agent task is created.
    Useful for:
    - Starting background tasks (like token refresh heartbeats)
    - Logging/analytics
    - Resource allocation

    Args:
        agent_name: Name of the agent starting
        model_name: Name of the model being used
        session_id: Optional session identifier

    Returns:
        List of results from registered callbacks.
    """
    return await _trigger_callbacks(
        "agent_run_start", agent_name, model_name, session_id
    )


async def on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> list[Any]:
    """Trigger callbacks when an agent run ends.

    This fires at the end of run, in the finally block.
    Always fires regardless of success/failure/cancellation.

    Useful for:
    - Stopping background tasks (like token refresh heartbeats)
    - Workflow orchestration (like Ralph's autonomous loop)
    - Logging/analytics
    - Resource cleanup
    - Detecting completion signals in responses

    Args:
        agent_name: Name of the agent that finished
        model_name: Name of the model that was used
        session_id: Optional session identifier
        success: Whether the run completed successfully
        error: Exception if the run failed, None otherwise
        response_text: The final text response from the agent (if successful)
        metadata: Optional dict with additional context (tokens used, etc.)

    Returns:
        List of results from registered callbacks.
    """
    return await _trigger_callbacks(
        "agent_run_end",
        agent_name,
        model_name,
        session_id,
        success,
        error,
        response_text,
        metadata,
    )


async def on_agent_run_result(
    result: Any,
    agent_name: str,
    model_name: str,
) -> list[Any]:
    """Trigger callbacks after an agent run returns a result.

    Fires after ``pydantic_agent.run()`` completes successfully, **before**
    the result is handed back to the caller.  Plugins can inspect the result
    and request an automatic retry (e.g. when an upstream content-filter
    produced a false-positive refusal).

    Callback signature::

        async def my_callback(result, agent_name: str, model_name: str)
            -> dict | None

    To request a retry, return a dict with::

        {
            "retry": True,
            "prompt": "<message to send on retry>",
            "delay": 1.0,          # optional, seconds before retry
        }

    Return ``None`` (or omit a return) to let the result pass through.
    The first callback that returns a retry request wins; the agent
    replays at most a small fixed number of times to prevent runaway loops.

    Args:
        result: The ``RunResult`` returned by ``pydantic_agent.run()``.
        agent_name: Name of the agent that produced the result.
        model_name: Name of the model that was used.

    Returns:
        List of results from registered callbacks.
    """
    return await _trigger_callbacks("agent_run_result", result, agent_name, model_name)


def on_register_model_providers() -> list[Any]:
    """Trigger callbacks to register custom model provider classes.

    Plugins can register callbacks that return a dict mapping provider names
    to model classes.

    Returns:
        List of dicts from all registered callbacks.
    """
    return _trigger_callbacks_sync("register_model_providers")


def on_message_history_processor_start(
    agent_name: str,
    session_id: str | None,
    message_history: list[Any],
    incoming_messages: list[Any],
) -> list[Any]:
    """Trigger callbacks at the start of message history processing.

    This hook fires at the beginning of the message_history_accumulator,
    before any deduplication or processing occurs. Useful for:
    - Logging/debugging message flow
    - Observing raw incoming messages
    - Analytics on message history growth

    Args:
        agent_name: Name of the agent processing messages
        session_id: Optional session identifier
        message_history: Current message history (before processing)
        incoming_messages: New messages being added

    Returns:
        List of results from registered callbacks.
    """
    return _trigger_callbacks_sync(
        "message_history_processor_start",
        agent_name,
        session_id,
        message_history,
        incoming_messages,
    )


def on_message_history_processor_end(
    agent_name: str,
    session_id: str | None,
    message_history: list[Any],
    messages_added: int,
    messages_filtered: int,
) -> list[Any]:
    """Trigger callbacks at the end of message history processing.

    This hook fires at the end of the message_history_accumulator,
    after deduplication and filtering has been applied. Useful for:
    - Logging/debugging final message state
    - Analytics on deduplication effectiveness
    - Observing what was actually added to history

    Args:
        agent_name: Name of the agent processing messages
        session_id: Optional session identifier
        message_history: Final message history (after processing)
        messages_added: Count of new messages that were added
        messages_filtered: Count of messages that were filtered out (dupes/empty)

    Returns:
        List of results from registered callbacks.
    """
    return _trigger_callbacks_sync(
        "message_history_processor_end",
        agent_name,
        session_id,
        message_history,
        messages_added,
        messages_filtered,
    )


async def on_message(message_id: str, message: Any) -> list[Any]:
    """Trigger callbacks when a message is emitted.

    This is the global observation hook for the messaging system.
    For per-message interception with pattern matching, use
    messaging.interceptors.register_interceptor() instead.

    This hook is for observation (logging, analytics, WebSocket forwarding),
    while interceptors are for control (silencing, replacing, redirecting).

    Args:
        message_id: The well-known message identifier (e.g., "tool:edit_file:complete")
        message: The full Pydantic BaseMessage model (or UIMessage for legacy)

    Returns:
        List of results from registered callbacks.
    """
    return await _trigger_callbacks("on_message", message_id, message)


def on_agent_run_context(agent, pydantic_agent, group_id) -> list[Any]:
    """Collect async context managers that should wrap the ``pydantic_agent.run()`` call.

    Each callback returns an async CM (with ``__aenter__``/``__aexit__``) or
    ``None``. The caller composes all non-``None`` results via
    ``contextlib.AsyncExitStack``.

    Returns a list of async context managers (may be empty).
    """
    results = _trigger_callbacks_sync(
        "agent_run_context", agent, pydantic_agent, group_id
    )
    return [r for r in results if r is not None]


async def on_agent_run_cancel(group_id: str) -> list[Any]:
    """Fired when an agent run is cancelled or interrupted.

    Plugins use this to cancel any external workflow tracking the run.
    """
    return await _trigger_callbacks("agent_run_cancel", group_id)


def on_should_skip_fallback_render(agent) -> bool:
    """Return True if any plugin requests skipping the non-streaming fallback render."""
    results = _trigger_callbacks_sync("should_skip_fallback_render", agent)
    return any(r is True for r in results)
