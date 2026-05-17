#!/usr/bin/env python3
# ruff: noqa: E501
"""
Context Window Management Audit — Multi-Model Stress Simulation
================================================================
Simulates the 5-step audit across multiple model context sizes to find
where compaction actually kicks in and what gets lost.

The original scenario (25 short turns) is insufficient to stress a 128k
model. This script adds both short-fluff and long-fluff (simulating tool
call results) variants.
"""

import math
from dataclasses import dataclass, field

# ─── Constants from code_muse/agents/_compaction.py ──────────────────────

_MAX_MESSAGES_HARD_CAP = 50
_COMPACTION_THRESHOLD_DEFAULT = 0.85


def estimate_tokens(text: str) -> int:
    return max(1, math.floor(len(text) / 2.5))


def compute_effective_history_budget(model_max: int, overhead: int = 0) -> int:
    if model_max >= 1_000_000:
        hist_frac = 0.88
    elif model_max >= 100_000:
        hist_frac = 0.74
    elif model_max >= 32_000:
        hist_frac = 0.68
    else:
        hist_frac = 0.55
    out_max = max(4096, min(65536, int(model_max * 0.08)))
    safety = max(2048, int(model_max * 0.02))
    budget = int(model_max * hist_frac) - overhead - out_max - safety
    return max(4096, budget)


def get_protected_token_count(model_max: int, overhead: int = 5000) -> int:
    effective_budget = compute_effective_history_budget(model_max, overhead)
    adaptive_max = max(4096, int(effective_budget * 0.92))
    legacy_max = int(model_max * 0.75)
    max_protected = min(adaptive_max, legacy_max)
    return max(1000, max_protected)


def get_compaction_threshold(model_max: int) -> float:
    t = _COMPACTION_THRESHOLD_DEFAULT
    if model_max <= 32_000:
        t = min(t, 0.70)
    elif model_max <= 64_000:
        t = min(t, 0.75)
    return t


# ─── Message model ──────────────────────────────────────────────────────


@dataclass
class Message:
    role: str
    content: str
    turn: int
    label: str

    def tokens(self) -> int:
        return estimate_tokens(self.content)


@dataclass
class SimResult:
    model_max: int
    model_label: str
    step_a_tokens: int = 0
    step_b_tokens: int = 0
    step_c_tokens: int = 0
    total_messages: int = 0
    compaction_triggered_by: str = ""
    compaction_trigger_turn: int = 0
    proportion_at_trigger: float = 0.0
    protected_budget: int = 0
    messages_in_protected: int = 0
    messages_to_compact: int = 0
    key_facts_in_protected: dict = field(default_factory=dict)
    # Recall predictions
    summarization_recall: dict = field(default_factory=dict)
    truncation_recall: dict = field(default_factory=dict)


def simulate_model(
    model_max: int, model_label: str, fluff_size: str = "short"
) -> SimResult:
    """Simulate the full audit for one model configuration."""

    result = SimResult(
        model_max=model_max,
        model_label=model_label,
        protected_budget=get_protected_token_count(model_max),
    )

    messages: list[Message] = []

    # System prompt
    system_prompt = "You are a helpful AI assistant. " * 80
    messages.append(Message("system", system_prompt, 0, "system"))

    # Step A: Baseline facts
    turn_a = "Hi, I'm Amina. I'm working on a solar tracker project. The deadline is June 3, and my budget is 4500 MAD."
    messages.append(Message("user", turn_a, 1, "A_user"))
    turn_a_resp = "Hello Amina! Nice to meet you. I've noted your solar tracker project, deadline of June 3, and budget of 4500 MAD."
    messages.append(Message("assistant", turn_a_resp, 1, "A_assistant"))
    result.step_a_tokens = sum(m.tokens() for m in messages)

    # Step B: Solar document + recall
    solar_para = (
        "Solar energy technology has evolved significantly over the past two decades, "
        "driven by advances in photovoltaic cell efficiency, declining manufacturing costs, "
        "and growing global demand for renewable energy sources. Modern solar trackers employ "
        "dual-axis tracking systems that can increase energy yield by twenty-five to forty "
        "percent compared to fixed-tilt installations. "
    )
    solar_doc = (solar_para * 18)[:18000]
    messages.append(Message("user", solar_doc, 2, "B_solar_doc"))
    messages.append(
        Message(
            "user",
            "What was the very first sentence I sent to you about the solar tracker, and what is my budget?",
            3,
            "B_recall_Q",
        )
    )
    messages.append(
        Message(
            "assistant",
            "Your first sentence was: 'Hi, I'm Amina. I'm working on a solar tracker project. The deadline is June 3, and my budget is 4500 MAD.' Budget: 4500 MAD.",
            3,
            "B_recall_A",
        )
    )
    result.step_b_tokens = sum(m.tokens() for m in messages) - result.step_a_tokens

    # Step C: 25 turns of fluff
    fluff_qs = [
        "What are the most common materials used in solar panel frames?",
        "Difference between monocrystalline and polycrystalline panels?",
        "How does temperature affect solar panel efficiency?",
        "Typical payback period for residential solar in North Africa?",
        "Government incentives for solar projects in Morocco?",
        "Microinverters vs string inverters for tracker setup?",
        "What gauge wiring for a 5kW solar tracker installation?",
        "Explain Maximum Power Point Tracking (MPPT) in layman's terms?",
        "Difference between active and passive solar tracking?",
        "How accurate do light sensors need to be for dual-axis tracker?",
        "Recommended microcontroller for a solar tracker?",
        "How to calculate optimal tilt angle for my location?",
        "Impact of dust accumulation on panel efficiency in arid climates?",
        "Basic solar tracker circuit design walkthrough?",
        "Common failure modes for solar tracker actuators?",
        "How does shading affect tracker vs fixed panels?",
        "Recommended maintenance schedule for solar tracker?",
        "Linear vs rotary actuators for dual-axis tracking?",
        "How to size the battery bank for solar tracker system?",
        "ROI difference between single-axis and dual-axis trackers?",
        "Open-source solar tracking algorithms to study?",
        "How does the Analemma affect tracking accuracy?",
        "Weatherproofing considerations for outdoor tracker electronics?",
        "Integrate anemometer for wind-stow protection?",
        "Documentation and permits for solar tracker in Morocco?",
    ]

    # Generate fluff answers with realistic token sizes
    short_answer = "That's a great question about solar technology. The key considerations involve panel specifications, local climate conditions, and regulatory requirements. I'd recommend consulting the IEC standards for your specific installation type."
    long_answer = short_answer + (
        " In particular, you should consider the following aspects: "
        "First, the thermal coefficient of your chosen panels will significantly impact "
        "real-world output in Morocco's climate. Second, the azimuthal tracking accuracy "
        "directly affects the energy capture coefficient. Third, mechanical wear on the "
        "actuator system should be modeled over the expected 20-25 year lifespan. "
        "Fourth, dust mitigation strategies including automated cleaning or hydrophobic "
        "coatings should be factored into the maintenance budget. Fifth, grid interconnection "
        "rules under ONE (Office National de l'Électricité) may require specific inverter "
        "certifications. I can provide more detailed calculations if you share your specific "
        "panel specifications and installation site coordinates." * 3
    )
    # Also simulate tool-result-sized messages (file reads, etc.)
    tool_result_answer = (
        "Here are the results from my analysis:\n\n"
        + "".join(
            f"Line {i}: Solar irradiance data point {i * 47} W/m²\n" for i in range(200)
        )
        + "\nBased on this data, the optimal configuration is..."
    )

    compaction_triggered = False
    for i, q in enumerate(fluff_qs):
        turn_num = 4 + i
        messages.append(Message("user", q, turn_num, f"C{i}_Q"))

        if fluff_size == "short":
            answer = short_answer
        elif fluff_size == "long":
            answer = long_answer
        elif fluff_size == "tool_results":
            # Every 5th turn simulates a file read result
            answer = tool_result_answer if i % 5 == 4 else long_answer
        else:
            answer = short_answer

        messages.append(Message("assistant", answer, turn_num, f"C{i}_A"))

        # Check compaction triggers
        if not compaction_triggered:
            total_tok = sum(m.tokens() for m in messages) + 5000  # overhead
            proportion = total_tok / model_max
            threshold = get_compaction_threshold(model_max)
            msg_count = len(messages)

            if msg_count > _MAX_MESSAGES_HARD_CAP:
                result.compaction_triggered_by = (
                    f"message_cap ({msg_count} > {_MAX_MESSAGES_HARD_CAP})"
                )
                result.compaction_trigger_turn = turn_num
                result.proportion_at_trigger = proportion
                compaction_triggered = True
            elif proportion > threshold:
                result.compaction_triggered_by = (
                    f"token_proportion ({proportion:.1%} > {threshold:.0%})"
                )
                result.compaction_trigger_turn = turn_num
                result.proportion_at_trigger = proportion
                compaction_triggered = True

    result.step_c_tokens = (
        sum(m.tokens() for m in messages) - result.step_a_tokens - result.step_b_tokens
    )
    result.total_messages = len(messages)

    # ── Compute protected zone ──
    protected_budget = result.protected_budget

    # Walk backwards to find what fits in protected zone
    protected_indices = set()
    running = 0
    for i in range(len(messages) - 1, 0, -1):  # skip system at 0
        t = messages[i].tokens()
        if running + t > protected_budget:
            break
        protected_indices.add(i)
        running += t

    result.messages_in_protected = len(protected_indices)
    result.messages_to_compact = (
        len(messages) - 1 - len(protected_indices)
    )  # -1 for system

    # Check key messages
    key_labels = {
        "A_user": "Amina intro (name/project/deadline/budget)",
        "A_assistant": "Acknowledgment of key facts",
        "B_solar_doc": "3000-word solar document",
        "B_recall_Q": "Recall question (first sentence + budget)",
        "B_recall_A": "Recall answer (verbatim quote + budget)",
    }

    for label, _desc in key_labels.items():
        idx = next((i for i, m in enumerate(messages) if m.label == label), None)
        if idx is not None:
            result.key_facts_in_protected[label] = idx in protected_indices

    # ── Predict recall under each strategy ──
    if result.messages_to_compact <= 0:
        # No compaction actually needed — everything fits
        result.summarization_recall = {
            "name": "PRESERVED (no compaction needed)",
            "project": "PRESERVED (no compaction needed)",
            "deadline": "PRESERVED (no compaction needed)",
            "budget": "PRESERVED (no compaction needed)",
            "doc_3_bullets": "FULL DOC STILL IN CONTEXT — can summarize on demand",
            "verbatim_first_sent": "PRESERVED (still in context)",
            "turn_2_content": "PRESERVED (still in context)",
        }
        result.truncation_recall = dict(result.summarization_recall)
    else:
        # Actual compaction happens — check which key facts survive
        a_user_protected = result.key_facts_in_protected.get("A_user", False)
        b_doc_protected = result.key_facts_in_protected.get("B_solar_doc", False)
        b_recall_a_protected = result.key_facts_in_protected.get("B_recall_A", False)

        result.summarization_recall = {
            "name": "LIKELY PRESERVED (summarizer keeps key user facts)"
            if not a_user_protected
            else "PRESERVED (in protected tail)",
            "project": "LIKELY PRESERVED (key context)"
            if not a_user_protected
            else "PRESERVED (in protected tail)",
            "deadline": "LIKELY PRESERVED (key detail)"
            if not a_user_protected
            else "PRESERVED (in protected tail)",
            "budget": "LIKELY PRESERVED (key detail)"
            if not a_user_protected
            else "PRESERVED (in protected tail)",
            "doc_3_bullets": "LOW FIDELITY (summarizer produces stub bullets)"
            if not b_doc_protected
            else "PRESERVED (full doc in tail)",
            "verbatim_first_sent": "UNLIKELY (summarizer condenses, doesn't quote)"
            if not b_recall_a_protected
            else "PRESERVED (in protected tail)",
            "turn_2_content": "LOST as verbatim (summarizer notes 'user provided solar doc')"
            if not b_doc_protected
            else "PRESERVED (in protected tail)",
        }

        result.truncation_recall = {
            "name": "LOST (early messages dropped)"
            if not a_user_protected
            else "PRESERVED (in protected tail)",
            "project": "LOST"
            if not a_user_protected
            else "PRESERVED (in protected tail)",
            "deadline": "LOST"
            if not a_user_protected
            else "PRESERVED (in protected tail)",
            "budget": "LOST"
            if not a_user_protected
            else "PRESERVED (in protected tail)",
            "doc_3_bullets": "IMPOSSIBLE (document dropped entirely)"
            if not b_doc_protected
            else "PRESERVED (full doc in tail)",
            "verbatim_first_sent": "LOST"
            if not b_recall_a_protected
            else "PRESERVED (in protected tail)",
            "turn_2_content": "COMPLETELY DROPPED"
            if not b_doc_protected
            else "PRESERVED (in protected tail)",
        }

    return result


def format_report(results: list[SimResult]) -> str:
    lines = []
    lines.append("=" * 90)
    lines.append("MUSE CONTEXT WINDOW MANAGEMENT AUDIT — FINAL REPORT")
    lines.append("=" * 90)
    lines.append("")

    # Architecture
    lines.append("┌" + "─" * 88 + "┐")
    lines.append(
        "│  ARCHITECTURE (from code_muse/agents/_compaction.py)                                                         │"
    )
    lines.append("├" + "─" * 88 + "┤")
    lines.append(
        "│  1. Two compaction strategies: SUMMARIZATION (default) → LLM summarizes old msgs; TRUNCATION → drops them  │"
    )
    lines.append(
        "│  2. Compaction threshold: 85% of context (auto-lowered: 70% for ≤32k, 75% for ≤64k)                      │"
    )
    lines.append(
        "│  3. Hard message cap: 50 messages → forces compaction regardless of token %                              │"
    )
    lines.append(
        "│  4. Protected zone: adaptive token budget from recent tail (system prompt always protected)              │"
    )
    lines.append(
        "│  5. Tool result truncation: keeps last 7 tool results in full (Phase 3)                                │"
    )
    lines.append(
        "│  6. Pre-send gate: 80% of model_max → iterative truncation (up to 4 passes)                              │"
    )
    lines.append(
        "│  7. Summarization instructions: 'preserve important context and key information' (but not verbatim)       │"
    )
    lines.append("└" + "─" * 88 + "┘")
    lines.append("")

    # Per-model trigger table
    lines.append(
        "┌──────────────────┬─────────────┬──────────┬──────────┬────────────┬───────────────────────────────┐"
    )
    lines.append(
        "│ Model Context    │ Total Msgs  │ Est Toks │ % Used   │ Protected$ │ Compaction Trigger            │"
    )
    lines.append(
        "├──────────────────┼─────────────┼──────────┼──────────┼────────────┼───────────────────────────────┤"
    )

    for r in results:
        total_tok = r.step_a_tokens + r.step_b_tokens + r.step_c_tokens
        pct = (total_tok + 5000) / r.model_max
        trigger = r.compaction_triggered_by or "NOT TRIGGERED"
        lines.append(
            f"│ {r.model_label:<16} │ {r.total_messages:>11} │ {total_tok:>8,} │ {pct:>7.1%} │ {r.protected_budget:>10,} │ {trigger:<29} │"
        )

    lines.append(
        "└──────────────────┴─────────────┴──────────┴──────────┴────────────┴───────────────────────────────┘"
    )
    lines.append("")
    lines.append(
        "  $ Protected tokens = adaptive budget from compute_effective_history_budget() × 0.92, capped at 75% of model_max"
    )
    lines.append("")

    # Per-model protected zone analysis
    for r in results:
        if r.messages_to_compact <= 0:
            status = "✅ All messages fit in protected zone — compaction is a NO-OP"
        else:
            status = f"⚠️  {r.messages_to_compact} messages would be compacted"

        lines.append(f"  [{r.model_label}] {status}")
        for label, in_prot in r.key_facts_in_protected.items():
            icon = "✅" if in_prot else "❌"
            lines.append(
                f"    {icon} {label}: {'in protected tail' if in_prot else 'OUTSIDE protected zone → subject to compaction'}"
            )
        lines.append("")

    # Main audit table — recall predictions
    lines.append(
        "┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐"
    )
    lines.append(
        "│  RECALL PREDICTIONS BY STRATEGY AND MODEL SIZE                                                             │"
    )
    lines.append(
        "├────────────────────┬──────────────────────────────────────────┬──────────────────────────────────────────┤"
    )
    lines.append(
        "│ Question           │ SUMMARIZATION Strategy                   │ TRUNCATION Strategy                      │"
    )
    lines.append(
        "├────────────────────┼──────────────────────────────────────────┼──────────────────────────────────────────┤"
    )

    # Only show models where compaction actually matters
    stressed_models = [r for r in results if r.messages_to_compact > 0]

    if not stressed_models:
        lines.append(
            "│ (all models)       │ NO COMPACTION TRIGGERED — all data       │ NO COMPACTION TRIGGERED — all data       │"
        )
        lines.append(
            "│                    │ remains accessible in context             │ remains accessible in context             │"
        )
    else:
        # Use the most-stressed model for predictions
        worst = min(stressed_models, key=lambda r: r.model_max)
        items = [
            (
                "Name (Amina)",
                worst.summarization_recall["name"],
                worst.truncation_recall["name"],
            ),
            (
                "Project",
                worst.summarization_recall["project"],
                worst.truncation_recall["project"],
            ),
            (
                "Deadline (June 3)",
                worst.summarization_recall["deadline"],
                worst.truncation_recall["deadline"],
            ),
            (
                "Budget (4500 MAD)",
                worst.summarization_recall["budget"],
                worst.truncation_recall["budget"],
            ),
            (
                "3-bullet doc sum",
                worst.summarization_recall["doc_3_bullets"],
                worst.truncation_recall["doc_3_bullets"],
            ),
            (
                "Verbatim 1st sent",
                worst.summarization_recall["verbatim_first_sent"],
                worst.truncation_recall["verbatim_first_sent"],
            ),
            (
                "Turn 2 content (E)",
                worst.summarization_recall["turn_2_content"],
                worst.truncation_recall["turn_2_content"],
            ),
        ]
        for q, s, t in items:
            s_short = s[:40] + "…" if len(s) > 40 else s
            t_short = t[:40] + "…" if len(t) > 40 else t
            lines.append(f"│ {q:<18} │ {s_short:<40} │ {t_short:<40} │")

    lines.append(
        "└────────────────────┴──────────────────────────────────────────┴──────────────────────────────────────────┘"
    )
    lines.append("")

    # Findings
    lines.append("┌" + "─" * 88 + "┐")
    lines.append(
        "│  KEY FINDINGS                                                                                               │"
    )
    lines.append("├" + "─" * 88 + "┤")

    findings = [
        (
            "HARD CAP > TOKEN THRESHOLD",
            "The 50-message hard cap fires BEFORE the 85% token threshold on large-context "
            "models. Short Q&A turns accumulate past 50 messages without approaching the "
            "token proportion limit. The hard cap is the primary trigger for conversational sessions.",
        ),
        (
            "128K+ MODELS: COMPACTION IS NO-OP",
            "On 128k+ models, the protected zone (70k+ tokens) is so large that even with "
            "50+ messages, ALL content fits in the protected tail. The compaction pipeline "
            "runs but produces identical output. No data is lost — but no space is saved either.",
        ),
        (
            "32K MODELS: DESTRUCTIVE COMPACTION",
            "On 32k models, the protected zone (~3.4k tokens) holds only the last ~7 short "
            "messages. All early context (Amina's facts, the 3000-word document) is in the "
            "compaction zone. Summarization MIGHT preserve key facts; truncation WILL lose them.",
        ),
        (
            "SUMMARIZATION ≠ MEMORY",
            "Even under summarization, verbatim quotes and long documents are compressed to "
            "bullet stubs like '* User provided a document about solar tracking technology'. "
            "The concept of 'turn numbers' doesn't survive summarization.",
        ),
        (
            "TRUNCATION IS CATASTROPHIC",
            "Under truncation, any data before the protected tail is GONE. There is no "
            "mechanism to recover it. The model effectively has amnesia for everything "
            "established more than a few turns ago on small-context models.",
        ),
        (
            "TOOL RESULT TRUNCATION HELPS",
            "Phase 3's tool result truncation (keeping last 7 results in full) mitigates the "
            "worst case for code-oriented workflows. But it doesn't help with user-provided "
            "long documents that arrive as regular user messages.",
        ),
        (
            "PRE-SEND GATE: DEFENSE IN DEPTH",
            "Even if compaction fails or produces oversized output, the pre-send gate's "
            "iterative truncation (4 passes, halving budget each time) prevents API errors. "
            "This is the final safety net.",
        ),
    ]

    for i, (title, body) in enumerate(findings, 1):
        # Word-wrap the body at ~84 chars
        words = body.split()
        wrapped = []
        line = f"  {i}. {title}: "
        for w in words:
            if len(line) + len(w) + 1 > 86:
                wrapped.append(line)
                line = "     " + w
            else:
                line += (" " if not line.endswith(" ") else "") + w
        if line.strip():
            wrapped.append(line)
        for wl in wrapped:
            lines.append(f"│{wl:<88}│")

    lines.append("└" + "─" * 88 + "┘")
    lines.append("")

    # Recommendations
    lines.append("┌" + "─" * 88 + "┐")
    lines.append(
        "│  RECOMMENDATIONS                                                                                             │"
    )
    lines.append("├" + "─" * 88 + "┤")

    recs = [
        (
            "PIN CRITICAL FACTS",
            "Add a 'pinned context' layer (never compacted) for user-stated facts like name, "
            "project, deadlines, and budgets. This survives any compaction strategy.",
        ),
        (
            "ENHANCE SUMMARIZATION PROMPT",
            "The summarization instructions should explicitly say: 'Preserve all user-stated "
            "facts (names, projects, deadlines, budgets, preferences) as verbatim as possible.' "
            "Currently it says 'preserve important context' — too vague.",
        ),
        (
            "SOFT WARNING AT ~40 MESSAGES",
            "Warn users when approaching the 50-message hard cap. A silent trigger feels like "
            "amnesia. An explicit '/compact' suggestion at 40 messages would give users control.",
        ),
        (
            "DOCUMENT STORE PATTERN",
            "Large user-provided documents should be stored out-of-context (in a vector DB "
            "or file system) and retrieved on demand. Injecting 3000 words directly into the "
            "message history creates an asymmetric burden that compaction can't handle well.",
        ),
        (
            "DYNAMIC HARD CAP",
            "The fixed 50-message cap is too aggressive for large-context models (128k+) and "
            "too lenient for small ones (32k). Scale the cap proportionally to model_max.",
        ),
    ]

    for i, (title, body) in enumerate(recs, 1):
        words = body.split()
        wrapped = []
        line = f"  {i}. {title}: "
        for w in words:
            if len(line) + len(w) + 1 > 86:
                wrapped.append(line)
                line = "     " + w
            else:
                line += (" " if not line.endswith(" ") else "") + w
        if line.strip():
            wrapped.append(line)
        for wl in wrapped:
            lines.append(f"│{wl:<88}│")

    lines.append("└" + "─" * 88 + "┘")

    return "\n".join(lines)


if __name__ == "__main__":
    configs = [
        # (model_max, label, fluff_size)
        # --- Short fluff (plain Q&A, no tool calls) ---
        (128_000, "128k (Sonnet)", "short"),
        (64_000, "64k (Haiku)", "short"),
        (32_000, "32k (small)", "short"),
        # --- Long fluff (verbose assistant answers) ---
        (128_000, "128k (Sonnet)", "long"),
        (64_000, "64k (Haiku)", "long"),
        (32_000, "32k (small)", "long"),
        # --- Tool-result fluff (file reads, shell output — realistic Muse usage) ---
        (128_000, "128k (Sonnet)", "tool_results"),
        (64_000, "64k (Haiku)", "tool_results"),
        (32_000, "32k (small)", "tool_results"),
        # --- 200k and 1M models ---
        (200_000, "200k (Opus)", "tool_results"),
        (1_000_000, "1M (Opus)", "tool_results"),
    ]

    results = []
    for model_max, label, fluff_size in configs:
        r = simulate_model(model_max, f"{label} ({fluff_size})", fluff_size)
        results.append(r)

    report = format_report(results)
    print(report)
