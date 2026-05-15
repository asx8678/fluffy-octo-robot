"""Run-utility helpers: data classes, prompt building, and response extraction.

Small pure functions and data structures used by the run orchestrator
in ``_runtime.py``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic_ai import BinaryContent, DocumentUrl, ImageUrl

from code_muse.model_factory import ModelFactory

# ---- Data classes -----------------------------------------------------------


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


# ---- Small utilities --------------------------------------------------------


def _model_allows_streaming(model_name: str | None) -> bool:
    """Check the model config for an explicit ``"streaming"`` override.

    Some providers (e.g. crof.ai / nahcrof for kimi models) have flaky SSE
    transports. These models default to non-streaming (single-shot request)
    unless the user explicitly sets ``"streaming": true``.
    """
    if not model_name:
        return True
    try:
        cfg = ModelFactory.load_config().get(model_name, {})

        # Explicit user override always wins (both true and false)
        if "streaming" in cfg:
            return cfg["streaming"] is not False

        # Auto-disable streaming for known flaky SSE providers.
        # Covers:
        #   - provider: "crof" (or "crof.ai")
        #   - any model name containing "crof" (nahcrof-*, crof-*, etc.)
        provider = str(cfg.get("provider") or "").lower()
        name_lower = model_name.lower()

        return not (provider in {"crof", "crof.ai"} or "crof" in name_lower)
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
