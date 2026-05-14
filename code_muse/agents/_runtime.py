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
import contextvars
import dataclasses
import signal
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpcore
import httpx
from pydantic_ai import (
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UsageLimits,
)

try:  # pragma: no cover - pydantic-ai version dependent
    from pydantic_ai.exceptions import ModelHTTPError
except ImportError:
    ModelHTTPError = None  # type: ignore[misc,assignment]

try:  # pragma: no cover - optional dependency
    from openai import APIError as OpenAIAPIError
except ImportError:
    OpenAIAPIError = None  # type: ignore[assignment]

# Python 3.11+ builtin; graceful fallback for 3.10
try:
    from builtins import BaseExceptionGroup  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - 3.10 only
    BaseExceptionGroup = Exception  # type: ignore[misc,assignment]

from code_muse.agents import _key_listeners
from code_muse.agents._builder import build_pydantic_agent
from code_muse.agents._diagnostics import emit_exception_diagnostics
from code_muse.agents._non_streaming_render import (
    StreamingTextDetector,
    render_result_without_streaming,
    should_render_fallback,
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
    register_callback,
)
from code_muse.config import (
    get_enable_streaming,
    get_max_agent_steps,
    get_max_consecutive_tool_errors,
    get_max_hook_retries,
    get_max_tool_calls,
    get_message_limit,
    get_overall_run_timeout_seconds,
    get_total_tokens_limit,
)
from code_muse.keymap import cancel_agent_uses_signal
from code_muse.messaging import emit_error, emit_info, emit_warning
from code_muse.model_factory import ModelFactory
from code_muse.tools.agent_tools import _active_subagent_tasks_var
from code_muse.tools.command_runner import is_awaiting_user_input

# ---- Streaming retry helpers ------------------------------------------------

# Every entry here is either an explicit provider "please retry" signal or an
# SSE framing / transport artifact that reliably succeeds on the next attempt.
# Keep this list substring-based and lower-case.
_RETRYABLE_SNIPPETS = (
    "streamed response ended without content",
    "malformed streamed sse event",
    "extra json data in sse payload",
    "too many requests",
    "rate limit",
    "rate limited",
    "overloaded",
    "service unavailable",
    "server had an error processing your request",
    "retry your request",
    "internal server error",
)

_RETRYABLE_EXCEPTIONS: tuple = (
    httpx.RemoteProtocolError,
    httpx.ReadTimeout,
    httpcore.RemoteProtocolError,
)


def _matches_retryable_snippet(msg: str) -> bool:
    """Return True if ``msg`` matches any known transient pattern.

    Also accepts the generic ``stream ... ended`` wording variants so we don't
    have to chase every phrasing tweak providers sneak in over time.
    """
    msg = msg.lower()
    if any(s in msg for s in _RETRYABLE_SNIPPETS):
        return True
    return "stream" in msg and "ended" in msg


def should_retry_streaming(exc: Exception) -> bool:
    """Decide whether ``exc`` is a transient streaming hiccup worth retrying."""
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True

    msg = str(exc)
    if isinstance(exc, UnexpectedModelBehavior):
        return _matches_retryable_snippet(msg)

    if OpenAIAPIError is not None and isinstance(exc, OpenAIAPIError):
        if _matches_retryable_snippet(msg):
            return True
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            body_msg = str(body.get("message", ""))
            body_type = str(body.get("type", "")).lower()
            if _matches_retryable_snippet(body_msg):
                return True
            if "rate" in body_type and "limit" in body_type:
                return True
            if body_type in {"server_error", "internal_server_error", "api_error"}:
                return _matches_retryable_snippet(body_msg)

    # Retry on pydantic-ai ModelHTTPError rate limits (e.g. 429 from providers)
    if ModelHTTPError is not None and isinstance(exc, ModelHTTPError):
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True
        # Retry on 5xx server errors as well
        if isinstance(status_code, int) and status_code >= 500:
            return True
        if _matches_retryable_snippet(msg):
            return True

    return False


def streaming_retry(
    max_attempts: int = 3,
    delays: Sequence[float] = (1, 2, 4),
) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
    """Wrap a no-arg async callable with streaming-retry semantics."""

    def decorator(factory: Callable[[], Any]) -> Callable[[], Any]:
        async def runner() -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return await factory()
                except Exception as exc:
                    if not should_retry_streaming(exc):
                        raise
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        delay = delays[attempt] if attempt < len(delays) else delays[-1]
                        emit_warning(
                            f"⚡ Streaming interrupted, auto-retrying in {delay}s... "
                            f"(attempt {attempt + 1}/{max_attempts})"
                        )
                        await asyncio.sleep(delay)
                    else:
                        emit_error(f"❌ Streaming failed after {max_attempts} attempts")
            assert last_exc is not None  # loop always sets this before exiting
            raise last_exc

        return runner

    return decorator


# ---- Tool error tracking (circuit breaker) --------------------------------


class _ToolErrorTracker:
    """Track consecutive tool errors as a per-agent-run circuit breaker."""

    def __init__(self, max_errors: int = 3):
        self.max_errors = max_errors
        self.consecutive_errors = 0

    def record_error(self) -> bool:
        """Increment error count. Returns True if max exceeded."""
        self.consecutive_errors += 1
        return self.consecutive_errors >= self.max_errors

    def record_success(self) -> None:
        """Reset error count on a successful tool call."""
        self.consecutive_errors = 0


_tool_error_tracker_ctx: contextvars.ContextVar[_ToolErrorTracker | None] = (
    contextvars.ContextVar("_tool_error_tracker_ctx", default=None)
)


async def _track_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> dict | None:
    """Block further tool calls once the consecutive-error cap is hit."""
    tracker = _tool_error_tracker_ctx.get()
    if tracker is None:
        return None
    if tracker.consecutive_errors >= tracker.max_errors:
        return {
            "blocked": True,
            "reason": (
                f"Too many consecutive tool errors ({tracker.consecutive_errors})"
                " — aborting run."
            ),
        }
    return None


async def _track_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Count consecutive tool errors via a contextvar (per-run state)."""
    tracker = _tool_error_tracker_ctx.get()
    if tracker is None:
        return None
    if isinstance(result, dict) and "error" in result:
        tracker.record_error()
    else:
        tracker.record_success()
    return None


# Register callbacks at module load time.
register_callback("pre_tool_call", _track_pre_tool_call)
register_callback("post_tool_call", _track_post_tool_call)


# ---- Small utilities --------------------------------------------------------


def _model_allows_streaming(model_name: str | None) -> bool:
    """Check the model config for an explicit ``"streaming": false`` override.

    Some providers (e.g. crof.ai for kimi models) have flaky SSE transports.
    Setting ``"streaming": false`` in ``models.json`` disables streaming for
    that model, falling back to a single-shot request like gac does.
    """
    if not model_name:
        return True
    try:
        cfg = ModelFactory.load_config().get(model_name, {})
        return cfg.get("streaming", True) is not False
    except Exception:
        return True


def _sanitize_prompt(prompt: str) -> str:
    """Strip lone UTF-16 surrogates (common on Windows copy-paste)."""
    if not prompt:
        return prompt
    try:
        return prompt.encode("utf-8", errors="surrogatepass").decode(
            "utf-8", errors="replace"
        )
    except UnicodeEncodeError, UnicodeDecodeError:
        return "".join(
            ch if ord(ch) < 0xD800 or ord(ch) > 0xDFFF else "\ufffd" for ch in prompt
        )


def _build_prompt_payload(
    prompt: str,
    attachments: Sequence[BinaryContent | None],
    link_attachments: Sequence[ImageUrl | DocumentUrl | None],
) -> str | list[Any]:
    """Merge prompt + binary/link attachments into the pydantic-ai payload shape."""
    parts: list[Any] = []
    if attachments:
        parts.extend(attachments)
    if link_attachments:
        parts.extend(link_attachments)

    if not parts:
        return prompt

    payload: list[Any] = []
    if prompt:
        payload.append(prompt)
    payload.extend(parts)
    return payload


def _extract_response_text(result: Any) -> str:
    """Best-effort extraction of human-readable text from a pydantic-ai result."""
    if result is None:
        return ""
    if hasattr(result, "data"):
        return str(result.data) if result.data else ""
    if hasattr(result, "output"):
        return str(result.output) if result.output else ""
    return str(result)


def _should_prepend_system_prompt(agent: Any, prompt: str) -> str:
    """Prepend system prompt to user prompt on the first turn (claude-code etc)."""
    from code_muse.agents._builder import assemble_full_system_prompt
    from code_muse.model_utils import prepare_prompt_for_model

    if agent._message_history:
        return prompt

    system_prompt = assemble_full_system_prompt(agent, agent.get_model_name())

    prepared = prepare_prompt_for_model(
        model_name=agent.get_model_name(),
        system_prompt=system_prompt,
        user_prompt=prompt,
        prepend_system_to_user=True,
    )
    return prepared.user_prompt


def _collect_exceptions(
    group: BaseException, predicate: Callable[[BaseException], bool]
) -> list[BaseException]:
    """Flatten an ExceptionGroup tree, returning leaves matching ``predicate``."""
    out: list[BaseException] = []
    stack: list[BaseException] = [group]
    while stack:
        exc = stack.pop()
        if isinstance(exc, BaseExceptionGroup):
            stack.extend(exc.exceptions)
        elif predicate(exc):
            out.append(exc)
    return out


@dataclass
class RunOutcome:
    """Structured result of a single agent run attempt."""

    success: bool
    result: Any = None
    error: BaseException | None = None


@dataclass
class RunStats:
    """Per-run metrics passed to on_agent_run_end metadata."""

    step_count: int = 0
    tool_calls_made: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    duration_seconds: float = 0.0
    consecutive_errors: int = 0
    was_retried: bool = False
    was_streamed: bool = False
    start_time: datetime = field(default_factory=datetime.now)


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
        usage_limits = UsageLimits(
            request_limit=get_message_limit(),
            tool_calls_limit=get_max_tool_calls() or None,
            total_tokens_limit=get_total_tokens_limit() or None,
        )

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
            """Run ``_call`` and let plugins request exception retries (capped)."""
            max_retries = get_max_hook_retries()
            for attempt in range(max_retries + 1):
                try:
                    return await _call()
                except Exception as exc:
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

            for _ in range(get_max_hook_retries()):
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

            # ---- Max agent steps guard ----
            max_steps = get_max_agent_steps()
            if max_steps > 0 and hasattr(result, "all_messages"):
                step_count = len(result.all_messages())
                if step_count >= max_steps:
                    from code_muse.io import emit_warning

                    emit_warning(
                        f"⚠️  Agent run reached {step_count} steps (max {max_steps}). "
                        f"Truncating result. Consider increasing 'max_agent_steps' via /set.",
                        message_group="token_context_status",
                    )

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
                try:
                    usage = result.usage
                except Exception:
                    pass
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
            # TODO: PEP 734 async bridge — render_result_without_streaming uses sync time.sleep
            await asyncio.to_thread(render_result_without_streaming, result)

        return result

    async def run_agent_task() -> RunOutcome:
        outcome: RunOutcome | None = None
        try:
            run_ctxs = on_agent_run_context(agent, pydantic_agent, group_id)
            async with AsyncExitStack() as stack:
                for cm in run_ctxs:
                    await stack.enter_async_context(cm)
                result = await _do_run(prompt_payload)
                outcome = RunOutcome(True, result=result)
        except* UsageLimitExceeded as ule:
            emit_info(f"Usage limit exceeded: {ule}", group_id=group_id)
            emit_info(
                "The agent has reached its usage limit. You can ask it to continue "
                "by saying 'please continue' or similar.",
                group_id=group_id,
            )
            outcome = RunOutcome(False, error=ule)
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

    try:
        await on_agent_run_start(
            agent_name=agent.name,
            model_name=agent.get_model_name(),
            session_id=group_id,
        )
    except Exception:
        # Hook failures never block the agent.
        pass

    agent_task = asyncio.create_task(run_agent_task())

    loop = asyncio.get_running_loop()

    def schedule_agent_cancel() -> None:
        from code_muse.tools.command_runner import _RUNNING_PROCESSES

        if _RUNNING_PROCESSES:
            emit_warning(
                "Refusing to cancel Agent while a shell command is running — "
                "press Ctrl+X to cancel the shell command."
            )
            return
        if agent_task.done():
            return
        try:
            active_tasks = _active_subagent_tasks_var.get()
        except LookupError:
            active_tasks = set()
        if active_tasks:
            emit_warning(f"Cancelling {len(active_tasks)} active subagent task(s)...")
            for task in list(active_tasks):
                if not task.done():
                    loop.call_soon_threadsafe(task.cancel)
        loop.call_soon_threadsafe(agent_task.cancel)

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
