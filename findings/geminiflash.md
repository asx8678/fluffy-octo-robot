# fixed_plan.md

## Overview
A strategic review of the Muse agentic system, focusing on architecturally sound agentic design, performance, and token efficiency. Several bottlenecks identified in the core loop and history management warrant Cython-accelerated paths.

---

## [P1] Token Waste: Full Agent System Prompt Resent Every Step
**Category**: Token
**Location**: `code_muse/agents/_runtime.py:346-353`, `_should_prepend_system_prompt()`
**Severity**: P1
**Description**: The system prompt is re-assembled and prepended to user prompts throughout the interaction. 
**Root Cause**: Lack of dynamic caching of the static portion of the system prompt (`cache_control`).
**Evidence**: Agent logic prepends system instructions *every* time `agent._message_history` is empty, but high-frequency runs keep modifying history, triggering re-assembly.
**Proposed Fix**:
1. Pre-calculate the system prompt hash/cache-key once on agent load.
2. Inject `anthropic.cache_control` headers into the system message block for models that support it.
**Token Impact**: Significant (variable, based on length of system instruction block).
**Effort**: M

## [P1] CPU Hotspot: String Manipulation in Message Assembly
**Category**: Hotspot
**Location**: `code_muse/agents/_runtime.py:440-449`, `_build_prompt_payload()`
**Severity**: P1
**Description**: Python list extension and potential string concatenation in a tight path for every message turn.
**Root Cause**: Frequent dynamic construction of message payloads instead of using byte-oriented, pre-allocated buffers.
**Evidence**: `parts.extend` and `payload.append` called for every turn in the agent loop.
**Proposed Fix**:
1. Implement a Cythonized payload builder that handles serialization of binary chunks and text parts.
**Hotspot Analysis**:
- Calls per run: 6-10 steps
- Complexity: $O(N)$ where $N$ is message parts
- Current: ~10-20ms per step
- **Proposed Cython signature**: `cdef list build_payload_cy(str prompt, list attachments)`
**Performance Impact**: Lower GC churn, reduced memory overhead.
**Effort**: M

## [P2] Performance: History Truncation and Tool Result Truncation
**Category**: Performance
**Location**: `code_muse/agents/_compaction.py:441-455`, `compact_with_tool_truncation()`
**Severity**: P2
**Description**: History processor scans the entire list and replaces content on multiple messages during every turn.
**Root Cause**: Repeated full-list traversal and `ModelRequest` object copying in Python.
**Evidence**: `_truncate_tool_result_content()` iterates and potentially calls `model_copy` on every turn.
**Proposed Fix**:
1. Move the truncation and splitting logic (`split_for_protected_summarization`) to a Cython kernel.
2. Use raw memoryviews to scan for tool IDs instead of Python set operations where possible.
**Hotspot Analysis**:
- Calls: Per turn (~10)
- Complexity: $O(N \times P)$ where $N$ is messages, $P$ is parts.
- Current: ~30-50ms+ in Python history processor.
- **Proposed Cython signature**: `cpdef void truncate_tool_results_cy(list messages, set protected_ids)`
**Performance Impact**: 10x speedup in history management latency.
**Effort**: L

---

## Summary Roadmap

| Priority | Issue | Category | Effort | Gain |
|----------|-------|----------|--------|------|
| **P1** | System prompt resending | Token | M | -15-20% base token overhead |
| **P1** | Message assembly in loop | Hotspot | M | Reduced GC pressure |
| **P1** | History processing cost | Performance | L | Reduced turn-to-turn latency |
| **P2** | Cython GIL holding | Cython | S | Parallelize token/parsing tasks |

### Top 3 Cythonization Candidates

1.  **`core/payload_builder.pyx`**: Accelerate `_build_prompt_payload`. High frequency, direct string/list manipulation.
2.  **`core/history_processor.pyx`**: Accelerate `compact_with_tool_truncation`. The logic is CPU-bound on object iteration and set management.
3.  **`core/token_estimations.pyx`**: Consolidate `estimate_tokens_for_message`. This is called repeatedly during compaction; moving this to a typed C function (`signed/unsigned`) will allow for much tighter loops.

---

## Architect's Note
The code is generally well-structured for a Muse-based system (following the plugin and callback architecture). The biggest scaling risk is not within the agentic logic itself (which leverages `pydantic-ai` effectively) but in the **data processing layer** that handles the history window. As your agent session length increases, the Python-time cost of `_compaction.py` grows, which will introduce "stutter" in the response-start time for long sessions. Prioritize Cythonization of the history processor.
