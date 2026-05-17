import asyncio
import atexit
import logging
import threading

# FREE-THREADED: ThreadPoolExecutor is compatible with free-threaded Python 3.14 —
# no GIL contention for I/O-bound summarization work.
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic_ai import Agent

from code_muse._models_config_utils import (
    get_cached_config,
    invalidate_models_config_cache,
    models_config_fingerprint,
    set_cached_config,
)
from code_muse.config import get_summarization_model_name
from code_muse.model_factory import ModelFactory, make_model_settings

logger = logging.getLogger(__name__)

# Keep a module-level agent reference to avoid rebuilding per call
_summarization_agent = None
# FREE-THREADED: _agent_lock guards sync-only agent cache access.
_agent_lock = threading.Lock()

# P2-05/PERF-05: track the model name the cached agent was built for
_cached_model_name: str | None = None

# Safe sync runner for async agent.run calls
# Avoids "event loop is already running" by offloading to a separate thread loop when needed
_thread_pool: ThreadPoolExecutor | None = None

# Reload counter
_reload_count = 0


# ---------------------------------------------------------------------------
# P2-05/PERF-05: Model config cache with mtime invalidation
# (fingerprint, cache, lock, and invalidate live in _models_config_utils)
# ---------------------------------------------------------------------------


def get_cached_models_config() -> dict[str, Any]:
    """Return the models config, using a cache invalidated by mtime/hash changes.

    This avoids re-reading ``models.json`` and extra model files on every call
    to ``ModelFactory.load_config()`` when nothing has changed. The cache is
    invalidated when any source file's mtime changes.

    Falls back to ``ModelFactory.load_config()`` on any error.
    """
    fingerprint = models_config_fingerprint()

    cached_config, cached_fp = get_cached_config()
    if cached_config is not None and cached_fp == fingerprint:
        return cached_config

    # Cache miss — reload. Let exceptions propagate so callers
    # (including reload_summarization_agent) see the same errors they
    # would have seen without the cache.
    config = ModelFactory.load_config()
    set_cached_config(config, fingerprint)
    return config


# invalidate_models_config_cache is imported from _models_config_utils


def _ensure_thread_pool():
    global _thread_pool
    # Check if pool is None OR if it's been shutdown
    if _thread_pool is None or _thread_pool._shutdown:
        # FREE-THREADED: ThreadPoolExecutor is compatible with free-threaded Python 3.14.
        _thread_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="summarizer-loop"
        )
    return _thread_pool


def _shutdown_thread_pool():
    global _thread_pool
    if _thread_pool is not None:
        _thread_pool.shutdown(wait=False)
        _thread_pool = None


atexit.register(_shutdown_thread_pool)


# Persistent event loop for summarization — created once, reused across calls.
# Avoids the ~5-10ms overhead of new_event_loop() per compaction cycle.
_summarization_loop: asyncio.AbstractEventLoop | None = None
_summarization_loop_lock = threading.Lock()


def _get_event_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for summarization.

    Creates the loop once on first call; reuses it thereafter.
    Thread-safe via _summarization_loop_lock.
    """
    global _summarization_loop
    if _summarization_loop is not None and not _summarization_loop.is_closed():
        return _summarization_loop
    with _summarization_loop_lock:
        if _summarization_loop is None or _summarization_loop.is_closed():
            _summarization_loop = asyncio.new_event_loop()
    return _summarization_loop


def _shutdown_event_loop():
    """Clean shutdown of the persistent summarization event loop."""
    global _summarization_loop
    loop = _summarization_loop
    if loop is not None and not loop.is_closed():
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
        except Exception:
            pass
    _summarization_loop = None


atexit.register(_shutdown_event_loop)


async def _run_agent_async(agent: Agent, prompt: str, message_history: list):
    return await agent.run(prompt, message_history=message_history)


class SummarizationError(Exception):
    """Raised when summarization fails with details about the failure."""

    def __init__(self, message: str, original_error: Exception | None = None):
        self.original_error = original_error
        super().__init__(message)


def run_summarization_sync(prompt: str, message_history: list) -> list:
    """Run the summarization agent synchronously.

    Raises:
        SummarizationError: If summarization fails for any reason.
    """
    try:
        agent = get_summarization_agent()
    except Exception as e:
        raise SummarizationError(
            f"Failed to initialize summarization agent: {type(e).__name__}: {e}",
            original_error=e,
        ) from e

    # Handle claude-code models: prepend system prompt to user prompt
    from code_muse.model_utils import prepare_prompt_for_model

    model_name = get_summarization_model_name()
    prepared = prepare_prompt_for_model(
        model_name, _get_summarization_instructions(), prompt
    )
    prompt = prepared.user_prompt

    # Inject protected facts into summarization instructions to preserve them
    try:
        from code_muse.plugins.task_context.protected_facts import (
            get_protected_fact_manager,
        )

        mgr = get_protected_fact_manager()
        fact_block = mgr.get_prompt_block()
        if fact_block:
            prompt += (
                "\n\nIMPORTANT — These facts MUST be preserved "
                "verbatim in your summary:\n" + fact_block
            )
    except Exception:
        pass

    logger.info(
        "Summarization LLM call starting: model=%s, messages=%d",
        model_name,
        len(message_history),
    )

    def _run_in_thread():
        """Run the async agent using the persistent summarization event loop.

        Uses run_until_complete instead of asyncio.run to avoid shutting down
        the default executor (which may break plugins in the main thread).
        The loop is reused across calls — no per-call creation/cleanup overhead.
        """
        loop = _get_event_loop()
        coro = agent.run(prompt, message_history=message_history)
        return loop.run_until_complete(coro)

    try:
        # Always use thread pool since we're likely in an existing event loop
        pool = _ensure_thread_pool()
        result = pool.submit(_run_in_thread).result()
        new_msgs = result.new_messages()
        logger.info(
            "Summarization LLM call complete: input=%d msgs, output=%d msgs",
            len(message_history),
            len(new_msgs),
        )
        return new_msgs
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else "(no details available)"
        raise SummarizationError(
            f"LLM call failed during summarization: [{error_type}] {error_msg}",
            original_error=e,
        ) from e


def _get_summarization_instructions() -> str:
    """Get the system instructions for the summarization agent."""
    return """You are a message summarization expert. Your task is to summarize conversation messages
while preserving important context and information. The summaries should be concise but capture the essential content
and intent of the original messages. This is to help manage token usage in a conversation history
while maintaining context for the AI to continue the conversation effectively.

When summarizing:
1. Keep summary concise but informative
2. Preserve important context and key information and decisions
3. Keep any important technical details
4. Don't summarize the system message
5. Make sure all tool calls and responses are summarized, as they are vital
6. Focus on token usage efficiency and system message preservation"""


def reload_summarization_agent():
    """Create a specialized agent for summarizing messages when context limit is reached."""
    from code_muse.model_utils import prepare_prompt_for_model

    # Always bust the cache on explicit reload — the caller expects fresh config
    invalidate_models_config_cache()
    models_config = get_cached_models_config()
    model_name = get_summarization_model_name()
    model = ModelFactory.get_model(model_name, models_config)

    # Handle claude-code models: swap instructions (prompt prepending happens in run_summarization_sync)
    instructions = _get_summarization_instructions()
    prepared = prepare_prompt_for_model(
        model_name, instructions, "", prepend_system_to_user=False
    )
    instructions = prepared.instructions

    model_settings = make_model_settings(model_name)

    agent = Agent(
        model=model,
        instructions=instructions,
        output_type=str,
        retries=1,  # Fewer retries for summarization
        model_settings=model_settings,
    )
    # NOTE: We intentionally don't wrap the summarization agent.
    # Summarization is a simple one-shot call that doesn't need durable execution,
    # and wrapping can cause async event loop conflicts with run_sync().
    return agent


def get_summarization_agent(force_reload=False):
    """Retrieve the summarization agent, caching across calls.

    P2-05/PERF-05: The default is now ``force_reload=False``. The agent is
    rebuilt only when:
    - ``force_reload=True`` is explicitly passed
    - The summarization model name has changed since the last build
    - No agent has been built yet (first call)

    Args:
        force_reload: When True, unconditionally rebuild the agent.

    Returns:
        A ``pydantic_ai.Agent`` configured for summarization.
    """
    global _summarization_agent, _cached_model_name
    current_model = get_summarization_model_name()
    with _agent_lock:
        needs_reload = (
            force_reload
            or _summarization_agent is None
            or _cached_model_name != current_model
        )
        if needs_reload:
            _summarization_agent = reload_summarization_agent()
            _cached_model_name = current_model
        return _summarization_agent
