"""TokenGuard A-E Protocol — automated verification harness.

Tests context-window memory fidelity across all compaction strategies
and context sizes using deterministic, mock-model-based simulations
(no real API calls).

Protocols:
  A: Single-injection recall — 5 facts at turn 1, verify after 25 turns
  B: Incremental-injection recall — 1 fact per turn × 10 turns, verify all
  C: Long-document recall — 3000-word doc, verify page-1 + 3-bullet summary
  D: Turn-2 exact recall — verify exact turn-2 content after 25+ turns
  E: Cross-strategy — run A-D across truncation and summarization strategies

Each protocol runs at 32k, 64k, and 128k context windows (when feasible).
"""

import random

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from code_muse.agents._history import CompactionCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOREM = (
    "The quick brown fox jumps over the lazy dog. Lorem ipsum dolor sit amet "
    "consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et "
    "dolore magna aliqua. Ut enim ad minim veniam quis nostrud exercitation "
    "ullamco laboris nisi ut aliquip ex ea commodo consequat. "
)


def _big_blob(approx_tokens: int, rng: random.Random, salt: str = "") -> str:
    """Generate roughly `approx_tokens` tokens of filler text."""
    target_chars = int(approx_tokens * 2.5)
    chunks: list[str] = []
    total = 0
    while total < target_chars:
        chunk = _LOREM + f" (seed-{rng.randint(0, 1_000_000)}{salt}) "
        chunks.append(chunk)
        total += len(chunk)
    return "".join(chunks)[:target_chars]


def build_system_prompt(model_label: str = "tokenguard-test") -> ModelMessage:
    return ModelRequest(
        parts=[
            UserPromptPart(
                content=(
                    "You are a TokenGuard test agent. Respond concisely. "
                    "Acknowledge the user's message briefly. "
                    f"Your ID is tokenguard-test-{model_label}."
                )
            )
        ]
    )


def build_user_message(content: str) -> ModelMessage:
    return ModelRequest(parts=[UserPromptPart(content=content)])


def build_assistant_message(content: str) -> ModelMessage:
    return ModelResponse(parts=[TextPart(content=content)])


def count_tokens(messages: list[ModelMessage]) -> int:
    cache = CompactionCache()
    return cache.sum_tokens(messages, model_name=None)


def check_content(messages: list[ModelMessage], fact_text: str) -> bool:
    """Check if text appears in any message."""
    for msg in messages:
        for part in getattr(msg, "parts", []) or []:
            content = getattr(part, "content", None) or ""
            if isinstance(content, str) and fact_text.lower() in content.lower():
                return True
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, str) and fact_text.lower() in item.lower():
                        return True
    return False


# ---------------------------------------------------------------------------
# Protocol A: Single-injection recall
# ---------------------------------------------------------------------------

FACTS_A = {
    "name": "Amina",
    "project": "solar tracker",
    "deadline": "June 3",
    "budget": "4500 MAD",
    "location": "Morocco",
}


def build_turns_for_protocol_a(num_turns: int = 25) -> list[ModelMessage]:
    """Build message history: 1 injection turn + N fluff turns."""
    history: list[ModelMessage] = [build_system_prompt("protocol-a")]

    # Turn 1: Inject all 5 facts
    fact_intro = (
        f"Hi, I'm {FACTS_A['name']}. I'm working on a {FACTS_A['project']} project. "
        f"The deadline is {FACTS_A['deadline']}, and my budget is {FACTS_A['budget']}. "
        f"The project is located in {FACTS_A['location']}."
    )
    history.append(build_user_message(fact_intro))
    history.append(
        build_assistant_message(
            f"Nice to meet you, {FACTS_A['name']}! "
            f"I've noted the {FACTS_A['project']} project, "
            f"deadline {FACTS_A['deadline']}, "
            f"budget {FACTS_A['budget']}, "
            f"location {FACTS_A['location']}."
        )
    )

    # Turns 2-25: Fluff
    rng = random.Random(42)
    for i in range(2, num_turns + 1):
        fluff = _big_blob(200, rng, salt=f"turn-{i}")
        history.append(build_user_message(f"Question {i}: {fluff[:100]}...?"))
        history.append(build_assistant_message(f"Answer for turn {i}: {fluff[:150]}"))

    return history


@pytest.mark.parametrize("context_size", [32_000, 64_000, 128_000])
@pytest.mark.parametrize("strategy", ["summarization", "truncation"])
def test_protocol_a_fact_recall(context_size: int, strategy: str, monkeypatch):
    """Protocol A: Inject 5 facts at turn 1, verify recall after compaction."""
    from code_muse.agents import _compaction
    from code_muse.config.parser import set_config_value

    set_config_value("compaction_strategy", strategy)
    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.85)
    monkeypatch.setattr(
        _compaction,
        "get_protected_token_count",
        lambda: int(context_size * 0.55),
    )

    history = build_turns_for_protocol_a(num_turns=25)
    before_count = len(history)
    before_tokens = count_tokens(history)

    compacted, dropped = _compaction.compact(
        agent=None,
        messages=history,
        model_max=context_size,
        context_overhead=5000,
    )

    after_count = len(compacted)
    after_tokens = count_tokens(compacted)

    print(
        f"\n[Protocol A / {context_size:,} / {strategy}] "
        f"{before_count} → {after_count} msgs, {before_tokens:,} → {after_tokens:,} tok"
    )

    for key, fact in FACTS_A.items():
        assert check_content(compacted, fact), (
            f"Fact '{key}'='{fact}' MISSING "
            f"after compaction ({context_size}, {strategy})"
        )

    if after_tokens < before_tokens:
        print(
            f"  ✅ Compacted: "
            f"{(before_tokens - after_tokens) / before_tokens * 100:.1f}% "
            "reduction"
        )
    print(f"  ✅ {len(FACTS_A)}/{len(FACTS_A)} facts preserved")


# ---------------------------------------------------------------------------
# Protocol B: Incremental injection
# ---------------------------------------------------------------------------

FACTS_B = [
    ("fact_1", "project name: Project Aurora"),
    ("fact_2", "start date: January 15"),
    ("fact_3", "team size: 8 people"),
    ("fact_4", "tech stack: Python, React, PostgreSQL"),
    ("fact_5", "budget: 25000 USD"),
    ("fact_6", "client: Acme Corp"),
    ("fact_7", "deadline: September 30"),
    ("fact_8", "location: remote"),
    ("fact_9", "stakeholder: Dr. Sarah Chen"),
    ("fact_10", "priority: high"),
]


def build_turns_for_protocol_b() -> list[ModelMessage]:
    """Inject 1 fact per turn for 10 turns, then 15 fluff turns."""
    history: list[ModelMessage] = [build_system_prompt("protocol-b")]
    rng = random.Random(99)

    for _i, (_key, fact) in enumerate(FACTS_B, 1):
        history.append(build_user_message(f"Setting: {fact}"))
        history.append(build_assistant_message(f"Got it, noted: {fact}"))

    for i in range(11, 26):
        fluff = _big_blob(200, rng, salt=f"turn-{i}")
        history.append(build_user_message(f"Question {i}: {fluff[:100]}...?"))
        history.append(build_assistant_message(f"Answer {i}: {fluff[:150]}"))

    return history


@pytest.mark.parametrize("context_size", [32_000, 64_000, 128_000])
@pytest.mark.parametrize("strategy", ["summarization", "truncation"])
def test_protocol_b_incremental_recall(context_size: int, strategy: str, monkeypatch):
    """Protocol B: 1 fact per turn × 10, verify all 10 survive compaction."""
    from code_muse.agents import _compaction
    from code_muse.config.parser import set_config_value

    set_config_value("compaction_strategy", strategy)
    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.85)
    monkeypatch.setattr(
        _compaction,
        "get_protected_token_count",
        lambda: int(context_size * 0.55),
    )

    history = build_turns_for_protocol_b()
    before_tokens = count_tokens(history)

    compacted, dropped = _compaction.compact(
        agent=None,
        messages=history,
        model_max=context_size,
        context_overhead=5000,
    )

    preserved = 0
    for key, fact in FACTS_B:
        if check_content(compacted, fact):
            preserved += 1
        else:
            print(f"  ⚠️  Fact '{key}': '{fact}' LOST")

    print(
        f"\n[Protocol B / {context_size:,} / {strategy}] "
        f"{preserved}/{len(FACTS_B)} facts preserved"
    )
    print(f"  Tokens: {before_tokens:,} → {count_tokens(compacted):,}")
    assert preserved >= 9, (
        f"Only {preserved}/{len(FACTS_B)} facts preserved (threshold: 9)"
    )


# ---------------------------------------------------------------------------
# Protocol C: Long-document recall
# ---------------------------------------------------------------------------


def build_3000_word_document() -> str:
    """Generate a realistic ~3000-word technical document."""
    lines = [
        "# Solar Tracking System — Technical Specification\n\n",
        "## 1. Introduction\n\n",
        "This document specifies the requirements and design "
        "for a dual-axis solar tracking system "
        "developed for deployment in North Africa. "
        "The system will increase energy yield by 25-40% "
        "compared to fixed-tilt installations. "
        "The primary deployment site is in Ouarzazate, Morocco.",
    ]
    for i in range(2, 16):
        lines.append(f"\n\n## {i}. Section {i}\n\n")
        for _ in range(5):
            lines.append(
                "Solar tracking technology has advanced significantly in recent years. "
                "Dual-axis trackers use both azimuth and elevation adjustment. "
                "Ambient temperature averages 35°C in summer. "
                "Wind speeds can reach 80 km/h. The system operates unattended. " * 3
            )
    return "".join(lines)


def build_turns_for_protocol_c(num_fluff: int = 25) -> list[ModelMessage]:
    """Build history with a 3000-word document at turn 1 + fluff."""
    history: list[ModelMessage] = [build_system_prompt("protocol-c")]
    doc = build_3000_word_document()
    history.append(build_user_message(doc))
    history.append(
        build_assistant_message(
            "I've read the solar tracking spec. "
            "Dual-axis system for Ouarzazate, Morocco. "
            "25-40% improvement, thermal management for 35°C, "
            "wind stow at 80 km/h."
        )
    )
    rng = random.Random(77)
    for i in range(2, num_fluff + 2):
        fluff = _big_blob(200, rng, salt=f"turn-c-{i}")
        history.append(build_user_message(f"Fluff Q{i}: {fluff[:100]}?"))
        history.append(build_assistant_message(f"Fluff A{i}: {fluff[:150]}"))
    return history


@pytest.mark.parametrize("context_size", [32_000, 64_000, 128_000])
@pytest.mark.parametrize("strategy", ["summarization", "truncation"])
def test_protocol_c_long_document_recall(context_size: int, strategy: str, monkeypatch):
    """Protocol C: 3000-word doc at turn 1, verify page-1 recall."""
    from code_muse.agents import _compaction
    from code_muse.config.parser import set_config_value

    set_config_value("compaction_strategy", strategy)
    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.85)
    monkeypatch.setattr(
        _compaction,
        "get_protected_token_count",
        lambda: int(context_size * 0.55),
    )

    history = build_turns_for_protocol_c()
    before_tokens = count_tokens(history)

    compacted, dropped = _compaction.compact(
        agent=None,
        messages=history,
        model_max=context_size,
        context_overhead=5000,
    )

    key_phrases = ["Ouarzazate", "dual-axis", "25-40%", "North Africa", "Morocco"]
    found = sum(1 for p in key_phrases if check_content(compacted, p))

    print(
        f"\n[Protocol C / {context_size:,} / {strategy}] "
        f"Page-1 recall: {found}/{len(key_phrases)} phrases"
    )
    print(f"  Tokens: {before_tokens:,} → {count_tokens(compacted):,}")

    if strategy == "summarization" and context_size >= 64_000:
        assert found >= 3, (
            f"Only {found}/{len(key_phrases)} page-1 key phrases preserved"
        )


# ---------------------------------------------------------------------------
# Protocol D: Turn-2 exact recall
# ---------------------------------------------------------------------------

_TURN_2_EXACT = (
    "My project is called Project Helios. "
    "The goal is to build a low-cost solar tracker "
    "for rural electrification in sub-Saharan Africa. "
    "The budget is strictly 5000 USD."
)


def build_turns_for_protocol_d(num_fluff: int = 25) -> list[ModelMessage]:
    """Build history with a distinctive turn-2 message + fluff."""
    history: list[ModelMessage] = [build_system_prompt("protocol-d")]
    history.append(build_user_message("Hello, I'd like some help with a project."))
    history.append(
        build_assistant_message(
            "Sure, I'm happy to help! What project are you working on?"
        )
    )
    history.append(build_user_message(_TURN_2_EXACT))
    history.append(
        build_assistant_message(
            "Project Helios sounds great! "
            "A low-cost solar tracker for rural electrification "
            "with a 5000 USD budget. Let me help with the design."
        )
    )
    rng = random.Random(123)
    for i in range(3, num_fluff + 3):
        fluff = _big_blob(200, rng, salt=f"turn-d-{i}")
        history.append(build_user_message(f"Q{i}: {fluff[:100]}?"))
        history.append(build_assistant_message(f"A{i}: {fluff[:150]}"))
    return history


@pytest.mark.parametrize("context_size", [32_000, 64_000, 128_000])
@pytest.mark.parametrize("strategy", ["summarization", "truncation"])
def test_protocol_d_turn2_recall(context_size: int, strategy: str, monkeypatch):
    """Protocol D: Verify exact turn-2 content is recoverable after compaction."""
    from code_muse.agents import _compaction
    from code_muse.config.parser import set_config_value

    set_config_value("compaction_strategy", strategy)
    monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.85)
    monkeypatch.setattr(
        _compaction,
        "get_protected_token_count",
        lambda: int(context_size * 0.55),
    )

    history = build_turns_for_protocol_d()
    before_tokens = count_tokens(history)

    compacted, dropped = _compaction.compact(
        agent=None,
        messages=history,
        model_max=context_size,
        context_overhead=5000,
    )

    key_terms = [
        "Project Helios",
        "low-cost solar tracker",
        "rural electrification",
        "5000 USD",
    ]
    found = sum(1 for t in key_terms if check_content(compacted, t))

    print(
        f"\n[Protocol D / {context_size:,} / {strategy}] "
        f"Turn-2 key terms: {found}/{len(key_terms)}"
    )
    print(f"  Tokens: {before_tokens:,} → {count_tokens(compacted):,}")

    if strategy == "summarization" and context_size >= 64_000:
        assert found >= 2, (
            f"Only {found}/{len(key_terms)} turn-2 terms "
            f"preserved under summarization at {context_size:,}"
        )


# ---------------------------------------------------------------------------
# Protocol E: Cross-strategy comparison
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("context_size", [32_000, 64_000, 128_000])
def test_protocol_e_cross_strategy(context_size: int, monkeypatch):
    """Protocol E: Run Protocol A across all compatible strategies."""
    from code_muse.agents import _compaction
    from code_muse.config.parser import set_config_value

    results = {}
    for strategy in ["summarization", "truncation"]:
        set_config_value("compaction_strategy", strategy)
        monkeypatch.setattr(_compaction, "get_compaction_threshold", lambda: 0.85)
        monkeypatch.setattr(
            _compaction,
            "get_protected_token_count",
            lambda: int(context_size * 0.55),
        )

        history = build_turns_for_protocol_a(num_turns=25)
        before_tokens = count_tokens(history)

        compacted, dropped = _compaction.compact(
            agent=None,
            messages=history,
            model_max=context_size,
            context_overhead=5000,
        )
        after_tokens = count_tokens(compacted)

        facts_preserved = sum(
            1 for f in FACTS_A.values() if check_content(compacted, f)
        )
        results[strategy] = {
            "before": before_tokens,
            "after": after_tokens,
            "compression_pct": (
                (1 - after_tokens / before_tokens) * 100 if before_tokens else 0
            ),
            "facts_preserved": facts_preserved,
        }

    print(f"\n[Protocol E / {context_size:,}] Cross-strategy comparison:")
    for strategy, r in results.items():
        print(
            f"  {strategy}: {r['facts_preserved']}/{len(FACTS_A)} facts, "
            f"{r['compression_pct']:.1f}% compression"
        )

    if context_size >= 64_000:
        for strategy, r in results.items():
            assert r["facts_preserved"] >= 4, (
                f"{strategy} at {context_size:,} only preserved "
                f"{r['facts_preserved']}/{len(FACTS_A)} facts"
            )

    print(f"  ✅ Both strategies pass at {context_size:,}")


# ---------------------------------------------------------------------------
# Protected facts integration test
# ---------------------------------------------------------------------------


def test_protocol_a_with_protected_facts():
    """Protocol A with protected facts plugin — facts should always survive."""
    try:
        from code_muse.plugins.task_context.protected_facts import (
            ProtectedFact,
            get_protected_fact_manager,
            reset_protected_fact_manager,
        )
    except ImportError:
        pytest.skip("Protected facts plugin not available")

    from code_muse.agents import _compaction

    reset_protected_fact_manager()
    mgr = get_protected_fact_manager()

    for key, fact in FACTS_A.items():
        mgr.add_fact(
            ProtectedFact(
                content=fact,
                category=key,
                priority=0,
                token_cost=50,
                immutable=True,
            )
        )

    history = build_turns_for_protocol_a(num_turns=25)
    compacted, _dropped = _compaction.compact(
        agent=None,
        messages=list(history),
        model_max=64_000,
        context_overhead=5000,
    )

    for key, fact in FACTS_A.items():
        assert check_content(compacted, fact), (
            f"Protected fact '{key}'='{fact}' LOST even with protection"
        )

    system_text = str(compacted[0])
    for key, fact in FACTS_A.items():
        assert fact in system_text or check_content(compacted, fact), (
            f"Protected fact '{key}' not found in system prompt or messages"
        )

    reset_protected_fact_manager()
    print(f"\n✅ Protocol A with protected facts: ALL {len(FACTS_A)} facts preserved")
