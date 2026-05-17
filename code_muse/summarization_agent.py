import asyncio
import atexit
import dataclasses
import logging
import re
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
from code_muse.messaging import emit_warning
from code_muse.model_factory import ModelFactory, make_model_settings

logger = logging.getLogger(__name__)

# Keep a module-level agent reference to avoid rebuilding per call
_summarization_agent = None
# FREE-THREADED: _agent_lock guards sync-only agent cache access.
_agent_lock = threading.Lock()

# P2-05/PERF-05: track the model name the cached agent was built for
_cached_model_name: str | None = None

# Safe sync runner for async agent.run calls
# Avoids "event loop is already running" by offloading
# to a separate thread loop when needed
_thread_pool: ThreadPoolExecutor | None = None

# Reload counter
_reload_count = 0


# ---------------------------------------------------------------------------
# P2-05/PERF-05: Model config cache with mtime invalidation
# (fingerprint, cache, lock, and invalidate live in _models_config_utils)
# ---------------------------------------------------------------------------


def get_cached_models_config() -> dict[str, Any]:
    """Return the models config, using a cache invalidated by mtime/hash
    changes.

    This avoids re-reading ``models.json`` and extra model files on every
    call to ``ModelFactory.load_config()`` when nothing has changed. The
    cache is invalidated when any source file's mtime changes.

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
        # FREE-THREADED: ThreadPoolExecutor is compatible
        # with free-threaded Python 3.14.
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


# ---------------------------------------------------------------------------
# Summarization fidelity validation
# ---------------------------------------------------------------------------

_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"

_RE_DATE_LIKE = re.compile(
    r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b"  # numeric dates
    rf"|\b(?:{_MONTHS})[a-z]*\s+\d{{1,2}}\b"  # month-day
    rf"|\b\d{{1,2}}\s+(?:{_MONTHS})[a-z]*\b",  # day-month
    re.IGNORECASE,
)
_RE_NUMBER_VALUE = re.compile(r"\b\d+(?:[,.]\d+)?\s*%?\b")
_RE_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")


@dataclasses.dataclass
class SummaryValidationResult:
    """Result of validating a summary against expected fidelity
    constraints."""

    is_valid: bool
    preserved_facts_found: list[str] = dataclasses.field(default_factory=list)
    preserved_facts_missing: list[str] = dataclasses.field(default_factory=list)
    key_values_matched: dict[str, str] = dataclasses.field(default_factory=dict)
    issues: list[str] = dataclasses.field(default_factory=list)
    retry_needed: bool = False


def _extract_text_from_messages(messages: list) -> str:
    """Extract all text content from a list of model messages."""
    texts: list[str] = []
    for msg in messages:
        parts = getattr(msg, "parts", []) or []
        for part in parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, str):
                        texts.append(item)
    return " ".join(texts)


def _check_key_values_preserved(
    summary_text: str, key_values: list[str]
) -> tuple[list[str], list[str]]:
    """Check whether key values are preserved verbatim in summary text.

    Scans for:
    - Numbers (dates, budgets, prices, counts)
    - Proper nouns (capitalized names)
    - Date-like patterns

    Returns:
        (matched_values, missing_values) — each value from *key_values*
        classified as found or missing in *summary_text*.
    """
    matched: list[str] = []
    missing: list[str] = []

    for value in key_values:
        # Check for exact substring match first
        if value in summary_text:
            matched.append(value)
            continue

        # For date-like values, try flexible matching
        if _RE_DATE_LIKE.search(value):
            date_matches = _RE_DATE_LIKE.findall(summary_text)
            if any(value in " ".join(date_matches) for _ in date_matches):
                matched.append(value)
                continue

        # For numeric values, try to find the same number
        if _RE_NUMBER_VALUE.search(value):
            nums_in_summary = _RE_NUMBER_VALUE.findall(summary_text)
            nums_in_value = _RE_NUMBER_VALUE.findall(value)
            if nums_in_value and any(n in nums_in_summary for n in nums_in_value):
                matched.append(value)
                continue

        missing.append(value)

    return matched, missing


def _validate_summary_fidelity(messages: list) -> SummaryValidationResult:
    """Validate a summary's fidelity against protected facts and key
    values.

    Checks the summary output for:
    - Protected fact presence (from the protected facts manager)
    - Key value preservation (dates, numbers, names)

    Returns a :class:`SummaryValidationResult` with detailed findings.
    """
    summary_text = _extract_text_from_messages(messages)

    if not summary_text.strip():
        return SummaryValidationResult(
            is_valid=False,
            issues=["Summary text is empty"],
            retry_needed=True,
        )

    found_facts: list[str] = []
    missing_facts: list[str] = []
    issues: list[str] = []
    key_values_matched: dict[str, str] = {}

    # Check protected facts from the manager
    try:
        from code_muse.plugins.task_context.protected_facts import (
            get_protected_fact_manager,
        )

        mgr = get_protected_fact_manager()
        facts = mgr.get_all_facts()
        for fact in facts:
            if fact.content in summary_text:
                found_facts.append(fact.content)
            else:
                missing_facts.append(fact.content)
                issues.append(f"Protected fact not found verbatim: {fact.content[:60]}")
    except Exception:
        # Protected facts manager not available — skip
        pass

    # Check key values from the summary's own PRESERVED FACTS /
    # KEY VALUES sections
    key_values: list[str] = []

    # Extract values from PRESERVED FACTS section
    preserved_section = re.search(
        r"\*\*PRESERVED FACTS:\*\*(.*?)(?=\*\*[A-Z]|$)",
        summary_text,
        re.DOTALL,
    )
    if preserved_section:
        for line in preserved_section.group(1).strip().splitlines():
            m = re.match(r"\s*-\s+\[\w+\]\s+(.+)", line.strip())
            if m:
                key_values.append(m.group(1).strip())

    # Extract values from KEY VALUES section
    kv_section = re.search(
        r"\*\*KEY VALUES:\*\*(.*?)(?=\*\*[A-Z]|$)",
        summary_text,
        re.DOTALL,
    )
    if kv_section:
        for line in kv_section.group(1).strip().splitlines():
            m = re.match(r"\s*-\s+(\w[\w\s]*?):\s+(.+)", line.strip())
            if m:
                key_values.append(m.group(2).strip())
                key_values_matched[m.group(1).strip()] = m.group(2).strip()

    # Verify key values appear in the SUMMARY section
    summary_section = re.search(
        r"\*\*SUMMARY:\*\*(.*)",
        summary_text,
        re.DOTALL,
    )
    summary_body = summary_section.group(1) if summary_section else summary_text

    if key_values:
        _matched, missing = _check_key_values_preserved(summary_body, key_values)
        for v in missing:
            issues.append(f"Key value not found in summary body: {v[:60]}")

    is_valid = len(missing_facts) == 0 and len(issues) == 0
    retry_needed = len(missing_facts) > 0

    return SummaryValidationResult(
        is_valid=is_valid,
        preserved_facts_found=found_facts,
        preserved_facts_missing=missing_facts,
        key_values_matched=key_values_matched,
        issues=issues,
        retry_needed=retry_needed,
    )


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

    # Inject protected facts into summarization prompt with
    # MUST-preserve directive
    try:
        from code_muse.plugins.task_context.protected_facts import (
            get_protected_fact_manager,
        )

        mgr = get_protected_fact_manager()
        facts = mgr.get_all_facts()
        if facts:
            # Build a verbatim fact block
            fact_lines = []
            for f in facts:
                fact_lines.append(f"- [{f.category}] {f.content}")

            prompt = (
                prompt.rstrip()
                + "\n\n## PROTECTED FACTS TO PRESERVE VERBATIM\n"
                + "These facts are CRITICAL."
                " You MUST reproduce them verbatim:\n"
                + "\n".join(fact_lines)
                + "\n\nFAILURE TO PRESERVE THESE FACTS"
                " WILL CAUSE DATA LOSS.\n" + "After writing your summary,"
                " double-check every preserved fact"
                " is included EXACTLY.\n"
            )
    except Exception:
        pass

    logger.info(
        "Summarization LLM call starting: model=%s, messages=%d",
        model_name,
        len(message_history),
    )

    def _run_in_thread():
        """Run the async agent using the persistent summarization
        event loop.

        Uses run_until_complete instead of asyncio.run to avoid
        shutting down the default executor (which may break plugins
        in the main thread). The loop is reused across calls — no
        per-call creation/cleanup overhead.
        """
        loop = _get_event_loop()
        coro = agent.run(prompt, message_history=message_history)
        return loop.run_until_complete(coro)

    try:
        # Always use thread pool since we're likely in an existing
        # event loop
        pool = _ensure_thread_pool()
        result = pool.submit(_run_in_thread).result()
        new_msgs = result.new_messages()
        logger.info(
            "Summarization LLM call complete: input=%d msgs, output=%d msgs",
            len(message_history),
            len(new_msgs),
        )

        # Validate summary fidelity
        try:
            if new_msgs:
                validation = _validate_summary_fidelity(new_msgs)
                if validation.retry_needed:
                    emit_warning(
                        f"\u26a0\ufe0f  Summarization missing "
                        f"{len(validation.preserved_facts_missing)}"
                        f" protected facts. "
                        f"Facts missing:"
                        f" {validation.preserved_facts_missing[:3]}"
                    )
        except Exception:
            pass

        return new_msgs
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else "(no details available)"
        raise SummarizationError(
            f"LLM call failed during summarization: [{error_type}] {error_msg}",
            original_error=e,
        ) from e


def _get_summarization_instructions() -> str:
    """Get the system instructions for the summarization agent
    with fidelity guards."""
    return (
        "You are a message summarization expert. Your task is to "
        "summarize conversation messages while preserving ALL "
        "factual details with maximum fidelity.\n\n"
        "## CRITICAL: Fact Preservation Rules\n\n"
        "You MUST preserve these facts VERBATIM in your summary "
        "(exact values, no paraphrasing):\n"
        "1. **Names** — Keep all user and project names exactly "
        'as stated (e.g. "Amina", not "the user")\n'
        "2. **Dates and deadlines** — Keep exact dates "
        '(e.g. "June 3", not "early June")\n'
        "3. **Budgets and monetary amounts** — Keep exact numbers "
        'and currency (e.g. "4500 MAD", not "about 4500 dirhams")\n'
        "4. **Technical specifications** — Keep exact numbers, "
        "units, and parameters\n"
        "5. **Decisions and constraints** — Keep verbatim language "
        "from decisions\n\n"
        "## Output Format\n\n"
        "Your summary must be a structured document with these "
        "sections:\n\n"
        "**PRESERVED FACTS:**\n"
        "List each user-stated fact verbatim on its own line "
        "with its category:\n"
        "- [name] Amina\n"
        "- [deadline] June 3\n"
        "- [budget] 4500 MAD\n"
        "- [project] solar tracker\n\n"
        "**KEY VALUES:**\n"
        "List all key numeric/date values in a machine-readable "
        "format:\n"
        "- deadline: June 3\n"
        "- budget: 4500 MAD\n"
        "- name: Amina\n\n"
        "**SUMMARY:**\n"
        "A brief narrative summary of the conversation flow, "
        "mentioning all preserved facts in context.\n\n"
        "## Anti-Paraphrase Rules\n"
        '- NEVER approximate numbers (not "about 4500" but '
        '"4500")\n'
        '- NEVER rename entities (not "the individual" but '
        '"Amina")\n'
        '- NEVER change date formats (keep "June 3" not '
        '"03/06")\n'
        "- If you cannot reproduce a fact exactly, mark it "
        "[APPROXIMATE] and explain\n\n"
        "## Quality Gate\n"
        "Before returning, verify every fact listed in PRESERVED "
        "FACTS appears VERBATIM in the SUMMARY section.\n"
        "If any fact was paraphrased, FIX IT before finalizing."
        "\n\n"
        "When summarizing:\n"
        "1. Keep summary concise but informative\n"
        "2. Preserve ALL important context and key information "
        "and decisions\n"
        "3. Keep ALL important technical details and exact "
        "numbers\n"
        "4. Do NOT summarize the system message\n"
        "5. Make sure all tool calls and responses are "
        "summarized\n"
        "6. Focus on token usage efficiency and factual "
        "preservation"
    )


def reload_summarization_agent():
    """Create a specialized agent for summarizing messages when
    context limit is reached."""
    from code_muse.model_utils import prepare_prompt_for_model

    # Always bust the cache on explicit reload
    invalidate_models_config_cache()
    models_config = get_cached_models_config()
    model_name = get_summarization_model_name()
    model = ModelFactory.get_model(model_name, models_config)

    # Handle claude-code models: swap instructions
    # (prompt prepending happens in run_summarization_sync)
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
    # Summarization is a simple one-shot call that doesn't need
    # durable execution, and wrapping can cause async event loop
    # conflicts with run_sync().
    return agent


def get_summarization_agent(force_reload=False):
    """Retrieve the summarization agent, caching across calls.

    P2-05/PERF-05: The default is now ``force_reload=False``. The
    agent is rebuilt only when:
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
