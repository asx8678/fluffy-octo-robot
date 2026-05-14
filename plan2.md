# MUSE Debate-Mode Plugin — Revised Implementation Plan

## Executive Summary

This is a **complete redesign** of the original plan.md based on analysis of the actual MUSE codebase. The original plan assumed hooks and capabilities that don't exist. This revision works within MUSE's real architecture.

### Key Changes from Original Plan

| Original Assumption | Reality | Solution |
|---------------------|---------|----------|
| `on_session_start` hook | Does not exist | Use `startup` hook + config check |
| `before_next_turn` hook | Does not exist | Use `pre_tool_call` for checkpoint gating |
| `before_next_token` hook | Does not exist | Not needed — use tool-based checkpoints |
| Pause/resume streaming | Not supported | Tool call naturally pauses generation |
| Mid-turn system message injection | Not supported | Return verdict as tool result |
| Complex state machine | Over-engineered | Simplify to 3 states |

### Core Insight

MUSE's tool execution model already provides natural checkpoints. When the planner calls `request_review`, the generation **stops** waiting for the tool result. We return the verdict as the tool result, and the planner continues based on that. No pause/resume needed.

---

## 0. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        MUSE Agent                                │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────────┐ │
│  │   Planner   │───▶│ request_review│───▶│  Debate Plugin      │ │
│  │   (LLM)     │◀───│   (tool)      │◀───│  (pre_tool_call)    │ │
│  └─────────────┘    └──────────────┘    └─────────────────────┘ │
│                                                │                 │
│                                                ▼                 │
│                                         ┌─────────────┐         │
│                                         │  Reviewer   │         │
│                                         │   (LLM)     │         │
│                                         └─────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

**Flow:**
1. Planner generates reasoning and calls `request_review` tool
2. `pre_tool_call` hook intercepts the call
3. Plugin calls reviewer LLM with the proposal
4. Verdict is returned as the tool result
5. Planner sees verdict and continues/revises

---

## 1. Product Goal (Unchanged)

Build a MUSE CLI plugin where the primary planning model thinks in discrete proposals, voluntarily calls a `request_review` tool at the end of each proposal, blocks until a second verifier model returns a structured verdict, then continues (or revises).

### Success Criteria

- Planner never proceeds past a checkpoint without a verdict
- Reviewer sees the proposal and reasoning summary
- p50 review-call latency under 2s, p95 under 4s
- Zero core MUSE files modified — plugin only

### Non-Goals

- Capturing full thinking trace (would require core changes)
- Mid-stream pause (not supported by MUSE)
- Cryptographic integrity of traces

---

## 2. File Structure

```
code_muse/plugins/debate/
  __init__.py               # Plugin entry
  register_callbacks.py     # Hook registration (MUSE pattern)
  config.py                 # Configuration loader
  state.py                  # Simple session state
  reviewer.py               # Reviewer LLM call
  schemas.py                # Pydantic models
  ui.py                     # Status display
  telemetry.py              # NDJSON logging
  prompts/
    planner_addendum.txt    # System prompt addition
    reviewer_system.txt     # Reviewer instructions
```

**Note:** Removed from original plan:
- `trace_cache.py` — Not feasible without `before_next_token` hook
- `segmenter.py` — Not needed
- `checkpoint_detector.py` — Replaced by `pre_tool_call` hook
- `pause_controller.py` — Not needed (tool calls naturally pause)
- `injector.py` — Verdict returned as tool result
- `tools/request_review.py` — Merged into register_callbacks.py

---

## 3. Data Models (`schemas.py`)

```python
from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["proceed", "revise", "reject"]

@dataclass
class CheckpointRequest:
    """What the planner submits for review."""
    proposal: str           # One sentence: what they intend to do
    reasoning_summary: str  # 2-3 sentences: why
    checkpoint_number: int  # 1-based, auto-incremented per turn

@dataclass
class ReviewVerdict:
    """What the reviewer returns."""
    verdict: Verdict
    confidence: float       # 0.0..1.0
    feedback: str           # Specific, actionable
    required_changes: list[str] = field(default_factory=list)
```

**Removed from original:**
- `TraceSegment` — No trace capture without core changes
- `SegmentStatus` — Simplified state model
- `hash`, `full_trace_ref` — No trace hashing

---

## 4. State Management (`state.py`)

### Simplified State Model

```python
from dataclasses import dataclass, field
from typing import Literal

DebateState = Literal["idle", "reviewing", "done"]

@dataclass
class SessionState:
    """Per-session debate state. Stored in module-level dict keyed by session_id."""
    enabled: bool = False
    state: DebateState = "idle"
    checkpoint_count: int = 0
    max_checkpoints: int = 5
    revise_attempts: dict[str, int] = field(default_factory=dict)  # topic_key -> count
    max_revise_per_topic: int = 3

# Module-level session storage
_sessions: dict[str, SessionState] = {}

def get_session(session_id: str) -> SessionState:
    if session_id not in _sessions:
        _sessions[session_id] = SessionState()
    return _sessions[session_id]

def clear_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
```

**Why simpler:**
- Original had 8 states; we need 3
- No `asyncio.Event` needed — tool call is synchronous from planner's perspective
- No cross-turn state persistence needed

---

## 5. Planner System Prompt (`prompts/planner_addendum.txt`)

Appended to planner's system prompt when debate mode is enabled:

```
You are operating in checkpoint-gated reasoning mode.

Rules:
1. Think step by step, breaking reasoning into complete proposals.
2. After each complete proposal, call the request_review tool.
3. Arguments for request_review:
     - proposal: one sentence stating what you intend to do
     - reasoning_summary: 2-3 sentences explaining why
4. Wait for the tool result before continuing.
5. The tool returns a verdict:
     - verdict="proceed": continue to the next proposal
     - verdict="revise": rewrite incorporating the feedback, then call request_review again
     - verdict="reject": abandon this approach entirely, try something different
6. Maximum 5 checkpoints per turn. After that, finalize with approved proposals.
7. Do not call request_review for partial thoughts — only complete proposals.
```

---

## 6. Tool Registration and Hook (`register_callbacks.py`)

```python
"""Debate Mode plugin — checkpoint-gated reasoning via request_review tool."""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning

from .config import get_debate_config, is_debate_enabled
from .reviewer import call_reviewer
from .schemas import CheckpointRequest, ReviewVerdict
from .state import get_session, SessionState
from .telemetry import log_checkpoint
from .ui import show_reviewing, show_verdict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

def _register_request_review_tool() -> list[dict[str, Any]]:
    """Register the request_review tool."""
    
    async def request_review(proposal: str, reasoning_summary: str) -> str:
        """Submit a proposal for review before proceeding.
        
        Args:
            proposal: One sentence stating what you intend to do.
            reasoning_summary: 2-3 sentences explaining why.
            
        Returns:
            A verdict with feedback. Follow the verdict instructions.
        """
        # This is a no-op — actual work happens in pre_tool_call hook
        # But we need a function for the tool schema
        return "ERROR: request_review should be intercepted by pre_tool_call hook"
    
    def register_func(agent):
        agent.tool(request_review)
    
    return [{"name": "request_review", "register_func": register_func}]


# ---------------------------------------------------------------------------
# Pre-tool-call hook — intercepts request_review
# ---------------------------------------------------------------------------

async def _on_pre_tool_call(
    tool_name: str, 
    tool_args: dict, 
    context: Any = None
) -> dict | str | None:
    """Intercept request_review calls and run the review process."""
    
    if tool_name != "request_review":
        return None
    
    if not is_debate_enabled():
        return None
    
    # Get session state
    from code_muse.messaging import get_session_context
    session_id = get_session_context() or "default"
    state = get_session(session_id)
    
    if not state.enabled:
        return None
    
    # Check checkpoint budget
    if state.checkpoint_count >= state.max_checkpoints:
        return _format_verdict(ReviewVerdict(
            verdict="proceed",
            confidence=1.0,
            feedback="Checkpoint budget exhausted. Finalize with approved proposals.",
        ))
    
    # Build request
    state.checkpoint_count += 1
    request = CheckpointRequest(
        proposal=tool_args.get("proposal", ""),
        reasoning_summary=tool_args.get("reasoning_summary", ""),
        checkpoint_number=state.checkpoint_count,
    )
    
    # Check loop detection
    topic_key = _compute_topic_key(request.proposal)
    attempts = state.revise_attempts.get(topic_key, 0)
    if attempts >= state.max_revise_per_topic:
        log_checkpoint(request, ReviewVerdict(
            verdict="reject",
            confidence=1.0,
            feedback="Maximum revision attempts reached for this topic.",
        ))
        return _format_verdict(ReviewVerdict(
            verdict="reject",
            confidence=1.0,
            feedback="You have revised this proposal too many times. Abandon this approach and try something fundamentally different.",
        ))
    
    # Show UI
    show_reviewing(request.proposal)
    state.state = "reviewing"
    
    # Call reviewer
    config = get_debate_config()
    verdict = await call_reviewer(request, config)
    
    # Update state
    state.state = "idle"
    if verdict.verdict == "revise":
        state.revise_attempts[topic_key] = attempts + 1
    elif verdict.verdict == "proceed":
        state.revise_attempts.pop(topic_key, None)  # Reset on success
    
    # Log and display
    log_checkpoint(request, verdict)
    show_verdict(verdict)
    
    # Return verdict as tool result (this is the key insight!)
    return _format_verdict(verdict)


def _format_verdict(verdict: ReviewVerdict) -> str:
    """Format verdict as a string tool result."""
    lines = [
        f"[REVIEW VERDICT]",
        f"verdict: {verdict.verdict}",
        f"confidence: {verdict.confidence:.2f}",
        f"feedback: {verdict.feedback}",
    ]
    if verdict.required_changes:
        lines.append("required_changes:")
        for change in verdict.required_changes:
            lines.append(f"  - {change}")
    lines.append("")
    lines.append("Instructions:")
    if verdict.verdict == "proceed":
        lines.append("- Continue with your next proposal.")
    elif verdict.verdict == "revise":
        lines.append("- Rewrite your proposal incorporating the required_changes.")
        lines.append("- Then call request_review again with the revised proposal.")
    else:  # reject
        lines.append("- Abandon this approach entirely.")
        lines.append("- Try a fundamentally different solution.")
        lines.append("- Do not re-propose the rejected idea.")
    
    return "\n".join(lines)


def _compute_topic_key(proposal: str) -> str:
    """Compute a stable key for loop detection."""
    import hashlib
    normalized = " ".join(proposal.lower().split())
    return hashlib.sha1(normalized.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Startup hook — inject system prompt addendum
# ---------------------------------------------------------------------------

def _on_load_prompt() -> str | None:
    """Inject debate mode instructions into system prompt."""
    if not is_debate_enabled():
        return None
    
    from pathlib import Path
    prompt_file = Path(__file__).parent / "prompts" / "planner_addendum.txt"
    if prompt_file.exists():
        return prompt_file.read_text()
    return None


# ---------------------------------------------------------------------------
# Custom commands
# ---------------------------------------------------------------------------

def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle /debate commands."""
    if name != "debate":
        return None
    
    parts = command.split()
    sub = parts[1] if len(parts) > 1 else "status"
    
    if sub == "on":
        from code_muse.messaging import get_session_context
        session_id = get_session_context() or "default"
        state = get_session(session_id)
        state.enabled = True
        emit_success("🎭 Debate mode enabled")
        return True
    
    if sub == "off":
        from code_muse.messaging import get_session_context
        session_id = get_session_context() or "default"
        state = get_session(session_id)
        state.enabled = False
        emit_info("🎭 Debate mode disabled")
        return True
    
    if sub == "status":
        from code_muse.messaging import get_session_context
        session_id = get_session_context() or "default"
        state = get_session(session_id)
        status = "enabled" if state.enabled else "disabled"
        emit_info(f"🎭 Debate mode: {status}, checkpoints: {state.checkpoint_count}/{state.max_checkpoints}")
        return True
    
    if sub == "metrics":
        from .telemetry import get_metrics_summary
        emit_info(get_metrics_summary())
        return True
    
    return None


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("debate on", "Enable debate mode (checkpoint-gated reasoning)"),
        ("debate off", "Disable debate mode"),
        ("debate status", "Show current debate mode status"),
        ("debate metrics", "Show review metrics (latency, verdicts)"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("register_tools", _register_request_review_tool)
register_callback("pre_tool_call", _on_pre_tool_call, priority=100)  # High priority
register_callback("load_prompt", _on_load_prompt)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Debate Mode plugin callbacks registered")
```

---

## 7. Reviewer (`reviewer.py`)

```python
"""Reviewer LLM call — validates proposals and returns verdicts."""

import json
import logging
import re
from typing import Any

from .schemas import CheckpointRequest, ReviewVerdict

logger = logging.getLogger(__name__)

REVIEWER_SYSTEM_PROMPT = """You are a senior code and logic reviewer. You receive a proposal and reasoning summary from a planning agent.

Task: Verify correctness, security, performance, and completeness.

Respond ONLY with a JSON object:
{
  "verdict": "proceed" | "revise" | "reject",
  "confidence": 0.0 to 1.0,
  "feedback": "specific, actionable feedback",
  "required_changes": ["change 1", "change 2"]  // empty if verdict is proceed
}

Rules:
- verdict="proceed" if the proposal is sound
- verdict="revise" if there are fixable flaws (populate required_changes)
- verdict="reject" if fundamentally wrong
- Be concise. No praise. No restating the proposal.
"""


async def call_reviewer(
    request: CheckpointRequest,
    config: dict[str, Any],
) -> ReviewVerdict:
    """Call the reviewer LLM and parse the response."""
    
    timeout_s = config.get("timeout_ms", 4000) / 1000.0
    reviewer_model = config.get("reviewer_model")
    
    user_prompt = f"""Checkpoint #{request.checkpoint_number}

Proposal: {request.proposal}

Reasoning: {request.reasoning_summary}

Provide your verdict as JSON."""

    try:
        from pydantic_ai import Agent as PydanticAgent
        from code_muse.config import get_global_model_name
        from code_muse.model_factory import ModelFactory, make_model_settings
        
        model_name = reviewer_model or get_global_model_name()
        if not model_name:
            return _fallback_verdict("No model available")
        
        models_config = ModelFactory.load_config()
        if model_name not in models_config:
            return _fallback_verdict(f"Model '{model_name}' not found")
        
        model = ModelFactory.get_model(model_name, models_config)
        if model is None:
            return _fallback_verdict("Could not create model instance")
        
        model_settings = make_model_settings(model_name)
        
        review_agent = PydanticAgent(
            model=model,
            instructions=REVIEWER_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
            model_settings=model_settings,
        )
        
        import asyncio
        result = await asyncio.wait_for(
            review_agent.run(user_prompt, message_history=[]),
            timeout=timeout_s,
        )
        
        text = result.data if hasattr(result, "data") else str(result)
        return _parse_verdict(text)
        
    except asyncio.TimeoutError:
        logger.warning("Reviewer timed out after %.1fs", timeout_s)
        return _fallback_verdict("Reviewer timed out", proceed=True)
    except Exception as exc:
        logger.error("Reviewer call failed: %s", exc, exc_info=True)
        return _fallback_verdict(str(exc), proceed=True)


def _parse_verdict(text: str) -> ReviewVerdict:
    """Parse JSON verdict from reviewer response."""
    try:
        # Find JSON in response
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                return ReviewVerdict(
                    verdict=data.get("verdict", "proceed"),
                    confidence=float(data.get("confidence", 0.5)),
                    feedback=data.get("feedback", ""),
                    required_changes=data.get("required_changes", []),
                )
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Failed to parse verdict JSON: %s", exc)
    
    # Heuristic fallback
    text_lower = text.lower()
    if "reject" in text_lower:
        return ReviewVerdict(
            verdict="reject",
            confidence=0.5,
            feedback=text[:200],
        )
    if "revise" in text_lower or "change" in text_lower:
        return ReviewVerdict(
            verdict="revise",
            confidence=0.5,
            feedback=text[:200],
            required_changes=["See feedback"],
        )
    return ReviewVerdict(
        verdict="proceed",
        confidence=0.5,
        feedback=text[:200] if text else "Approved",
    )


def _fallback_verdict(reason: str, proceed: bool = False) -> ReviewVerdict:
    """Return a fallback verdict when reviewer fails."""
    return ReviewVerdict(
        verdict="proceed" if proceed else "revise",
        confidence=0.3,
        feedback=f"⚠️ Reviewer unavailable: {reason}. Proceeding with caution.",
    )
```

---

## 8. Configuration (`config.py`)

```python
"""Configuration for Debate Mode plugin."""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_config_cache: dict[str, Any] | None = None


def get_debate_config() -> dict[str, Any]:
    """Load debate_mode config from extra_models.json."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    
    defaults = {
        "enabled": False,
        "reviewer_model": None,  # Uses global model if not set
        "timeout_ms": 4000,
        "max_checkpoints_per_turn": 5,
        "max_revise_attempts_per_topic": 3,
        "telemetry": {
            "enabled": True,
            "path": "~/.muse/telemetry/debate_checkpoints.ndjson",
        },
    }
    
    try:
        config_path = Path.home() / ".muse" / "extra_models.json"
        if config_path.exists():
            import json
            with open(config_path) as f:
                data = json.load(f)
            if "debate_mode" in data:
                defaults.update(data["debate_mode"])
    except Exception as exc:
        logger.warning("Failed to load debate_mode config: %s", exc)
    
    _config_cache = defaults
    return defaults


def is_debate_enabled() -> bool:
    """Check if debate mode is enabled globally."""
    return get_debate_config().get("enabled", False)
```

---

## 9. UI (`ui.py`)

```python
"""UI feedback for debate mode."""

from code_muse.messaging import emit_info, emit_success, emit_warning

from .schemas import ReviewVerdict


def show_reviewing(proposal: str) -> None:
    """Show that a review is in progress."""
    truncated = proposal[:60] + "..." if len(proposal) > 60 else proposal
    emit_info(f"⏸️  Reviewing: \"{truncated}\"")


def show_verdict(verdict: ReviewVerdict) -> None:
    """Show the review verdict."""
    if verdict.verdict == "proceed":
        emit_success(f"✅ PROCEED — {verdict.feedback[:100]}")
    elif verdict.verdict == "revise":
        changes = ", ".join(verdict.required_changes[:3]) if verdict.required_changes else verdict.feedback[:100]
        emit_warning(f"🔄 REVISE — {changes}")
    else:
        emit_warning(f"❌ REJECT — {verdict.feedback[:100]}")
```

---

## 10. Telemetry (`telemetry.py`)

```python
"""NDJSON telemetry for debate checkpoints."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import get_debate_config
from .schemas import CheckpointRequest, ReviewVerdict

logger = logging.getLogger(__name__)


def log_checkpoint(request: CheckpointRequest, verdict: ReviewVerdict) -> None:
    """Log a checkpoint to the telemetry file."""
    config = get_debate_config()
    if not config.get("telemetry", {}).get("enabled", True):
        return
    
    path = Path(config.get("telemetry", {}).get("path", "~/.muse/telemetry/debate_checkpoints.ndjson"))
    path = path.expanduser()
    
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "checkpoint": request.checkpoint_number,
            "proposal": request.proposal[:200],
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
        }
        
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")
            
    except Exception as exc:
        logger.debug("Failed to write telemetry: %s", exc)


def get_metrics_summary() -> str:
    """Get a summary of recent metrics."""
    config = get_debate_config()
    path = Path(config.get("telemetry", {}).get("path", "~/.muse/telemetry/debate_checkpoints.ndjson"))
    path = path.expanduser()
    
    if not path.exists():
        return "No telemetry data yet."
    
    try:
        records = []
        with open(path) as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        
        if not records:
            return "No telemetry data yet."
        
        # Last 50 records
        recent = records[-50:]
        
        verdicts = {"proceed": 0, "revise": 0, "reject": 0}
        for r in recent:
            v = r.get("verdict", "proceed")
            verdicts[v] = verdicts.get(v, 0) + 1
        
        total = len(recent)
        return (
            f"Last {total} checkpoints: "
            f"proceed={verdicts['proceed']} ({100*verdicts['proceed']/total:.0f}%), "
            f"revise={verdicts['revise']} ({100*verdicts['revise']/total:.0f}%), "
            f"reject={verdicts['reject']} ({100*verdicts['reject']/total:.0f}%)"
        )
        
    except Exception as exc:
        return f"Error reading telemetry: {exc}"
```

---

## 11. Implementation Phases

### Phase A — Scaffolding (Day 1)
1. Create plugin folder structure
2. Implement `config.py` with defaults
3. Implement `schemas.py` dataclasses
4. Implement `state.py` session management

### Phase B — Core Hook (Day 2)
5. Implement `register_callbacks.py` with tool registration
6. Implement `_on_pre_tool_call` hook (the core logic)
7. Test tool interception with mock reviewer

### Phase C — Reviewer (Day 3)
8. Implement `reviewer.py` with LLM call
9. Add timeout handling and fallback verdicts
10. Test with real reviewer model

### Phase D — Polish (Day 4)
11. Implement `ui.py` status display
12. Implement `telemetry.py` logging
13. Add `/debate` slash commands
14. Create `prompts/planner_addendum.txt`

### Phase E — Testing (Day 5)
15. Unit tests for state management
16. Unit tests for verdict parsing
17. Integration test with mock LLM
18. End-to-end test with real models

---

## 12. Testing Plan

### Unit Tests

```python
# test_state.py
def test_session_isolation():
    """Sessions don't leak state."""
    
def test_checkpoint_budget():
    """Checkpoints stop at max."""
    
def test_loop_detection():
    """Same topic triggers reject after N attempts."""

# test_reviewer.py
def test_parse_valid_json():
    """Valid JSON parses correctly."""
    
def test_parse_malformed_json():
    """Malformed JSON falls back gracefully."""
    
def test_timeout_fallback():
    """Timeout returns proceed_with_warning."""

# test_hook.py
def test_non_request_review_passthrough():
    """Other tools are not intercepted."""
    
def test_disabled_mode_passthrough():
    """Disabled mode doesn't intercept."""
    
def test_verdict_formatting():
    """Verdict formats correctly as tool result."""
```

### Integration Tests

```python
# test_integration.py
async def test_full_review_cycle():
    """Planner → request_review → reviewer → verdict → planner."""
    
async def test_revise_loop():
    """Revise verdict triggers re-review."""
    
async def test_reject_forces_new_approach():
    """Reject verdict blocks same topic."""
```

---

## 13. Configuration Example

Add to `~/.muse/extra_models.json`:

```json
{
  "debate_mode": {
    "enabled": true,
    "reviewer_model": "claude-3-5-sonnet",
    "timeout_ms": 4000,
    "max_checkpoints_per_turn": 5,
    "max_revise_attempts_per_topic": 3,
    "telemetry": {
      "enabled": true,
      "path": "~/.muse/telemetry/debate_checkpoints.ndjson"
    }
  }
}
```

---

## 14. What Was Removed and Why

| Original Component | Why Removed |
|--------------------|-------------|
| `trace_cache.py` | Requires `before_next_token` hook that doesn't exist |
| `segmenter.py` | No token-level access to segment |
| `pause_controller.py` | Tool calls naturally pause; no explicit pause needed |
| `injector.py` | Verdict returned as tool result instead |
| `manifest.json` | MUSE uses `register_callbacks.py` pattern, not manifests |
| 8-state machine | Simplified to 3 states (idle/reviewing/done) |
| `cooperative` pause strategy | Not supported by any MUSE-compatible runtime |
| SHA1 trace hashing | No traces to hash |
| `before_next_turn` hook | Doesn't exist; not needed with tool-based approach |
| `on_session_start` hook | Use `startup` + config check instead |

---

## 15. Future Enhancements (Post-v1)

If MUSE core adds these hooks, the plugin could be enhanced:

1. **`before_next_token` hook** → Enable full trace capture
2. **`on_session_start` hook** → Per-session initialization
3. **Streaming pause/resume** → True mid-stream checkpoints
4. **Message history injection** → Richer verdict context

For now, the tool-based approach provides 80% of the value with 20% of the complexity.

---

## 16. Summary

This revised plan:
- Works with MUSE's actual hook architecture
- Uses the natural pause point of tool execution
- Returns verdicts as tool results (no injection needed)
- Simplifies state management significantly
- Can be implemented in ~5 days
- Requires zero core MUSE changes

The key insight is that **tool calls are already checkpoints**. When the planner calls `request_review`, generation stops waiting for the result. We intercept via `pre_tool_call`, run the review, and return the verdict as the tool result. The planner sees the verdict and continues accordingly.
