"""Mock-based compaction tests — no API keys needed.

Exercises the full compaction pipeline (make_history_processor → compact()
→ truncation/summarization) using a StaticMockModel instead of real LLMs.
Only the final model inference is stubbed; everything else runs in production.
"""

import random
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.usage import Usage

# ---------------------------------------------------------------------------
# Helpers — self-contained, no imports from other test files
# ---------------------------------------------------------------------------

_LOREM = (
    "The quick brown fox jumps over the lazy dog. "
    "Lorem ipsum dolor sit amet consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    "Ut enim ad minim veniam quis nostrud exercitation ullamco laboris. "
)


def _big_blob(approx_tokens: int, rng: random.Random) -> str:
    target_chars = int(approx_tokens * 2.5)
    chunks: list[str] = []
    total = 0
    while total < target_chars:
        chunk = _LOREM + f" (seed-{rng.randint(0, 1_000_000)}) "
        chunks.append(chunk)
        total += len(chunk)
    return "".join(chunks)[:target_chars]


def _msg(txt: str, is_user: bool = True) -> ModelMessage:
    """Single-turn user-request / assistant-response pair."""
    part = UserPromptPart(content=txt) if is_user else TextPart(content=txt)
    return ModelRequest(parts=[part]) if is_user else ModelResponse(parts=[part])


def _build_history(target_tokens: int = 200_000) -> list[ModelMessage]:
    """Return a synthetic message history of roughly *target_tokens*.

    The history starts with a system-like ModelRequest and alternates
    between ModelRequest (user) and ModelResponse (assistant) messages.
    """
    rng = random.Random(42)
    messages: list[ModelMessage] = [
        ModelRequest(
            parts=[UserPromptPart(content="You are a helpful assistant with tools.")]
        )
    ]

    tokens_per_pair = 200  # rough estimate
    n_pairs = max(1, target_tokens // tokens_per_pair)
    for i in range(n_pairs):
        blob = _big_blob(100, rng)
        user_part = UserPromptPart(content=f"Step {i}: {blob}")
        assistant_part = TextPart(content=f"Response {i}: {blob[:50]}...")
        messages.append(ModelRequest(parts=[user_part]))
        messages.append(ModelResponse(parts=[assistant_part]))
    return messages


def _count_orphan_ids(messages: list[ModelMessage]) -> tuple[set[str], set[str]]:
    """Return (unmatched_tool_call_ids, unmatched_tool_return_ids)."""
    call_ids: set[str] = set()
    return_ids: set[str] = set()
    for msg in messages:
        for part in msg.parts:
            tid = getattr(part, "tool_call_id", None)
            if tid:
                return_ids.add(tid)
            if isinstance(part, ToolCallPart):
                call_ids.add(part.tool_call_id)
    orphan_calls = call_ids - return_ids
    orphan_returns = return_ids - call_ids
    return orphan_calls, orphan_returns


def _tok(m: ModelMessage) -> int:
    """Rough token estimate (character-based)."""
    total = 0
    for p in m.parts:
        content = getattr(p, "content", "")
        if isinstance(content, str):
            total += len(content) // 2
    return max(1, total)


# ---------------------------------------------------------------------------
# Mock model
# ---------------------------------------------------------------------------


class StaticMockModel(Model):
    """Pydantic-ai Model that returns a fixed text response.

    Only the abstract ``request()`` method needs implementing.
    """

    model_name: str = "mock-model"
    system: str = "test"

    def __init__(self, response_text: str = "42") -> None:
        super().__init__()
        self._response_text = response_text

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: Any | None,
        model_request_parameters: ModelRequestParameters | None,
    ) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(content=self._response_text)],
            model_name=self.model_name,
            timestamp=datetime.now(UTC),
            usage=Usage(),
        )

    def request_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Streaming not supported in mock")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_agent(monkeypatch: pytest.MonkeyPatch) -> Any:
    """MuseAgent with StaticMockModel injected via ModelFactory.

    The pydantic agent is built via build_pydantic_agent(), so the
    full make_history_processor → compact() pipeline runs in production.
    """
    # Import _compaction BEFORE summarization_agent to avoid circular import:
    #   summarization_agent → model_factory → messaging → tools →
    #   agents._history → agents → base_agent → _builder → _compaction
    #   → summarization_agent  (circular!)
    # Pre-loading _compaction breaks the cycle.
    import code_muse.agents._compaction as _comp  # noqa: F401
    from code_muse import config as cp_config
    from code_muse import summarization_agent as _sum_mod
    from code_muse.agents import base_agent as _base_agent_mod
    from code_muse.agents.agent_muse import MuseAgent
    from code_muse.model_factory import ModelFactory

    pinned = "mocked-model"
    for mod in (cp_config, _base_agent_mod):
        if hasattr(mod, "get_global_model_name"):
            monkeypatch.setattr(mod, "get_global_model_name", lambda: pinned)
        if hasattr(mod, "get_agent_pinned_model"):
            monkeypatch.setattr(mod, "get_agent_pinned_model", lambda _n: pinned)
    monkeypatch.setattr(_sum_mod, "get_summarization_model_name", lambda: pinned)

    mock_model = StaticMockModel(response_text="42")

    def _mock_get_model(name: str, config: dict | None = None) -> Any:
        return mock_model

    monkeypatch.setattr(ModelFactory, "get_model", _mock_get_model)
    return MuseAgent()


# ---------------------------------------------------------------------------
# Test: truncation strategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncation_compacts_large_history(
    mocked_agent: Any, monkeypatch: pytest.MonkeyPatch
):
    """Large 200k-token history with truncation strategy → compaction fires."""
    from code_muse.agents import _compaction
    from code_muse.agents._builder import build_pydantic_agent

    monkeypatch.setattr(_compaction, "get_compaction_strategy", lambda: "truncation")
    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.5)
    monkeypatch.setattr(_compaction, "get_protected_token_count", lambda: 20_000)

    history = _build_history(target_tokens=200_000)
    before_tokens = sum(_tok(m) for m in history)
    before_len = len(history)

    agent = mocked_agent
    agent.set_message_history(list(history))
    build_pydantic_agent(agent)

    result = await agent.pydantic_agent.run(
        "What is 2+2? Reply with just the number.",
        message_history=list(agent.get_message_history()),
    )

    assert result is not None
    after = agent.get_message_history()
    after_tokens = sum(_tok(m) for m in after)
    assert len(after) < before_len, (
        f"History did not shrink: {before_len} -> {len(after)}"
    )
    assert after_tokens < before_tokens, (
        f"Tokens did not drop: {before_tokens} -> {after_tokens}"
    )
    assert isinstance(after[0], ModelRequest), "First msg must be ModelRequest"
    orphan_calls, orphan_returns = _count_orphan_ids(after)
    assert not orphan_calls, f"Orphan tool_calls: {orphan_calls}"
    assert not orphan_returns, f"Orphan tool_returns: {orphan_returns}"
    assert isinstance(after[-1], ModelRequest), (
        f"History must end with ModelRequest, got {type(after[-1]).__name__}"
    )


@pytest.mark.asyncio
async def test_truncation_no_compaction_under_threshold(
    mocked_agent: Any, monkeypatch: pytest.MonkeyPatch
):
    """Small history + high threshold → compaction does NOT fire."""
    from code_muse.agents import _compaction
    from code_muse.agents._builder import build_pydantic_agent

    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.95)
    monkeypatch.setattr(_compaction, "get_compaction_strategy", lambda: "truncation")

    history = _build_history(target_tokens=5_000)
    agent = mocked_agent
    agent.set_message_history(list(history))
    build_pydantic_agent(agent)

    before_len = len(agent.get_message_history())

    result = await agent.pydantic_agent.run(
        "What is 3+3? Reply with just the number.",
        message_history=list(agent.get_message_history()),
    )

    assert result is not None
    after_len = len(agent.get_message_history())
    assert after_len >= before_len, (
        f"Under-threshold history shrank: {before_len} -> {after_len}"
    )


# ---------------------------------------------------------------------------
# Test: summarization strategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarization_attempted(
    mocked_agent: Any, monkeypatch: pytest.MonkeyPatch
):
    """Summarization strategy → summarize() is called."""
    from code_muse.agents import _compaction
    from code_muse.agents._builder import build_pydantic_agent

    monkeypatch.setattr(_compaction, "get_compaction_strategy", lambda: "summarization")
    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.5)
    monkeypatch.setattr(_compaction, "get_protected_token_count", lambda: 20_000)

    history = _build_history(target_tokens=200_000)
    agent = mocked_agent
    agent.set_message_history(list(history))
    agent.set_message_history(list(history))
    build_pydantic_agent(agent)

    call_count = 0

    def spy_summarize(*args: Any, **kwargs: Any) -> tuple[list, list]:
        nonlocal call_count
        call_count += 1
        return [
            history[0],
            ModelRequest(parts=[UserPromptPart(content="<summarized>")]),
        ], history[1:]

    monkeypatch.setattr(_compaction, "summarize", spy_summarize)

    result = await agent.pydantic_agent.run(
        "What is 2+2? Reply with just the number.",
        message_history=list(agent.get_message_history()),
    )

    assert result is not None
    assert call_count >= 1, "summarize() was never called"
    after = agent.get_message_history()
    orphan_calls, orphan_returns = _count_orphan_ids(after)
    assert not orphan_calls, f"Orphan tool_calls: {orphan_calls}"
    assert not orphan_returns, f"Orphan tool_returns: {orphan_returns}"
    assert isinstance(after[-1], ModelRequest), (
        f"History must end with ModelRequest, got {type(after[-1]).__name__}"
    )


# ---------------------------------------------------------------------------
# Test: orphan tool call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orphan_tool_call_does_not_block_compaction(
    mocked_agent: Any, monkeypatch: pytest.MonkeyPatch
):
    """Orphan tool_call in history → compaction proceeds anyway."""
    from code_muse.agents import _compaction
    from code_muse.agents._builder import build_pydantic_agent

    monkeypatch.setattr(_compaction, "get_compaction_strategy", lambda: "truncation")
    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.5)
    monkeypatch.setattr(_compaction, "get_protected_token_count", lambda: 20_000)

    history = _build_history(target_tokens=200_000)
    orphan = ModelResponse(
        parts=[
            ToolCallPart(
                tool_name="read_file",
                args={"file_path": "/cancelled.txt"},
                tool_call_id="orphan_run",
            )
        ]
    )
    history = [history[0], orphan] + history[1:]

    agent = mocked_agent
    agent.set_message_history(list(history))
    build_pydantic_agent(agent)

    result = await agent.pydantic_agent.run(
        "What is 5+5? Reply with just the number.",
        message_history=list(agent.get_message_history()),
    )

    assert result is not None
    after = agent.get_message_history()
    for m in after:
        for p in getattr(m, "parts", []):
            assert getattr(p, "tool_call_id", None) != "orphan_run", (
                "orphan tool_call leaked through"
            )
    orphan_calls, orphan_returns = _count_orphan_ids(after)
    assert not orphan_calls, f"Orphan tool_calls: {orphan_calls}"
    assert not orphan_returns, f"Orphan tool_returns: {orphan_returns}"
    assert isinstance(after[-1], ModelRequest), (
        f"History must end with ModelRequest, got {type(after[-1]).__name__}"
    )


# ---------------------------------------------------------------------------
# Test: summarization fallback to truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarization_fallback_to_truncation(
    mocked_agent: Any, monkeypatch: pytest.MonkeyPatch
):
    """When summarization fails, compaction falls back to truncation."""
    from code_muse.agents import _compaction
    from code_muse.agents._builder import build_pydantic_agent

    monkeypatch.setattr(_compaction, "get_compaction_strategy", lambda: "summarization")
    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.5)
    monkeypatch.setattr(_compaction, "get_protected_token_count", lambda: 20_000)

    summarize_attempted = False
    truncate_fallback_called = False

    def raise_summarize(*args: Any, **kwargs: Any) -> Any:
        nonlocal summarize_attempted
        summarize_attempted = True
        raise RuntimeError("Simulated summarization failure")

    orig_truncate = _compaction._truncate_with_dropped

    def spy_truncate(*args: Any, **kwargs: Any) -> tuple[list, list]:
        nonlocal truncate_fallback_called
        truncate_fallback_called = True
        return orig_truncate(*args, **kwargs)

    monkeypatch.setattr(_compaction, "_run_summarization_core", raise_summarize)
    monkeypatch.setattr(_compaction, "_truncate_with_dropped", spy_truncate)

    history = _build_history(target_tokens=200_000)
    before_tokens = sum(_tok(m) for m in history)

    agent = mocked_agent
    agent.set_message_history(list(history))
    build_pydantic_agent(agent)

    result = await agent.pydantic_agent.run(
        "hi",
        message_history=list(agent.get_message_history()),
    )

    assert result is not None
    assert summarize_attempted, "_run_summarization_core was never called"
    assert truncate_fallback_called, (
        "_truncate_with_dropped was not called — fallback did not fire"
    )

    after = agent.get_message_history()
    after_tokens = sum(_tok(m) for m in after)
    assert after_tokens < before_tokens, (
        f"Tokens did not drop: {before_tokens} -> {after_tokens}"
    )
    orphan_calls, orphan_returns = _count_orphan_ids(after)
    assert not orphan_calls, f"Orphan tool_calls: {orphan_calls}"
    assert not orphan_returns, f"Orphan tool_returns: {orphan_returns}"
    assert isinstance(after[-1], ModelRequest), (
        f"History must end with ModelRequest, got {type(after[-1]).__name__}"
    )
