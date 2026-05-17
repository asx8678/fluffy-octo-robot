"""Message history compaction (truncation + summarization).

Replaces the old ``message_history_processor`` / ``message_history_accumulator``
pair from ``BaseAgent``. All logic here is free-function; the one stateful
entry point is ``make_history_processor(agent)`` which returns a closure that
pydantic-ai wires in as its ``history_processors`` callback.

The delayed-compaction globals and the retry-after-tool-calls plumbing from
the original god-class are **gone**. If compaction can't run safely right now
(pending tool calls + summarization strategy), we just skip it this cycle and
let the next ``history_processor`` invocation handle it.
"""

import dataclasses
import logging as _logging
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolReturnPart,
)

from code_muse.agents._history import (
    CompactionCache,
    _classify_tool_part,
    estimate_tokens_for_message,
    filter_huge_messages,
    has_pending_tool_calls,
    hash_message,
    prune_interrupted_tool_calls,
)
from code_muse.callbacks import (
    on_message_history_processor_end,
    on_message_history_processor_start,
)
from code_muse.config import (
    get_compaction_strategy,
    get_compaction_threshold,
    get_max_messages_hard_cap,
    get_protected_token_count,
    get_recent_tool_results_to_keep,
)
from code_muse.messaging import emit_error, emit_info, emit_warning
from code_muse.messaging.spinner import SpinnerBase, update_spinner_context

_SUMMARIZATION_INSTRUCTIONS = (
    "The input will be a log of Agentic AI steps that have been taken"
    " as well as user queries, etc. Summarize the contents of these steps."
    " The high level details should remain but the bulk of the content from tool-call"
    " responses should be compacted and summarized. For example if you see a tool-call"
    " reading a file, and the file contents are large, then in your"
    " summary you might just"
    " write: * used read_file on space_invaders.cpp - contents removed."
    "\n Make sure your result is a bulleted list of all steps and interactions."
    "\n\nNOTE: This summary represents older conversation history. "
    "Recent messages are preserved separately."
)

# Default for tool result retention; actual value comes from config.
_DEFAULT_TOOL_RESULTS_TO_KEEP = 7

# Token-proportion threshold above which compact_with_tool_truncation
# applies tool-result truncation even for short histories.
_TOOL_TRUNCATION_TOKEN_THRESHOLD = 0.50


def _find_safe_split_index(messages: list[ModelMessage], initial_split_idx: int) -> int:
    """Adjust split index so we never sever a tool_call from its tool_return."""
    if initial_split_idx <= 1:
        return initial_split_idx

    protected_tool_return_ids: set[str] = set()
    for msg in messages[initial_split_idx:]:
        for part in getattr(msg, "parts", []) or []:
            if _classify_tool_part(part) == "return":
                tcid = getattr(part, "tool_call_id", None)
                if tcid:
                    protected_tool_return_ids.add(tcid)

    if not protected_tool_return_ids:
        return initial_split_idx

    adjusted_idx = initial_split_idx
    # Walk backwards; never cross the system message at index 0.
    for i in range(initial_split_idx - 1, 0, -1):
        msg = messages[i]
        has_match = False
        for part in getattr(msg, "parts", []) or []:
            if _classify_tool_part(part) == "call":
                tcid = getattr(part, "tool_call_id", None)
                if tcid and tcid in protected_tool_return_ids:
                    has_match = True
                    break
        if has_match:
            adjusted_idx = i
        else:
            # Tool calls and their returns are adjacent — first miss ends it.
            break

    return adjusted_idx


def split_for_protected_summarization(
    messages: list[ModelMessage],
    protected_tokens: int,
    model_name: str | None = None,
    cache: CompactionCache | None = None,
) -> tuple[list[ModelMessage], list[ModelMessage]]:
    """Split messages into (to_summarize, protected) groups.

    The system message (index 0) is always protected. Starting from the most
    recent message, we accumulate messages into the protected zone until we
    hit ``protected_tokens``. Everything in-between becomes summarization
    fodder. The split point is adjusted to keep tool_call/tool_return pairs
    together.
    """
    if len(messages) <= 1:
        return [], messages

    _tok = cache.estimate_tokens if cache else estimate_tokens_for_message

    system_message = messages[0]
    system_tokens = _tok(system_message, model_name)

    protected_messages: list[ModelMessage] = []
    running_tokens = system_tokens

    for i in range(len(messages) - 1, 0, -1):
        msg_tokens = _tok(messages[i], model_name)
        if running_tokens + msg_tokens > protected_tokens:
            break
        protected_messages.append(messages[i])
        running_tokens += msg_tokens

    protected_messages.reverse()
    protected_messages.insert(0, system_message)

    protected_start_idx = max(1, len(messages) - (len(protected_messages) - 1))
    protected_start_idx = _find_safe_split_index(messages, protected_start_idx)
    messages_to_summarize = messages[1:protected_start_idx]

    emit_info(
        f"🔒 Protecting {len(protected_messages)} recent messages "
        f"({running_tokens} tokens, limit: {protected_tokens})"
    )
    emit_info(f"📝 Summarizing {len(messages_to_summarize)} older messages")

    return messages_to_summarize, protected_messages


def truncate(
    messages: list[ModelMessage],
    protected_tokens: int,
    model_name: str | None = None,
    cache: CompactionCache | None = None,
) -> list[ModelMessage]:
    """Drop middle messages, keeping system prompt + recent tail within budget.

    Budget is the TOTAL token count of the returned list (system message
    included). Tool_call/tool_return pairs are preserved by adjusting the
    split point so we never sever a tool_call from its tool_return.
    """
    if not messages:
        return messages

    _tok = cache.estimate_tokens if cache else estimate_tokens_for_message

    emit_info("Truncating message history to manage token usage")

    system_message = messages[0]
    system_tokens = _tok(system_message, model_name)

    # If even the system message is over budget, return just it (caller's
    # responsibility — we can't do better here).
    if system_tokens >= protected_tokens or len(messages) == 1:
        return [system_message]

    # Optional 2nd message: extended-thinking context.
    extra_protected: list[ModelMessage] = []
    extra_tokens = 0
    skip_indices = {0}
    if len(messages) > 1:
        second_msg = messages[1]
        if any(isinstance(part, ThinkingPart) for part in second_msg.parts):
            second_tokens = _tok(second_msg, model_name)
            if system_tokens + second_tokens < protected_tokens:
                extra_protected.append(second_msg)
                extra_tokens = second_tokens
                skip_indices.add(1)

    # Walk backwards from the tail, accumulating recent messages until we
    # hit the remaining budget.
    budget_remaining = protected_tokens - system_tokens - extra_tokens
    recent: list[ModelMessage] = []
    recent_tokens = 0
    for i in range(len(messages) - 1, -1, -1):
        if i in skip_indices:
            continue
        msg_tokens = _tok(messages[i], model_name)
        if recent_tokens + msg_tokens > budget_remaining:
            break
        recent_tokens += msg_tokens
        recent.append(messages[i])

    # We collected in reverse order; reverse to chronological.
    recent.reverse()

    # Compute the split index from the original list and adjust to keep
    # tool_call/tool_return pairs together (never sever a pair).
    if recent:
        # Find the index of the earliest message in `recent` within `messages`.
        # We do this by identity since messages preserve identity through
        # the algorithm.
        first_recent_id = id(recent[0])
        split_idx = next(
            (i for i, m in enumerate(messages) if id(m) == first_recent_id),
            len(messages) - len(recent),
        )
        adjusted_idx = _find_safe_split_index(messages, split_idx)
        # If pair-safety pushed the split earlier, expand `recent` accordingly,
        # but ONLY if it still fits within the budget. If not, accept the
        # original (potentially-orphaned) split and rely on
        # prune_interrupted_tool_calls to clean up downstream.
        if adjusted_idx < split_idx:
            extra = messages[adjusted_idx:split_idx]
            extra_tok = sum(_tok(m, model_name) for m in extra)
            if recent_tokens + extra_tok <= budget_remaining:
                recent = list(extra) + recent
                recent_tokens += extra_tok

    result: list[ModelMessage] = [system_message] + extra_protected + recent

    # Safety: never return only the system prompt with no user messages.
    # When this happens, the budget was too small to fit even one message;
    # we still need *something* — pick the smallest recent message rather
    # than the last (which may be massive).
    if len(result) == 1 and len(messages) > 1:
        candidates = [messages[i] for i in range(1, len(messages))]
        smallest = min(candidates, key=lambda m: _tok(m, model_name))
        result.append(smallest)

    return result


def _run_summarization_core(
    messages: list[ModelMessage],
    protected_tokens: int,
    with_protection: bool,
    model_name: str | None,
    cache: CompactionCache | None = None,
) -> tuple[list[ModelMessage], list[ModelMessage]]:
    """Inner summarization that propagates exceptions to the caller.

    Returns ``(compacted_messages, summarized_source_messages)`` or raises
    on summarization-agent failure. Use :func:`summarize` if you want the
    swallow-and-return-original behavior, or call this directly when you want
    to handle failure yourself (e.g. fall back to truncation).
    """
    if not messages:
        return [], []

    if with_protection:
        messages_to_summarize, protected_messages = split_for_protected_summarization(
            messages, protected_tokens, model_name, cache=cache
        )
    else:
        messages_to_summarize = messages[1:]
        protected_messages = messages[:1]

    system_message = messages[0]

    if not messages_to_summarize:
        return messages, []

    from code_muse.summarization_agent import run_summarization_sync

    new_messages = run_summarization_sync(
        _SUMMARIZATION_INSTRUCTIONS, message_history=messages_to_summarize
    )

    if not isinstance(new_messages, list):
        emit_warning(
            "Summarization agent returned non-list output;"
            " wrapping into message request"
        )
        new_messages = [ModelRequest([TextPart(str(new_messages))])]

    compacted: list[ModelMessage] = [system_message] + list(new_messages)
    compacted.extend(msg for msg in protected_messages if msg is not system_message)
    return compacted, messages_to_summarize


def _log_summarization_failure(error: Exception, fallback_note: str = "") -> None:
    """Single source of truth for summarization-failure user messaging."""
    error_type = type(error).__name__
    emit_error(f"Compaction failed: [{error_type}] {error}")
    from code_muse.summarization_agent import SummarizationError

    if isinstance(error, SummarizationError) and error.original_error:
        underlying = type(error.original_error).__name__
        suffix = f" {fallback_note}" if fallback_note else ""
        emit_warning(f"💡 Underlying error was {underlying}.{suffix}")
    elif fallback_note:
        emit_warning(fallback_note)


def summarize(
    messages: list[ModelMessage],
    protected_tokens: int,
    with_protection: bool = True,
    model_name: str | None = None,
    cache: CompactionCache | None = None,
) -> tuple[list[ModelMessage], list[ModelMessage]]:
    """Summarize older messages, preserving the protected recent tail.

    Returns ``(compacted_messages, summarized_source_messages)``. On failure
    we log a warning and return ``(messages, [])`` so the run continues.
    """
    try:
        result_messages, summarized_messages = _run_summarization_core(
            messages, protected_tokens, with_protection, model_name, cache=cache
        )

        # Validate summarization output
        try:
            from code_muse.summarization_agent import _validate_summary_fidelity

            validation = _validate_summary_fidelity(result_messages)
            if validation.retry_needed:
                _logging.getLogger(__name__).warning(
                    "Summarization validation failed: missing %d protected facts",
                    len(validation.preserved_facts_missing),
                )
                # Fall back to truncation if summarization dropped critical facts
                if validation.retry_needed:
                    result_messages, summarized_messages = messages, []
                    emit_warning(
                        "Summarization dropped protected facts — "
                        "falling back to truncation."
                    )
        except ImportError:
            pass

        return result_messages, summarized_messages
    except Exception as e:
        _log_summarization_failure(
            e,
            "Consider using '/set compaction_strategy=truncation' as a fallback.",
        )
        return messages, []


def _truncate_with_dropped(
    filtered: list[ModelMessage],
    protected_tokens: int,
    model_name: str | None,
    cache: CompactionCache | None = None,
) -> tuple[list[ModelMessage], list[ModelMessage]]:
    """Truncate ``filtered`` and compute which messages got dropped.

    Shared by the truncation strategy and the summarization-failure fallback
    so both paths agree on what counts as 'dropped' for hash bookkeeping.
    """
    result_messages = truncate(filtered, protected_tokens, model_name, cache=cache)
    _hash = cache.hash_message if cache else hash_message
    result_hashes = {_hash(m) for m in result_messages}
    dropped = [m for m in filtered if _hash(m) not in result_hashes]
    return result_messages, dropped


def compact(
    agent: Any,
    messages: list[ModelMessage],
    model_max: int,
    context_overhead: int,
) -> tuple[list[ModelMessage], list[ModelMessage]]:
    """Unified compaction entrypoint. Replaces ``message_history_processor``.

    Args:
        agent: The owning agent. Used to resolve the active model name so
            token estimates can apply per-model calibration multipliers.
        messages: Current message history (already accumulated by the caller).
        model_max: Effective model context window in tokens.
        context_overhead: Estimated overhead for system prompt + tool schemas.

    Returns:
        ``(new_messages, dropped_messages_for_hash_tracking)``.
    """
    # Resolve model name once so all downstream estimators apply the same
    # per-model calibration multiplier.
    model_name: str | None = None
    if agent is not None:
        try:
            model_name = agent.get_model_name()
        except Exception:
            model_name = None

    # PERF-04: create a per-compaction cache to avoid repeated hash/token
    # computations on the same message objects within this invocation.
    cache = CompactionCache()

    message_tokens = cache.sum_tokens(messages, model_name)
    total_tokens = message_tokens + context_overhead
    proportion_used = total_tokens / model_max if model_max else 0.0

    context_summary = SpinnerBase.format_context_info(
        total_tokens, model_max, proportion_used
    )
    update_spinner_context(context_summary)

    # Replace long pasted documents with reference stubs (before compaction)
    with suppress(Exception):
        from code_muse.plugins.task_context.document_store import (
            replace_long_documents_in_history,
        )

        messages = replace_long_documents_in_history(messages)

    # Inject protected facts into system message if available
    with suppress(Exception):
        _inject_protected_facts_into_system(messages)

    # Hard cap on message count: prevent unbounded history even when
    # token proportion is below threshold. Short messages can accumulate
    # past the cap without triggering token-based compaction.
    # The cap scales dynamically with model_max so large-window models
    # aren't forced to compact prematurely.
    hard_cap = get_max_messages_hard_cap(model_max=model_max)
    if len(messages) > hard_cap:
        strategy = get_compaction_strategy()
        protected_tokens = get_protected_token_count()
        filtered = filter_huge_messages(messages, model_name, cache=cache)

        if strategy == "truncation":
            result_messages, summarized_messages = _truncate_with_dropped(
                filtered, protected_tokens, model_name, cache=cache
            )
        else:
            result_messages, summarized_messages = summarize(
                filtered, protected_tokens, True, model_name, cache=cache
            )
            if not summarized_messages:
                result_messages, summarized_messages = _truncate_with_dropped(
                    filtered, protected_tokens, model_name, cache=cache
                )

        new_proportion = 0.0
        if model_max:
            new_total = cache.sum_tokens(result_messages, model_name) + context_overhead
            new_proportion = new_total / model_max
        update_spinner_context(
            f"Count cap ({hard_cap}): "
            + SpinnerBase.format_context_info(
                cache.sum_tokens(result_messages, model_name) + context_overhead,
                model_max,
                new_proportion,
            )
        )
        return result_messages, summarized_messages

    threshold = get_compaction_threshold()
    # Dynamic threshold: lower for small-context models where the margin
    # between "safe" and "overflow" is much tighter.
    if model_max <= 32_000:
        threshold = min(threshold, 0.70)
    elif model_max <= 64_000:
        threshold = min(threshold, 0.75)
    if proportion_used <= threshold:
        return messages, []

    strategy = get_compaction_strategy()

    protected_tokens = get_protected_token_count()
    filtered = filter_huge_messages(messages, model_name, cache=cache)

    # The authoritative prune_interrupted_tool_calls() runs once at the
    # end of the history processor, so any orphaned tool_call / tool_return
    # pairs (from cancelled runs, Ctrl-C interrupts, etc.) are stripped out
    # there. The check below only trips on a genuine mid-execution state,
    # which shouldn't happen when the history_processor is invoked — but we
    # keep it as a defensive safety net.
    #
    # Previously this check ran on the raw `messages` list, which meant a
    # single orphaned tool_call (e.g., from one cancelled command weeks ago)
    # would defer summarization forever, letting history grow unbounded.
    if strategy == "summarization" and has_pending_tool_calls(filtered):
        emit_warning(
            "⚠️  Summarization deferred: pending tool call(s) detected "
            "after pruning orphans. Will retry on next invocation.",
            message_group="token_context_status",
        )
        return messages, []

    if strategy == "truncation":
        result_messages, summarized_messages = _truncate_with_dropped(
            filtered, protected_tokens, model_name, cache=cache
        )
    else:
        # Route through the public summarize() so error handling, logging,
        # and any future instrumentation stay in one place (DRY).
        result_messages, summarized_messages = summarize(
            filtered, protected_tokens, True, model_name, cache=cache
        )
        # If summarization failed gracefully (returned original messages
        # with nothing dropped), fall back to truncation for this cycle.
        # The user's strategy preference is preserved for the next cycle.
        if not summarized_messages:
            pre_truncate_count = len(filtered)
            result_messages, summarized_messages = _truncate_with_dropped(
                filtered, protected_tokens, model_name, cache=cache
            )
            dropped_count = pre_truncate_count - len(result_messages)
            emit_warning(
                f"↪️  Summarization produced no compaction; "
                f"falling back to truncation: "
                f"{pre_truncate_count} → {len(result_messages)} messages "
                f"({dropped_count} dropped)",
                message_group="token_context_status",
            )

    final_token_count = cache.sum_tokens(result_messages, model_name)
    final_summary = SpinnerBase.format_context_info(
        final_token_count,
        model_max,
        final_token_count / model_max if model_max else 0.0,
    )
    update_spinner_context(final_summary)

    return result_messages, summarized_messages


def _strip_empty_thinking_parts(
    messages: list[ModelMessage],
) -> tuple[list[ModelMessage], int]:
    """Remove empty ThinkingParts; drop messages rendered empty by removal."""
    cleaned: list[ModelMessage] = []
    filtered_count = 0
    for msg in messages:
        parts = list(msg.parts)
        if (
            len(parts) == 1
            and isinstance(parts[0], ThinkingPart)
            and not parts[0].content
        ):
            filtered_count += 1
            continue
        if any(isinstance(p, ThinkingPart) and not p.content for p in parts):
            msg = dataclasses.replace(
                msg,
                parts=[
                    p
                    for p in parts
                    if not (isinstance(p, ThinkingPart) and not p.content)
                ],
            )
            if not msg.parts:
                filtered_count += 1
                continue
        cleaned.append(msg)
    return cleaned, filtered_count


def make_history_processor(agent: Any) -> Callable[..., list[ModelMessage]]:
    """Build the pydantic-ai ``history_processors`` callback for ``agent``.

    The returned closure:
      1. Fires ``on_message_history_processor_start``.
      2. Merges any incoming messages not already in ``agent._message_history``
         (preserving the last-message regardless of compacted-hash collisions).
      3. Runs ``compact_with_tool_truncation(...)`` if we're over threshold —
         truncates older tool-result content first, then falls through to compact().
      4. Records dropped-message hashes in ``agent._compacted_message_hashes``.
      5. Strips empty ThinkingParts.
      6. Trims trailing ModelResponse messages so history ends with a ModelRequest.
      7. Fires ``on_message_history_processor_end``.

    Agent contract (Phase 3 will enforce on ``BaseAgent``):
      - ``agent._message_history: list``
      - ``agent._compacted_message_hashes: set``
      - ``agent._get_model_context_length() -> int``
      - ``agent._estimate_context_overhead() -> int``
      - ``agent.name`` / ``agent.session_id`` (optional)
    """

    def history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
        # pydantic-ai picks 1-arg vs 2-arg processor by inspecting the first
        # parameter's type annotation (must be ``RunContext`` for 2-arg form).
        # We don't need ctx, so we use the 1-arg form.
        history: list[ModelMessage] = agent._message_history
        compacted_hashes: set[int] = agent._compacted_message_hashes

        on_message_history_processor_start(
            agent_name=getattr(agent, "name", None),
            session_id=getattr(agent, "session_id", None),
            message_history=history,
            incoming_messages=list(messages),
        )

        existing_hashes = {hash_message(m) for m in history}
        messages_added = 0
        last_idx = len(messages) - 1
        for i, msg in enumerate(messages):
            h = hash_message(msg)
            if h in existing_hashes:
                continue
            # Always keep the last (newest) message, even if its hash collides
            # with a previously compacted one — short prompts like "yes"/"1"
            # can collide and get silently dropped otherwise.
            if i == last_idx or h not in compacted_hashes:
                history.append(msg)
                messages_added += 1

        new_history, dropped = compact_with_tool_truncation(
            agent,
            history,
            agent._get_model_context_length(),
            agent._estimate_context_overhead(),
        )
        agent._message_history = new_history
        for m in dropped:
            compacted_hashes.add(hash_message(m))

        cleaned, filtered_count = _strip_empty_thinking_parts(agent._message_history)

        # Ensure history ends with a ModelRequest — otherwise Anthropic etc.
        # reject it with a "prefill" error.
        while cleaned and isinstance(cleaned[-1], ModelResponse):
            cleaned.pop()

        # Always prune orphaned tool_call/tool_return pairs that may have
        # been created by truncate() during compaction. The model REQUIRES
        # valid tool call pairs — missing returns or stray calls cause it
        # to produce empty responses.
        cleaned = prune_interrupted_tool_calls(cleaned)

        agent._message_history = cleaned

        # PRE-SEND SIZE GATE: Final safety check — guarantees the request we
        # send NEVER exceeds a safe fraction of the model context. Reserves
        # room for the model's response (output tokens are counted by the
        # provider against the same budget on most APIs).
        #
        # Target: input tokens + overhead ≤ 80% of model_max
        # (leaves ~20% headroom for response generation + estimation drift)
        model_max = agent._get_model_context_length()
        overhead = agent._estimate_context_overhead()
        cache_g = CompactionCache()
        model_name_g: str | None = None
        with suppress(Exception):
            model_name_g = agent.get_model_name()

        SAFE_FRACTION = 0.80
        safe_input_tokens = max(1000, int(model_max * SAFE_FRACTION) - overhead)

        # Loop: each pass cuts the budget more aggressively if still over.
        # Most cases resolve in one pass; the loop is defense-in-depth for
        # pathological cases (e.g. system prompt itself dominating budget).
        for attempt in range(4):
            current_tokens = cache_g.sum_tokens(cleaned, model_name_g)
            total = current_tokens + overhead
            if total <= int(model_max * SAFE_FRACTION):
                break
            if len(cleaned) <= 2:
                # Already as small as possible — give up; downstream
                # error handling (emergency compact + retry) will catch it.
                emit_warning(
                    f"⚠️  Pre-send gate: cannot shrink further "
                    f"({total}/{model_max} tokens, {len(cleaned)} msgs)."
                )
                break

            # Each retry halves the available budget.
            shrink_factor = 0.5 ** (attempt + 1)
            target_protected = max(
                1000, int(safe_input_tokens * (0.5 + shrink_factor / 2))
            )
            cleaned = truncate(cleaned, target_protected, model_name_g, cache=cache_g)
            cleaned = prune_interrupted_tool_calls(cleaned)
            # Re-create cache because message identities may have changed.
            cache_g = CompactionCache()
            emit_warning(
                f"⚠️  Pre-send gate (pass {attempt + 1}): "
                f"{total}/{model_max} tokens too large; "
                f"truncating to {target_protected} protected tokens."
            )

        # Safety: ensure we didn't truncate away all user messages
        if len(cleaned) <= 1 and len(agent._message_history) > 1:
            emit_warning(
                "⚠️  Pre-send gate left only system prompt; "
                "restoring original history to prevent empty input."
            )
            cleaned = agent._message_history

        agent._message_history = cleaned

        on_message_history_processor_end(
            agent_name=getattr(agent, "name", None),
            session_id=getattr(agent, "session_id", None),
            message_history=list(cleaned),
            messages_added=messages_added,
            messages_filtered=len(messages) - messages_added + filtered_count,
        )

        return cleaned

    return history_processor


# --- Protected fact integration ---


def _inject_protected_facts_into_system(messages: list[ModelMessage]) -> bool:
    """Append protected facts to the system prompt (message at index 0).

    Returns True if facts were injected, False otherwise.
    """
    if not messages:
        return False

    system_msg = messages[0]
    if not isinstance(system_msg, ModelRequest):
        return False

    try:
        from code_muse.plugins.task_context.protected_facts import (
            get_protected_fact_manager,
        )

        mgr = get_protected_fact_manager()
        fact_block = mgr.get_prompt_block()
        if not fact_block:
            return False

        # Append to the first part with string content
        for part in system_msg.parts:
            if hasattr(part, "content") and isinstance(part.content, str):
                if "## Protected User Facts" not in part.content:
                    part.content += fact_block
                return True
    except Exception:
        _log = _logging.getLogger(__name__)
        _log.debug("Failed to inject protected facts", exc_info=True)

    return False


def _is_protected_message(
    message: ModelMessage, fact_manager: Any | None = None
) -> bool:
    """Check if a message contains protected fact content."""
    if fact_manager is None:
        try:
            from code_muse.plugins.task_context.protected_facts import (
                get_protected_fact_manager,
            )

            fact_manager = get_protected_fact_manager()
        except Exception:
            return False

    if not fact_manager.get_all_facts():
        return False

    text = _extract_message_text(message)
    for fact in fact_manager.get_all_facts():
        if fact.content.lower() in text.lower():
            return True
    return False


def _extract_message_text(message: ModelMessage) -> str:
    """Extract all text from a message for content matching."""
    parts = getattr(message, "parts", []) or []
    texts: list[str] = []
    for part in parts:
        content = getattr(part, "content", None)
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    texts.append(item)
    return " ".join(texts)


# --- Phase 3: Enhanced History Compression ---


def _truncate_tool_result_content(
    messages: list[ModelMessage],
    keep_count: int | None = None,
) -> list[ModelMessage]:
    """Replace older tool result content with a truncation marker.

    Keeps the last `keep_count` tool results in full.
    Older tool results get their content replaced with a short notice.
    The structural pairing (tool_call ↔ tool_return) stays intact.

    Only affects ToolReturnPart content — all other parts preserved.

    Args:
        messages: The message history.
        keep_count: Number of recent tool results to keep in full.
            Defaults to the configurable ``recent_tool_results_to_keep``.
    """
    if keep_count is None:
        keep_count = get_recent_tool_results_to_keep()
    # Reverse-scan: collect tool_call_ids of the most recent N tool results
    protected_ids: set[str] = set()
    seen = 0
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    seen += 1
                    if seen <= keep_count:
                        protected_ids.add(part.tool_call_id)

    # Forward-pass: truncate old results
    result: list[ModelMessage] = []
    TRUNCATION_MSG = "[Result truncated — re-call tool if full output is needed]"

    for msg in messages:
        if not isinstance(msg, ModelRequest):
            result.append(msg)
            continue
        new_parts = []
        truncated = False
        for part in msg.parts:
            if (
                isinstance(part, ToolReturnPart)
                and part.tool_call_id not in protected_ids
            ):
                # Replace content, keep structure
                truncated = True
                try:
                    if hasattr(part, "model_copy"):
                        new_parts.append(
                            part.model_copy(update={"content": TRUNCATION_MSG})
                        )
                    else:
                        new_parts.append(part)
                except Exception:
                    new_parts.append(part)
            else:
                new_parts.append(part)
        # Preserve identity when no parts were actually modified
        result.append(msg if not truncated else ModelRequest(parts=new_parts))

    return result


def compact_with_tool_truncation(
    agent: Any,
    messages: list[ModelMessage],
    model_max: int,
    context_overhead: int,
) -> tuple[list[ModelMessage], list[ModelMessage]]:
    """Enhanced compact() that first truncates old tool results,
    then runs normal compaction.

    Tool-result truncation runs when EITHER:
    - The message count is > 20, OR
    - Token usage already exceeds 50% of the context window.
    This ensures large tool results in short histories still get truncated.

    Returns: (new_messages, dropped_messages_for_hash_tracking)
    """
    # Decide whether tool-result truncation is worthwhile.
    # Skip only for very small histories that are also well within budget.
    model_name: str | None = None
    if agent is not None:
        try:
            model_name = agent.get_model_name()
        except Exception:
            model_name = None

    cache = CompactionCache()
    message_tokens = cache.sum_tokens(messages, model_name)
    proportion_used = (
        (message_tokens + context_overhead) / model_max if model_max else 0.0
    )
    needs_tool_truncation = (
        len(messages) > 20 or proportion_used > _TOOL_TRUNCATION_TOKEN_THRESHOLD
    )
    if not needs_tool_truncation:
        return compact(agent, messages, model_max, context_overhead)

    # Step 1: Truncate old tool results (always safe, always reduces tokens)
    truncated = _truncate_tool_result_content(messages)

    # Step 2: Run existing compaction on the already-trimmed history
    # The existing compact() handles summarization or truncation if still over threshold
    return compact(agent, truncated, model_max, context_overhead)
