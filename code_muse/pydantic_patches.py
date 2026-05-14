"""Monkey patches for pydantic-ai.

This module contains all monkey patches needed to customize pydantic-ai behavior.
These patches MUST be applied before any other pydantic-ai imports to work correctly.

Usage:
    from code_muse.pydantic_patches import apply_all_patches
    apply_all_patches()
"""

import contextlib
import importlib.metadata
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_muse_version() -> str:
    """Get the current Muse version."""
    try:
        return importlib.metadata.version("code-muse")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0-dev"


def patch_user_agent() -> None:
    """Patch pydantic-ai's User-Agent to use Muse's version.

    pydantic-ai sets its own User-Agent ('pydantic-ai/x.x.x') via a @cache-decorated
    function. We replace it with a dynamic function that returns:
    - 'KimiCLI/0.63' for Kimi models
    - 'Muse/{version}' for all other models

    This MUST be called before any pydantic-ai models are created.
    """
    try:
        import pydantic_ai.models as pydantic_models

        version = _get_muse_version()

        # Clear cache if already called
        if hasattr(pydantic_models.get_user_agent, "cache_clear"):
            pydantic_models.get_user_agent.cache_clear()

        def _get_dynamic_user_agent() -> str:
            """Return User-Agent based on current model selection."""
            try:
                from code_muse.config import get_global_model_name

                model_name = get_global_model_name()
                if model_name and "kimi" in model_name.lower():
                    return "KimiCLI/0.63"
            except (ImportError, AttributeError, ValueError) as exc:
                logger.debug("get_global_model_name failed: %s", exc)
            return f"Muse/{version}"

        pydantic_models.get_user_agent = _get_dynamic_user_agent
    except (ImportError, AttributeError, TypeError) as exc:
        logger.warning("patch_user_agent failed: %s", exc)


def patch_message_history_cleaning() -> None:
    """Disable overly strict message history cleaning in pydantic-ai."""
    try:
        from pydantic_ai import _agent_graph

        _agent_graph._clean_message_history = lambda messages: messages
    except (ImportError, AttributeError, TypeError) as exc:
        logger.warning("patch_message_history_cleaning failed: %s", exc)


def patch_process_message_history() -> None:
    """Patch _process_message_history to skip strict ModelRequest validation.

    Pydantic AI added a validation that history must end with ModelRequest,
    but this breaks valid conversation flows. We patch it to skip that validation.

    In newer pydantic-ai versions the function was removed, so this becomes a no-op.
    """
    try:
        from pydantic_ai import _agent_graph

        if not hasattr(_agent_graph, "_process_message_history"):
            return

        async def _patched_process_message_history(messages, processors, run_context):
            """Patched version that doesn't enforce ModelRequest at end."""
            from pydantic_ai._agent_graph import (
                cast,
                exceptions,
                is_async_callable,
                is_takes_ctx,
                run_in_executor,
            )

            for processor in processors:
                takes_ctx = is_takes_ctx(processor)

                if is_async_callable(processor):
                    if takes_ctx:
                        messages = await processor(run_context, messages)
                    else:
                        messages = await processor(messages)
                else:
                    if takes_ctx:
                        sync_processor_with_ctx = cast(
                            "_HistoryProcessorSyncWithCtx", processor
                        )
                        messages = await run_in_executor(
                            sync_processor_with_ctx, run_context, messages
                        )
                    else:
                        sync_processor = cast("_HistoryProcessorSync", processor)
                        messages = await run_in_executor(sync_processor, messages)

            if len(messages) == 0:
                raise exceptions.UserError("Processed history cannot be empty.")

            # NOTE: We intentionally skip the "must end with ModelRequest" validation
            # that was added in newer Pydantic AI versions.

            return messages

        _agent_graph._process_message_history = _patched_process_message_history
    except (ImportError, AttributeError, TypeError) as exc:
        logger.warning("patch_process_message_history failed: %s", exc)


def patch_tool_call_json_repair() -> None:
    """JSON repair is now consolidated into patch_tool_call_callbacks.

    Kept as a no-op for backward compatibility with apply_all_patches().
    """
    pass


def patch_tool_call_callbacks() -> None:
    """Patch pydantic-ai tool handling to support callbacks and Claude Code tool names.

    Also handles JSON argument repair (consolidated from patch_tool_call_json_repair
    to avoid double-wrapping ToolManager._call_tool).

    Claude Code OAuth prefixes tool names with ``cp_`` on the wire.  pydantic-ai
    classifies tool calls *before* ``_call_tool`` runs, so unprefixing only in
    ``_call_tool`` is too late: prefixed tools get marked as ``unknown`` and can
    burn through result retries, eventually raising ``UnexpectedModelBehavior``.

    This patch normalizes Claude Code tool names early (during lookup/dispatch)
    and wraps ``_call_tool`` so every tool invocation also triggers the
    ``pre_tool_call`` and ``post_tool_call`` callbacks defined in
    ``code_muse.callbacks``.
    """
    import time

    try:
        from pydantic_ai._tool_manager import ToolManager

        _original_call_tool = ToolManager._call_tool
        _original_get_tool_def = ToolManager.get_tool_def
        _original_handle_call = ToolManager.handle_call

        # Tool name prefix used by Claude Code OAuth - tools are prefixed on
        # outgoing requests, so we need to unprefix them when they come back.
        TOOL_PREFIX = "cp_"

        def _normalize_tool_name(name: Any) -> Any:
            """Strip the ``cp_`` prefix if present."""
            if isinstance(name, str) and name.startswith(TOOL_PREFIX):
                return name[len(TOOL_PREFIX) :]
            return name

        def _normalize_call_tool_name(call: Any) -> tuple[Any, Any]:
            """Normalize the tool_name on a call object in-place."""
            tool_name = getattr(call, "tool_name", None)
            normalized_name = _normalize_tool_name(tool_name)
            if normalized_name != tool_name:
                with contextlib.suppress(AttributeError, TypeError):
                    call.tool_name = normalized_name
            return normalized_name, call

        # -- Early normalization patches -----------------------------------------
        # These run *before* pydantic-ai classifies the tool as function/output/
        # unknown, so prefixed names resolve correctly.

        def _patched_get_tool_def(self, name: str):
            return _original_get_tool_def(self, _normalize_tool_name(name))

        async def _patched_handle_call(
            self,
            call,
            allow_partial: bool = False,
            wrap_validation_errors: bool = True,
            *,
            approved: bool = False,
            metadata: Any = None,
        ):
            _normalize_call_tool_name(call)
            return await _original_handle_call(
                self,
                call,
                allow_partial=allow_partial,
                wrap_validation_errors=wrap_validation_errors,
                approved=approved,
                metadata=metadata,
            )

        # -- _call_tool wrapper with callbacks -----------------------------------

        async def _patched_call_tool(
            self,
            call,
            *,
            allow_partial: bool,
            wrap_validation_errors: bool,
            approved: bool,
            metadata: Any = None,
        ):
            tool_name, call = _normalize_call_tool_name(call)

            # --- JSON repair (moved from patch_tool_call_json_repair) ---
            try:
                import orjson as json_repair

                if isinstance(call.args, str) and call.args:
                    repaired = json_repair.repair_json(call.args)
                    if repaired != call.args:
                        call.args = repaired
            except (ImportError, AttributeError, ValueError, TypeError) as exc:
                logger.debug("json_repair failed: %s", exc)

            # Normalise args to a dict for the callback contract
            tool_args: dict = {}
            if isinstance(call.args, dict):
                tool_args = call.args
            elif isinstance(call.args, str):
                try:
                    import orjson as json

                    tool_args = json.loads(call.args)
                except json.JSONDecodeError, TypeError, ValueError:
                    tool_args = {"raw": call.args}

            # --- pre_tool_call (with blocking support) ---
            # Returns a string tool-result on block so pydantic-ai sees a clean
            # "BLOCKED: ..." message and the agent can react gracefully, without
            # triggering UnexpectedModelBehavior crashes.
            try:
                from code_muse import callbacks
                from code_muse.messaging import emit_warning

                callback_results = await callbacks.on_pre_tool_call(
                    tool_name, tool_args
                )

                for callback_result in callback_results:
                    if (
                        callback_result
                        and isinstance(callback_result, dict)
                        and callback_result.get("blocked")
                    ):
                        raw_reason = (
                            callback_result.get("error_message")
                            or callback_result.get("reason")
                            or ""
                        )
                        if "[BLOCKED]" in raw_reason:
                            clean_reason = raw_reason[
                                raw_reason.index("[BLOCKED]") :
                            ].strip()
                        else:
                            clean_reason = (
                                raw_reason.strip() or "Tool execution blocked by hook"
                            )
                        block_msg = f"🚫 Hook blocked this tool call: {clean_reason}"
                        emit_warning(block_msg)
                        return f"ERROR: {block_msg}\n\nThe hook policy prevented this tool from running. Please inform the user and do not retry this specific command."
            except Exception as exc:
                logger.warning("pre_tool_call callback error: %s", exc)

            start = time.perf_counter()
            error: Exception | None = None
            result = None
            try:
                result = await _original_call_tool(
                    self,
                    call,
                    allow_partial=allow_partial,
                    wrap_validation_errors=wrap_validation_errors,
                    approved=approved,
                    metadata=metadata,
                )
                return result
            except Exception as exc:
                error = exc
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                final_result = result if error is None else {"error": str(error)}
                try:
                    from code_muse import callbacks

                    await callbacks.on_post_tool_call(
                        tool_name, tool_args, final_result, duration_ms
                    )
                except Exception as exc:
                    logger.warning("post_tool_call callback error: %s", exc)

        ToolManager.get_tool_def = _patched_get_tool_def
        ToolManager.handle_call = _patched_handle_call
        ToolManager._call_tool = _patched_call_tool

    except ImportError:
        pass
    except (AttributeError, TypeError) as exc:
        logger.warning("patch_tool_call_callbacks failed: %s", exc)


def patch_prompt_toolkit_emoji_width() -> None:
    """Patch prompt_toolkit's character width calculation for emojis.

    Modern terminals render most emojis as 2 cells wide, but wcwidth often
    returns 1 for many emoji codepoints. This causes cursor misalignment.

    This patch:
    1. Returns 0 for variation selectors (zero-width modifiers)
    2. Returns 2 for emoji codepoints (terminals render them wide)
    3. Falls back to wcwidth for non-emoji characters
    """
    try:
        import wcwidth
        from prompt_toolkit import utils as pt_utils

        _original_get_cwidth = pt_utils.get_cwidth

        def _patched_get_cwidth(char: str) -> int:
            """Get character width with better emoji support."""
            code = ord(char)

            # Variation selectors are zero-width
            if 0xFE00 <= code <= 0xFE0F:  # VS1-VS16
                return 0

            # Emoji codepoints - terminals render these as 2 cells wide
            # even when wcwidth says 1
            if (
                0x1F300 <= code <= 0x1F9FF  # Misc Symbols/Pictographs, Emoticons
                or 0x1F600 <= code <= 0x1F64F  # Emoticons
                or 0x1F680 <= code <= 0x1F6FF  # Transport/Map symbols
                or 0x1FA00 <= code <= 0x1FAFF  # Symbols/Pictographs Extended-A
                or 0x2600 <= code <= 0x26FF  # Misc Symbols (☀️, ⚡, etc)
                or 0x2700 <= code <= 0x27BF  # Dingbats (✂️, ✈️, etc)
                or 0x1F1E0 <= code <= 0x1F1FF  # Regional indicators (flags)
            ):
                return 2

            # Use wcwidth for non-emoji
            w = wcwidth.wcwidth(char)
            if w >= 0:
                return w

            return _original_get_cwidth(char)

        pt_utils.get_cwidth = _patched_get_cwidth

    except ImportError:
        pass  # wcwidth or prompt_toolkit not available
    except (AttributeError, TypeError) as exc:
        logger.warning("patch_prompt_toolkit_emoji_width failed: %s", exc)


def apply_all_patches() -> None:
    """Apply all pydantic-ai monkey patches.

    Call this at the very top of main.py, before any other imports.
    """
    patch_user_agent()
    patch_message_history_cleaning()
    patch_process_message_history()
    patch_tool_call_json_repair()
    patch_tool_call_callbacks()
    patch_prompt_toolkit_emoji_width()
