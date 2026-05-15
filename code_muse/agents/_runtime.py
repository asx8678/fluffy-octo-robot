"""Agent run orchestration: streaming retries, signal/key cancellation.

Replaces the monolithic ``BaseAgent.run`` coroutine. Everything here
is a free function; the agent is passed in explicitly. Integration points
preserved verbatim:

- Plugin-supplied async context managers wrap the run (see
  ``on_agent_run_context``); used e.g. by plugins to set a workflow
  ID and swap external toolsets in/out.
- Signal-vs-key-listener branch driven by ``cancel_agent_uses_signal()``
- Windows terminal reset on graceful SIGINT
- ``is_awaiting_user_input()`` guards interrupt handling
- Subagent task cancellation via ``_active_subagent_tasks``
- ``_RUNNING_PROCESSES`` check before cancelling the agent
"""

import asyncio
import dataclasses
import signal
import threading
import time
import uuid
from collections.abc import Sequence
from contextlib import AsyncExitStack, suppress
from typing import Any

from pydantic_ai import (
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    UsageLimitExceeded,
    UsageLimits,
)

# Python 3.11+ builtin; graceful fallback for 3.10
try:
    from builtins import BaseExceptionGroup  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - 3.10 only
    BaseExceptionGroup = Exception  # type: ignore[misc,assignment]

from code_muse.agents import _key_listeners, _run_signals
from code_muse.agents._builder import build_pydantic_agent
from code_muse.agents._diagnostics import emit_exception_diagnostics
from code_muse.agents._non_streaming_render import (
    StreamingTextDetector,
    render_result_without_streaming,
    should_render_fallback,
)
from code_muse.agents._run_utils import (
    RunOutcome,
    RunStats,
    _build_prompt_payload,
    _collect_exceptions,
    _extract_response_text,
    _model_allows_streaming,
    _sanitize_prompt,
    _should_prepend_system_prompt,
)
from code_muse.agents._streaming_retry import streaming_retry
from code_muse.agents._tool_circuit_breaker import (
    _tool_error_tracker_ctx,
    _ToolErrorTracker,
)
from code_muse.agents.event_stream_handler import event_stream_handler
from code_muse.callbacks import (
    on_agent_exception,
    on_agent_run_cancel,
    on_agent_run_context,
    on_agent_run_end,
    on_agent_run_result,
    on_agent_run_start,
    on_should_skip_fallback_render,
)
from code_muse.config import (
    get_enable_streaming,
    get_max_consecutive_tool_errors,
    get_max_hook_retries,
    get_message_limit,
    get_overall_run_timeout_seconds,
)
from code_muse.keymap import cancel_agent_uses_signal
from code_muse.messaging import emit_info, emit_warning
from code_muse.tools.command_runner import is_awaiting_user_input

# ---- Emergency compaction for context overflow -------------------------------


# Patterns that indicate the model couldn't process the request due to
# context size. Checked case-insensitively against the full exception chain.
_CONTEXT_OVERFLOW_PATTERNS = (
    "context_length_exceeded",
    "maximum context length",
    "request too large",
    "token limit",
    "content_too_large",
    "max_tokens_exceeded",
    "prompt is too long",
    "input is too long",
    "exceeds the model's maximum",
    "reduce the length",
    "too many tokens",
)


def _is_context_overflow_error(exc: Exception) -> bool:
    """Walk the exception chain checking for context overflow signals."""
    current: BaseException | None = exc
    while current is not None:
        msg = str(current).lower()
        if any(p in msg for p in _CONTEXT_OVERFLOW_PATTERNS):
            return True
        current = current.__cause__ or current.__context__
    return False


def _emergency_compact(agent: Any) -> bool:
    """Aggressively compact agent message history when context overflow is suspected.

    Returns True if compaction reduced the history, False otherwise.
    """
    from code_muse.agents._compaction import truncate
    from code_muse.agents._history import CompactionCache, hash_message

    history = agent._message_history
    if len(history) <= 2:
        return False

    emit_warning(
        "🚨 Emergency compaction: model returned empty response, "
        "likely context overflow. Aggressively trimming history..."
    )

    # Use 25% of model context as protected tokens (much more aggressive
    # than the normal 50k default) to force a significant reduction.
    try:
        model_ctx = agent._get_model_context_length()
    except Exception:
        model_ctx = 128000
    emergency_protected = max(5000, model_ctx // 4)

    cache = CompactionCache()
    model_name: str | None = None
    with suppress(Exception):
        model_name = agent.get_model_name()

    result = truncate(history, emergency_protected, model_name, cache=cache)

    if len(result) < len(history):
        # Track dropped messages
        result_hashes = {hash_message(m) for m in result}
        for m in history:
            if hash_message(m) not in result_hashes:
                agent._compacted_message_hashes.add(hash_message(m))
        agent._message_history = result
        emit_info(f"✂️  Emergency compaction: {len(history)} → {len(result)} messages")
        return True

    return False


# ---- The main entry point ---------------------------------------------------


async def run(
    agent: Any,
    prompt: str,
    *,
    attachments: Sequence[BinaryContent | None] = None,
    link_attachments: Sequence[ImageUrl | DocumentUrl | None] = None,
    output_type: type[Any | None] = None,
    **kwargs: Any,
) -> Any:
    """Run ``agent`` against ``prompt`` with full tool + cancellation support."""

    prompt = _sanitize_prompt(prompt)
    group_id = str(uuid.uuid4())

    if agent._code_generation_agent is None:
        build_pydantic_agent(agent)
    pydantic_agent = agent._code_generation_agent

    if output_type is not None:
        pydantic_agent = build_pydantic_agent(agent, output_type=output_type)

    prompt = _should_prepend_system_prompt(agent, prompt)
    prompt_payload = _build_prompt_payload(prompt, attachments, link_attachments)

    run_stats: RunStats | None = None

    async def _do_run(prompt_to_use: Any) -> Any:
        """Run the agent once, then honour any plugin ``retry`` requests."""

        # Per-run tool error circuit breaker
        tracker = _ToolErrorTracker(max_errors=get_max_consecutive_tool_errors())
        tracker_token = _tool_error_tracker_ctx.set(tracker)

        # Streaming config gate (issue #295). When streaming is disabled we
        # never install the stream handler at all and always render from the
        # final result. When it's enabled we wrap the handler in a detector
        # and fall back to a one-shot render only if no text actually streamed.
        #
        # Model-level override: models with ``"streaming": false`` in
        # models.json always use non-streaming requests (e.g. kimi-k2.5
        # via crof.ai whose SSE transport is flaky).
        use_streaming = get_enable_streaming() and _model_allows_streaming(
            agent.get_model_name()
        )
        detector: StreamingTextDetector | None = (
            StreamingTextDetector(event_stream_handler) if use_streaming else None
        )
        stream_handler = detector if detector is not None else None
        # When streaming is disabled we must also clear the handler stored on
        # the pydantic agent itself.  Some wrappers bake
        # ``event_stream_handler`` into the agent at build
        # time; passing ``None`` to ``.run()`` isn't enough because pydantic-ai
        # falls back via ``event_stream_handler or self.event_stream_handler``.
        # Nuking ``_event_stream_handler`` forces the property to return
        # ``None``, which makes pydantic-ai use the non-streaming
        # ``model.request()`` path instead of ``request_stream()``.
        _saved_handler: Any = None
        handler_was_modified = False
        if not use_streaming:
            _saved_handler = getattr(pydantic_agent, "_event_stream_handler", None)
            pydantic_agent._event_stream_handler = None
            handler_was_modified = True
        # Plugins can render their own output and ask us to skip
        # the non-streaming fallback render.
        skip_fallback_render = on_should_skip_fallback_render(agent)

        stats = RunStats()
        stats.was_streamed = use_streaming
        run_start = time.perf_counter()
        was_retried = False

        async def _run_agent(
            prompt: Any,
            history: list[Any],
            stream_h: Any | None,
        ) -> Any:
            """Wrap pydantic_agent.run with an optional overall timeout."""
            usage_limits = UsageLimits(request_limit=get_message_limit())
            coro = pydantic_agent.run(
                prompt,
                message_history=history,
                usage_limits=usage_limits,
                event_stream_handler=stream_h,
                **kwargs,
            )
            timeout = get_overall_run_timeout_seconds()
            if timeout > 0:
                return await asyncio.wait_for(coro, timeout=timeout)
            return await coro

        @streaming_retry()
        async def _call() -> Any:
            return await _run_agent(
                prompt_to_use, agent._message_history, stream_handler
            )

        async def _call_with_exception_recovery() -> Any:
            """Run ``_call`` and let plugins request exception retries (capped).

            Also performs emergency compaction when the model returns empty
            responses (likely context overflow) — compacts history aggressively
            and retries once before giving up.
            """
            max_retries = get_max_hook_retries()
            for attempt in range(max_retries + 1):
                try:
                    return await _call()
                except Exception as exc:
                    # Emergency compaction: if all streaming retries failed
                    # due to context overflow, aggressively compact and retry.
                    if _is_context_overflow_error(exc) and attempt == 0:
                        compacted = _emergency_compact(agent)
                        if compacted:
                            continue

                    if attempt >= max_retries:
                        raise
                    hook_results = await on_agent_exception(
                        exc,
                        agent=agent,
                        agent_name=agent.name,
                        model_name=agent.get_model_name(),
                    )
                    retry_req = next(
                        (
                            r
                            for r in hook_results
                            if isinstance(r, dict) and r.get("retry")
                        ),
                        None,
                    )
                    if not retry_req:
                        raise
                    retry_delay = retry_req.get("delay", 0.0)
                    if retry_delay:
                        await asyncio.sleep(retry_delay)
            # Unreachable — loop always returns or raises.
            raise RuntimeError("Exhausted exception recovery retries")

        try:
            result = await _call_with_exception_recovery()

            max_hook_retries = get_max_hook_retries()
            hook_retries_used = 0
            max_loop_iterations = 50  # safety cap

            for _ in range(max_loop_iterations):
                # 1) Check for queued steer injection (stub for now)
                # 2) Check hook retries
                if hook_retries_used >= max_hook_retries:
                    break
                hook_results = await on_agent_run_result(
                    result,
                    agent_name=agent.name,
                    model_name=agent.get_model_name(),
                )
                retry_req = next(
                    (r for r in hook_results if isinstance(r, dict) and r.get("retry")),
                    None,
                )
                if not retry_req:
                    break

                was_retried = True
                hook_retries_used += 1
                retry_prompt = retry_req.get("prompt", "Please continue.")
                retry_delay = retry_req.get("delay", 1.0)
                if hasattr(result, "all_messages"):
                    agent._message_history = list(result.all_messages())
                await asyncio.sleep(retry_delay)

                @streaming_retry()
                async def _retry_call(prompt: str = retry_prompt) -> Any:
                    return await _run_agent(
                        prompt, agent._message_history, stream_handler
                    )

                result = await _retry_call()

        finally:
            _tool_error_tracker_ctx.reset(tracker_token)
            # Restore the handler we cleared (non-streaming models).
            if handler_was_modified:
                pydantic_agent._event_stream_handler = _saved_handler

        # Populate run stats before returning.
        if result is not None:
            if hasattr(result, "all_messages"):
                messages = list(result.all_messages())
                stats.step_count = len(messages)
                for msg in messages:
                    if hasattr(msg, "parts"):
                        for part in msg.parts:
                            if hasattr(part, "tool_name"):
                                stats.tool_calls_made += 1
            usage = None
            if hasattr(result, "usage") and callable(result.usage):
                with suppress(Exception):
                    usage = result.usage
            elif hasattr(result, "usage"):
                usage = result.usage
            if usage is not None:
                if hasattr(usage, "input_tokens"):
                    stats.total_input_tokens = usage.input_tokens or 0
                if hasattr(usage, "output_tokens"):
                    stats.total_output_tokens = usage.output_tokens or 0

        stats.duration_seconds = time.perf_counter() - run_start
        stats.consecutive_errors = tracker.consecutive_errors
        stats.was_retried = was_retried
        nonlocal run_stats
        run_stats = stats

        # Fallback render when streaming didn't surface any text to the user.
        if result is not None and should_render_fallback(
            detector, skip=skip_fallback_render
        ):
            # TODO: PEP 734 async bridge — render_result_without_streaming
            # uses sync time.sleep
            await asyncio.to_thread(render_result_without_streaming, result)

        return result

    async def run_agent_task() -> RunOutcome:
        from code_muse.agents._history import prune_interrupted_tool_calls

        agent._message_history = prune_interrupted_tool_calls(agent._message_history)
        outcome: RunOutcome | None = None
        try:
            run_ctxs = on_agent_run_context(agent, pydantic_agent, group_id)
            async with AsyncExitStack() as stack:
                for cm in run_ctxs:
                    await stack.enter_async_context(cm)
                result = await _do_run(prompt_payload)
                outcome = RunOutcome(True, result=result)

        except* UsageLimitExceeded:
            emit_info(
                "⚠️  The agent has reached its step limit. "
                "Say 'please continue' to resume.",
            )
            outcome = RunOutcome(True, result=None)
        except* Exception as other:
            unexpected = _collect_exceptions(
                other,
                lambda e: (
                    not isinstance(e, (asyncio.CancelledError, UsageLimitExceeded))
                ),
            )
            for exc in unexpected:
                emit_exception_diagnostics(exc, group_id=group_id)
            outcome = RunOutcome(False, error=other)
        if outcome is None:
            return RunOutcome(False)
        return outcome

    # Scrub any stale PauseController state from a previously-cancelled run
    _run_signals.reset_pause_state_at_run_start()

    with suppress(Exception):
        await on_agent_run_start(
            agent_name=agent.name,
            model_name=agent.get_model_name(),
            session_id=group_id,
        )

    agent_task = asyncio.create_task(run_agent_task())

    loop = asyncio.get_running_loop()

    schedule_agent_cancel = _run_signals.make_schedule_cancel(agent_task, loop)

    def keyboard_interrupt_handler(_sig, _frame):
        # Let input() handle its own KeyboardInterrupt if we're mid-prompt.
        if is_awaiting_user_input():
            return
        schedule_agent_cancel()

    def graceful_sigint_handler(_sig, _frame):
        from code_muse.keymap import get_cancel_agent_display_name
        from code_muse.terminal_utils import reset_windows_terminal_full

        reset_windows_terminal_full()
        emit_info(f"Use {get_cancel_agent_display_name()} to cancel the agent task.")

    original_handler = None
    key_listener_stop_event: threading.Event | None = None
    key_listener_thread: threading.Thread | None = None

    run_success = False
    run_error: BaseException | None = None
    run_response_text = ""

    try:
        if cancel_agent_uses_signal():
            original_handler = signal.signal(signal.SIGINT, keyboard_interrupt_handler)
        else:
            original_handler = signal.signal(signal.SIGINT, graceful_sigint_handler)
            key_listener_stop_event = threading.Event()
            key_listener_thread = _key_listeners.spawn_key_listener(
                key_listener_stop_event,
                on_escape=lambda: None,  # Ctrl+X handled by command_runner
                on_cancel_agent=schedule_agent_cancel,
            )

        outcome = await agent_task
        if outcome.success:
            result = outcome.result
            run_success = True
            run_response_text = _extract_response_text(result)
            return result
        else:
            run_error = outcome.error
            if outcome.error is not None:
                raise outcome.error
    except asyncio.CancelledError as exc:
        run_response_text = ""
        run_error = exc
        await on_agent_run_cancel(group_id)
        agent_task.cancel()
        raise
    except KeyboardInterrupt:
        run_response_text = ""
        if not agent_task.done():
            agent_task.cancel()
    except BaseExceptionGroup as e:
        run_error = e
        raise
    except Exception as e:
        run_error = e
        raise
    finally:
        _run_signals.drain_pause_state_on_cancel()

        with suppress(Exception):
            await on_agent_run_end(
                agent_name=agent.name,
                model_name=agent.get_model_name(),
                session_id=group_id,
                success=run_success,
                error=run_error,
                response_text=run_response_text,
                metadata={"stats": dataclasses.asdict(run_stats)}
                if run_stats
                else None,
            )

        if key_listener_stop_event is not None:
            key_listener_stop_event.set()
        if key_listener_thread is not None:
            key_listener_thread.join(timeout=1.0)
        if original_handler is not None:  # SIG_DFL is 0/falsy — explicit check!
            signal.signal(signal.SIGINT, original_handler)
