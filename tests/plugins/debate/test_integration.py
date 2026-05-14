"""Integration tests for the Debate Mode plugin.

End-to-end workflow: planner → request_review → reviewer → verdict → planner.
Edge cases: reviewer timeouts, invalid responses, budget exhaustion, loop detection.
Performance benchmark: p50 <2s, p95 <4s.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_muse.plugins.debate.config import (
    is_debate_enabled,
    set_debate_enabled,
)
from code_muse.plugins.debate.register_callbacks import (
    _on_agent_run_end,
    _on_agent_run_start,
    _on_custom_command,
    _on_custom_command_help,
    _on_load_prompt,
    _on_pre_tool_call,
    _on_stream_event,
    _register_debate_tools,
)
from code_muse.plugins.debate.schemas import (
    Issue,
    ReviewRequest,
    ReviewResponse,
    Verdict,
    VerdictKind,
)
from code_muse.plugins.debate.state import DebateState
from code_muse.plugins.debate.telemetry import (
    get_session_stats,
    get_success_rate,
    get_verdict_breakdown,
    record_review_latency,
    reset_telemetry,
)


@pytest.fixture(autouse=True)
def _reset():
    """Ensure clean debate state and telemetry for every test."""
    DebateState.reset()
    reset_telemetry()
    set_debate_enabled(True)
    yield
    DebateState.reset()
    reset_telemetry()
    set_debate_enabled(True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_verdict(
    kind: VerdictKind = VerdictKind.APPROVE,
    summary: str = "Looks good",
    confidence: float = 0.9,
    issues: list[Issue] | None = None,
) -> Verdict:
    """Build a Verdict for test assertions."""
    return Verdict(
        kind=kind,
        summary=summary,
        issues=issues or [],
        confidence=confidence,
    )


def _make_response(
    kind: VerdictKind = VerdictKind.APPROVE,
    summary: str = "Looks good",
    confidence: float = 0.9,
    review_count: int = 1,
    remaining_budget: int = 19,
) -> ReviewResponse:
    """Build a ReviewResponse for mock return values."""
    return ReviewResponse(
        verdict=_make_verdict(kind, summary, confidence),
        review_count=review_count,
        remaining_budget=remaining_budget,
    )


# ---------------------------------------------------------------------------
# E2E: Full workflow — planner → request_review → verdict → continue
# ---------------------------------------------------------------------------


class TestEndToEndWorkflow:
    """Full integration: the request_review tool calls the reviewer and
    returns a structured verdict that the planner can act on."""

    @pytest.mark.asyncio
    async def test_approve_workflow(self):
        """Planner submits proposal → reviewer approves → planner continues."""
        mock_response = _make_response(
            VerdictKind.APPROVE, "Implementation is solid", 0.95
        )

        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            tools = _register_debate_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "request_review"

            # Simulate the tool being called
            register_func = tools[0]["register_func"]
            mock_agent = MagicMock()
            captured_tool = None

            def capture_tool(func):
                nonlocal captured_tool
                captured_tool = func
                return func

            mock_agent.tool = capture_tool
            register_func(mock_agent)
            assert captured_tool is not None

            # Execute the tool
            mock_context = MagicMock()
            result = await captured_tool(
                mock_context,
                proposal="Refactor auth module to use JWT",
                reasoning_summary="Current session approach has security issues",
                checkpoint=1,
            )

            # Verify the returned structure
            assert result["verdict"]["kind"] == "approve"
            assert result["verdict"]["summary"] == "Implementation is solid"
            assert result["verdict"]["confidence"] == 0.95
            assert result["review_count"] == 1
            assert result["remaining_budget"] == 19

            # Verify state was updated
            assert DebateState.review_count() == 1
            assert DebateState.remaining_budget() == 19
            assert DebateState.consecutive_revisions() == 0

    @pytest.mark.asyncio
    async def test_revise_workflow(self):
        """Planner submits → reviewer says revise → planner must address issues."""
        issues = [
            Issue(
                severity="critical",
                message="SQL injection vulnerability",
                suggestion="Use parameterized queries",
            ),
            Issue(
                severity="warning",
                message="Missing error handling",
                suggestion="Add try/except blocks",
            ),
        ]
        mock_response = ReviewResponse(
            verdict=Verdict(
                kind=VerdictKind.REVISE,
                summary="Critical security issue found",
                issues=issues,
                confidence=0.85,
            ),
            review_count=1,
            remaining_budget=19,
        )

        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            tools = _register_debate_tools()
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()
            result = await captured_tool(
                mock_context,
                proposal="Add raw SQL query",
                checkpoint=1,
            )

            assert result["verdict"]["kind"] == "revise"
            assert len(result["verdict"]["issues"]) == 2
            assert result["verdict"]["issues"][0]["severity"] == "critical"
            assert result["verdict"]["issues"][0]["suggestion"] == (
                "Use parameterized queries"
            )

            # Loop detection should track consecutive revisions
            assert DebateState.consecutive_revisions() == 1

    @pytest.mark.asyncio
    async def test_reject_workflow(self):
        """Reviewer rejects → planner must completely rethink approach."""
        mock_response = _make_response(
            VerdictKind.REJECT, "Approach is fundamentally flawed", 0.7
        )

        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            tools = _register_debate_tools()
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()
            result = await captured_tool(
                mock_context,
                proposal="Delete the database",
                checkpoint=1,
            )

            assert result["verdict"]["kind"] == "reject"
            assert DebateState.consecutive_revisions() == 0  # reject resets

    @pytest.mark.asyncio
    async def test_multi_checkpoint_workflow(self):
        """Simulate a realistic session: 3 checkpoints, each reviewed."""
        responses = [
            _make_response(VerdictKind.APPROVE, "Good start", 0.9, 1, 19),
            _make_response(VerdictKind.REVISE, "Fix edge case", 0.8, 2, 18),
            _make_response(VerdictKind.APPROVE, "Edge case fixed", 0.95, 3, 17),
        ]

        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            tools = _register_debate_tools()
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()

            # Checkpoint 1: approve
            r1 = await captured_tool(mock_context, "Phase 1 plan", checkpoint=1)
            assert r1["verdict"]["kind"] == "approve"
            assert r1["review_count"] == 1

            # Checkpoint 2: revise
            r2 = await captured_tool(
                mock_context,
                "Phase 2 plan",
                reasoning_summary="Added edge case handling",
                checkpoint=2,
            )
            assert r2["verdict"]["kind"] == "revise"
            assert r2["review_count"] == 2

            # Checkpoint 3: approve (after revision)
            r3 = await captured_tool(mock_context, "Phase 2 revised", checkpoint=2)
            assert r3["verdict"]["kind"] == "approve"
            assert r3["review_count"] == 3
            assert r3["remaining_budget"] == 17

            # Verify full history
            history = DebateState.review_history()
            assert len(history) == 3
            assert history[0]["verdict"] == "approve"
            assert history[1]["verdict"] == "revise"
            assert history[2]["verdict"] == "approve"


# ---------------------------------------------------------------------------
# Edge cases: reviewer failures, invalid responses, budget, loops
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: reviewer unavailable, invalid JSON, budget exhaustion,
    loop detection, and disabled mode."""

    @pytest.mark.asyncio
    async def test_reviewer_returns_none_fallback(self):
        """When the reviewer LLM is unreachable, a fallback approve is
        returned so the planner isn't stuck."""

        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=None,
        ):
            tools = _register_debate_tools()
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()
            result = await captured_tool(mock_context, "Some proposal", checkpoint=1)

            # Fallback approve so planner can continue
            assert result["verdict"]["kind"] == "approve"
            assert "unavailable" in result["verdict"]["summary"].lower() or (
                "proceeding" in result["verdict"]["summary"].lower()
            )

    @pytest.mark.asyncio
    async def test_reviewer_timeout_fallback(self):
        """When the reviewer call times out (raises exception), fallback."""
        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            side_effect=TimeoutError("Reviewer timed out after 30s"),
        ):
            tools = _register_debate_tools()
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()
            # The tool should propagate the exception — this is correct
            # behaviour because the planner's framework handles retries.
            with pytest.raises(TimeoutError):
                await captured_tool(mock_context, "Some proposal", checkpoint=1)

    @pytest.mark.asyncio
    async def test_budget_exhaustion_blocks_tool(self):
        """When the review budget is exhausted, pre_tool_call blocks the call."""
        # Exhaust budget: 20 reviews (default max)
        for i in range(20):
            DebateState.record_review(i + 1, VerdictKind.APPROVE)

        result = await _on_pre_tool_call("request_review", {"proposal": "x"})
        assert result == {"blocked": True}

        # Other tools still pass through
        result = await _on_pre_tool_call("create_file", {"path": "/tmp/x"})
        assert result is None

    @pytest.mark.asyncio
    async def test_loop_detection_blocks_tool(self):
        """When consecutive revisions exceed the loop threshold, the call is blocked."""
        # 3 consecutive revisions (default max_loops)
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)

        result = await _on_pre_tool_call("request_review", {"proposal": "x"})
        assert result == {"blocked": True}

    @pytest.mark.asyncio
    async def test_approve_breaks_loop_detection(self):
        """An approve verdict resets the consecutive-revision counter."""
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        # Approve breaks the chain
        DebateState.record_review(2, VerdictKind.APPROVE)
        # Now consecutive_revisions should be 0
        assert DebateState.consecutive_revisions() == 0
        result = await _on_pre_tool_call("request_review", {"proposal": "x"})
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_resets_loop_counter(self):
        """A reject verdict also resets the consecutive-revision counter."""
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REJECT)
        assert DebateState.consecutive_revisions() == 0

    @pytest.mark.asyncio
    async def test_disabled_mode_returns_fallback(self):
        """When debate mode is disabled, request_review returns a quick fallback."""
        set_debate_enabled(False)

        tools = _register_debate_tools()
        mock_agent = MagicMock()
        captured_tool = None

        def capture(fn):
            nonlocal captured_tool
            captured_tool = fn
            return fn

        mock_agent.tool = capture
        tools[0]["register_func"](mock_agent)

        mock_context = MagicMock()
        result = await captured_tool(mock_context, "Proposal", checkpoint=1)

        assert result["verdict"]["kind"] == "approve"
        assert "disabled" in result["verdict"]["summary"].lower()

        # No state should have been updated (debate is off)
        assert DebateState.review_count() == 0

    @pytest.mark.asyncio
    async def test_disabled_pre_tool_call_passes_through(self):
        """When debate mode is disabled, pre_tool_call doesn't block."""
        set_debate_enabled(False)
        # Even with exhausted budget, no blocking when disabled
        for i in range(20):
            DebateState.record_review(i + 1, VerdictKind.APPROVE)

        result = await _on_pre_tool_call("request_review", {"proposal": "x"})
        assert result is None

    @pytest.mark.asyncio
    async def test_load_prompt_disabled(self):
        """When debate mode is disabled, load_prompt returns None."""
        set_debate_enabled(False)
        result = _on_load_prompt()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_prompt_enabled(self):
        """When debate mode is enabled, load_prompt returns the addendum."""
        result = _on_load_prompt()
        assert result is not None
        assert "request_review" in result
        assert "checkpoint" in result


# ---------------------------------------------------------------------------
# Stream event hook
# ---------------------------------------------------------------------------


class TestStreamEventHook:
    """Verify the stream_event hook renders inline review indicators."""

    def test_part_start_request_review(self):
        """When a request_review ToolCallPart starts, emit an indicator."""
        # Mock a part object with tool_name attribute
        mock_part = MagicMock()
        mock_part.tool_name = "request_review"

        event_data = {
            "index": 5,
            "part_type": "ToolCallPart",
            "part": mock_part,
        }

        # Should not raise
        _on_stream_event("part_start", event_data, "session-1")

    def test_part_start_other_tool_ignored(self):
        """Other tool calls should not trigger the indicator."""
        mock_part = MagicMock()
        mock_part.tool_name = "create_file"

        event_data = {
            "index": 5,
            "part_type": "ToolCallPart",
            "part": mock_part,
        }

        # Should not raise, and no pending index added
        _on_stream_event("part_start", event_data, "session-1")

    def test_part_end_clears_pending(self):
        """Part end for a tracked index should clean up."""
        mock_part = MagicMock()
        mock_part.tool_name = "request_review"

        # Add to pending
        _on_stream_event(
            "part_start",
            {"index": 7, "part_type": "ToolCallPart", "part": mock_part},
            "session-1",
        )
        # Clear on part_end
        _on_stream_event(
            "part_end",
            {"index": 7, "part_type": "ToolCallPart"},
            "session-1",
        )

    def test_disabled_skips_all(self):
        """When debate is disabled, stream events are ignored."""
        set_debate_enabled(False)
        mock_part = MagicMock()
        mock_part.tool_name = "request_review"

        # Should not raise or track
        _on_stream_event(
            "part_start",
            {"index": 1, "part_type": "ToolCallPart", "part": mock_part},
            "session-1",
        )

    def test_text_part_ignored(self):
        """Text parts should not trigger the indicator."""
        event_data = {
            "index": 3,
            "part_type": "TextPart",
            "part": MagicMock(),
        }
        _on_stream_event("part_start", event_data, "session-1")


# ---------------------------------------------------------------------------
# Agent lifecycle integration
# ---------------------------------------------------------------------------


class TestAgentLifecycleIntegration:
    """Verify the agent-run hooks correctly track active state."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Agent starts → reviews happen → agent ends → state clean."""
        # Start
        await _on_agent_run_start("muse", "claude-3.5-sonnet", "s1")
        assert DebateState.is_active()
        assert DebateState.agent_name() == "muse"

        # Reviews happen
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 100.0)
        assert DebateState.review_count() == 1

        # End
        await _on_agent_run_end("muse", "claude-3.5-sonnet", "s1", success=True)
        assert not DebateState.is_active()
        # But review count persists
        assert DebateState.review_count() == 1

    @pytest.mark.asyncio
    async def test_multiple_agents(self):
        """Only the matching agent clears the active state on end."""
        await _on_agent_run_start("muse", "claude-3.5-sonnet", "s1")
        await _on_agent_run_end("code-critic", "gpt-4o", "s2", success=True)
        assert DebateState.is_active()
        assert DebateState.agent_name() == "muse"


# ---------------------------------------------------------------------------
# Telemetry integration
# ---------------------------------------------------------------------------


class TestTelemetryIntegration:
    """Verify telemetry is recorded during the full review workflow."""

    @pytest.mark.asyncio
    async def test_telemetry_records_on_review(self):
        """A successful review should update all telemetry counters."""
        mock_response = _make_response(VerdictKind.APPROVE, "OK", 0.9)

        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            tools = _register_debate_tools()
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()
            await captured_tool(mock_context, "Proposal", checkpoint=1)

        # Telemetry should reflect the review
        stats = get_session_stats()
        assert stats["total_reviews"] == 1
        assert stats["success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_verdict_distribution_across_reviews(self):
        """Multiple reviews should produce correct verdict distribution."""
        mock_responses = [
            _make_response(VerdictKind.APPROVE, "OK", 0.9),
            _make_response(VerdictKind.REVISE, "Fix", 0.7),
            _make_response(VerdictKind.REJECT, "Bad", 0.6),
        ]

        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            side_effect=mock_responses,
        ):
            tools = _register_debate_tools()
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()
            for i in range(3):
                await captured_tool(mock_context, f"Proposal {i}", checkpoint=i + 1)

        breakdown = get_verdict_breakdown()
        assert breakdown["approve"] == 1
        assert breakdown["revise"] == 1
        assert breakdown["reject"] == 1

        # Success rate = approve / total = 1/3
        rate = get_success_rate()
        assert rate == pytest.approx(1 / 3, abs=0.01)


# ---------------------------------------------------------------------------
# Slash command integration
# ---------------------------------------------------------------------------


class TestSlashCommandIntegration:
    """Verify /debate commands correctly manage state and telemetry."""

    @pytest.mark.asyncio
    async def test_reset_clears_everything(self):
        """'/debate reset' should clear all state and telemetry."""
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 100.0)
        start = time.monotonic() - 0.1
        record_review_latency(start, VerdictKind.APPROVE)

        assert DebateState.review_count() == 1
        assert get_session_stats()["total_reviews"] == 1

        result = _on_custom_command("/debate reset", "debate")
        assert result is True

        assert DebateState.review_count() == 0
        assert get_session_stats()["total_reviews"] == 0

    @pytest.mark.asyncio
    async def test_toggle_integration(self):
        """Toggle should flip the enabled state and persist."""
        assert is_debate_enabled() is True
        _on_custom_command("/debate toggle", "debate")
        assert is_debate_enabled() is False
        _on_custom_command("/debate toggle", "debate")
        assert is_debate_enabled() is True

    @pytest.mark.asyncio
    async def test_status_with_active_agent(self):
        """Status should display agent info when active."""
        await _on_agent_run_start("muse", "claude-3.5-sonnet", "s1")
        result = _on_custom_command("/debate status", "debate")
        assert result is True
        await _on_agent_run_end("muse", "claude-3.5-sonnet", "s1", success=True)

    @pytest.mark.asyncio
    async def test_history_displays_reviews(self):
        """History command should list all recorded reviews."""
        DebateState.record_review(1, VerdictKind.APPROVE, "First review", 100.0)
        DebateState.record_review(2, VerdictKind.REVISE, "Needs work", 200.0)

        result = _on_custom_command("/debate history", "debate")
        assert result is True


# ---------------------------------------------------------------------------
# Performance benchmark
# ---------------------------------------------------------------------------


class TestPerformanceBenchmark:
    """Verify review-call latency meets the p50 <2s, p95 <4s requirement.

    Since we cannot call the real LLM in tests, we benchmark the overhead
    of the request_review tool function itself (excluding LLM time).
    This ensures the plugin framework doesn't add unacceptable latency.
    """

    @pytest.mark.asyncio
    async def test_tool_overhead_under_50ms(self):
        """The request_review tool function (excluding LLM call) should
        complete in under 50ms overhead."""
        mock_response = _make_response(VerdictKind.APPROVE, "OK", 0.9)

        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            tools = _register_debate_tools()
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()

            # Warm up
            await captured_tool(mock_context, "Warmup", checkpoint=1)
            DebateState.reset()
            reset_telemetry()

            # Benchmark 10 calls
            latencies = []
            for i in range(10):
                start = time.monotonic()
                await captured_tool(mock_context, f"Proposal {i}", checkpoint=i + 1)
                elapsed_ms = (time.monotonic() - start) * 1000
                latencies.append(elapsed_ms)

            latencies.sort()
            p50 = latencies[5]
            p95 = latencies[9]  # With 10 samples, max ≈ p95

            # Plugin overhead should be negligible
            assert p50 < 50, f"p50 tool overhead {p50:.1f}ms exceeds 50ms"
            assert p95 < 100, f"p95 tool overhead {p95:.1f}ms exceeds 100ms"

    def test_state_operations_under_1ms(self):
        """State operations (record_review, is_budget_exhausted, etc.)
        should each complete in under 1ms."""
        latencies = []

        for i in range(100):
            start = time.monotonic()
            DebateState.record_review(i + 1, VerdictKind.APPROVE, "OK", 100.0)
            elapsed_us = (time.monotonic() - start) * 1_000_000  # microseconds
            latencies.append(elapsed_us)

        avg_us = sum(latencies) / len(latencies)
        max_us = max(latencies)

        assert avg_us < 500, f"Average state op {avg_us:.0f}μs exceeds 500μs"
        assert max_us < 5000, f"Max state op {max_us:.0f}μs exceeds 5ms"

    def test_telemetry_recording_under_5ms(self):
        """Telemetry recording (including NDJSON append) should be fast."""
        latencies = []

        for _i in range(50):
            start = time.monotonic()
            start_time = time.monotonic() - 0.01
            record_review_latency(start_time, VerdictKind.APPROVE)
            elapsed_ms = (time.monotonic() - start) * 1000
            latencies.append(elapsed_ms)

        latencies.sort()
        p50 = latencies[25]
        p95 = latencies[47]

        # Even with file I/O, should be fast
        assert p50 < 5, f"p50 telemetry write {p50:.1f}ms exceeds 5ms"
        assert p95 < 20, f"p95 telemetry write {p95:.1f}ms exceeds 20ms"

    def test_ui_rendering_under_1ms(self):
        """UI rendering functions should be sub-millisecond."""
        from code_muse.plugins.debate.ui import (
            render_progress_bar,
            render_review_history,
            render_status_panel,
            render_verdict_summary,
            show_reviewing,
            show_verdict,
        )

        functions = [
            lambda: show_reviewing(5, "Some proposal text"),
            lambda: show_verdict(
                VerdictKind.APPROVE,
                "OK",
                issues=[
                    {"severity": "warning", "message": "Test"},
                ],
                confidence=0.8,
                review_count=3,
                remaining_budget=17,
            ),
            lambda: render_verdict_summary(VerdictKind.APPROVE, "OK", 3, 17),
            lambda: render_progress_bar(8, 20),
            lambda: render_review_history(
                [
                    {
                        "checkpoint": 1,
                        "verdict": "approve",
                        "latency_ms": 100.0,
                        "summary": "OK",
                    }
                ]
            ),
            lambda: render_status_panel(
                enabled=True,
                active=True,
                agent_name="muse",
                review_count=5,
                remaining_budget=15,
                max_reviews=20,
                consecutive_revisions=0,
                max_loops=3,
                avg_latency_ms=120.0,
            ),
        ]

        for func in functions:
            start = time.monotonic()
            for _ in range(100):
                func()
            elapsed_ms = (time.monotonic() - start) * 1000
            avg_ms = elapsed_ms / 100
            assert avg_ms < 1, f"{func.__name__ or 'lambda'} avg {avg_ms:.3f}ms > 1ms"


# ---------------------------------------------------------------------------
# Plugin loading verification
# ---------------------------------------------------------------------------


class TestPluginLoading:
    """Verify the plugin loads correctly and all callbacks are registered."""

    def test_register_tools_returns_tool_defs(self):
        """_register_debate_tools returns the expected tool definitions."""
        tools = _register_debate_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "request_review"
        assert callable(tools[0]["register_func"])

    def test_load_prompt_returns_string(self):
        """load_prompt hook returns a non-empty string when enabled."""
        result = _on_load_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_custom_command_help_entries(self):
        """custom_command_help returns entries for all subcommands."""
        from code_muse.plugins.debate.register_callbacks import (
            _on_custom_command_help,
        )

        entries = _on_custom_command_help()
        assert isinstance(entries, list)
        assert len(entries) >= 8

        names = [e[0] for e in entries]
        assert "debate on" in names
        assert "debate off" in names
        assert "debate toggle" in names
        assert "debate status" in names
        assert "debate stats" in names
        assert "debate metrics" in names
        assert "debate history" in names
        assert "debate reset" in names

    def test_schemas_valid(self):
        """Verify all schema models can be instantiated."""
        v = _make_verdict()
        assert v.kind == VerdictKind.APPROVE
        assert v.confidence == 0.9

        req = ReviewRequest(
            proposal="Test proposal",
            reasoning_summary="Test reasoning",
            checkpoint=1,
        )
        assert req.proposal == "Test proposal"

        resp = _make_response()
        assert resp.verdict.kind == VerdictKind.APPROVE
        assert resp.remaining_budget == 19

    def test_imports_from_package(self):
        """All __all__ exports from the package are importable."""
        from code_muse.plugins.debate import (
            get_debate_max_loops,
            get_debate_max_reviews,
            is_debate_enabled,
        )

        # Verify they're all usable
        assert is_debate_enabled() is True
        assert get_debate_max_reviews() == 20
        assert get_debate_max_loops() == 3


# ---------------------------------------------------------------------------
# Full plugin smoke test — end-to-end across all subsystems
# ---------------------------------------------------------------------------


class TestFullPluginSmokeTest:
    """Complete end-to-end smoke test exercising every subsystem:

    1. Plugin loads → callbacks registered → tool available
    2. Planner submits proposal → reviewer returns verdict
    3. State, telemetry, and UI all update consistently
    4. Slash commands query state correctly
    5. Budget enforcement blocks further reviews when exhausted
    6. Reset clears everything for a fresh session
    """

    @pytest.mark.asyncio
    async def test_complete_session_lifecycle(self):
        """Simulate a full session from start to finish."""
        # Step 1: Verify plugin loads
        tools = _register_debate_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "request_review"

        prompt_addendum = _on_load_prompt()
        assert prompt_addendum is not None
        assert "request_review" in prompt_addendum

        help_entries = _on_custom_command_help()
        assert len(help_entries) >= 8

        # Step 2: Start agent run
        await _on_agent_run_start("muse", "claude-3.5-sonnet", "s1")
        assert DebateState.is_active()

        # Step 3: First checkpoint — approve
        mock_response_1 = _make_response(VerdictKind.APPROVE, "Good start", 0.92)
        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response_1,
        ):
            mock_agent = MagicMock()
            captured_tool = None

            def capture(fn):
                nonlocal captured_tool
                captured_tool = fn
                return fn

            mock_agent.tool = capture
            tools[0]["register_func"](mock_agent)

            mock_context = MagicMock()
            r1 = await captured_tool(
                mock_context, "Phase 1: set up project structure", checkpoint=1
            )

        assert r1["verdict"]["kind"] == "approve"
        assert r1["review_count"] == 1
        assert r1["remaining_budget"] == 19

        # Verify state and telemetry are consistent
        assert DebateState.review_count() == 1
        assert DebateState.remaining_budget() == 19
        assert DebateState.consecutive_revisions() == 0
        stats = get_session_stats()
        assert stats["total_reviews"] == 1

        # Step 4: Second checkpoint — revise (issues found)
        issues = [
            Issue(
                severity="warning",
                message="No error handling",
                suggestion="Add try/except",
            ),
        ]
        mock_response_2 = ReviewResponse(
            verdict=Verdict(
                kind=VerdictKind.REVISE,
                summary="Needs error handling",
                issues=issues,
                confidence=0.78,
            ),
            review_count=2,
            remaining_budget=18,
        )
        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response_2,
        ):
            r2 = await captured_tool(
                mock_context,
                "Phase 2: add API routes",
                reasoning_summary="Routes need error handling",
                checkpoint=2,
            )

        assert r2["verdict"]["kind"] == "revise"
        assert r2["review_count"] == 2
        assert len(r2["verdict"]["issues"]) == 1
        assert r2["verdict"]["issues"][0]["suggestion"] == "Add try/except"

        assert DebateState.consecutive_revisions() == 1
        assert DebateState.review_count() == 2

        # Step 5: Third checkpoint — approve (after revision)
        mock_response_3 = _make_response(
            VerdictKind.APPROVE, "Error handling added correctly", 0.95
        )
        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response_3,
        ):
            r3 = await captured_tool(
                mock_context,
                "Phase 2 revised: routes with try/except",
                checkpoint=3,
            )

        assert r3["verdict"]["kind"] == "approve"
        assert r3["review_count"] == 3

        # Approve should have reset consecutive revisions
        assert DebateState.consecutive_revisions() == 0

        # Step 6: Verify slash commands work
        result = _on_custom_command("/debate status", "debate")
        assert result is True

        result = _on_custom_command("/debate history", "debate")
        assert result is True

        result = _on_custom_command("/debate stats", "debate")
        assert result is True

        # Step 7: Verify telemetry consistency
        stats = get_session_stats()
        assert stats["total_reviews"] == 3
        breakdown = get_verdict_breakdown()
        assert breakdown["approve"] == 2
        assert breakdown["revise"] == 1
        assert breakdown["reject"] == 0

        # Step 8: Exhaust remaining budget (17 more reviews)
        for i in range(17):
            DebateState.record_review(i + 4, VerdictKind.APPROVE, "Auto-approve", 50.0)
        assert DebateState.is_budget_exhausted()
        assert DebateState.remaining_budget() == 0

        # Budget enforcement should block further reviews
        block_result = await _on_pre_tool_call("request_review", {"proposal": "x"})
        assert block_result == {"blocked": True}

        # Step 9: Reset clears everything
        _on_custom_command("/debate reset", "debate")
        assert DebateState.review_count() == 0
        assert DebateState.remaining_budget() == 20
        assert get_session_stats()["total_reviews"] == 0

        # Step 10: End agent run
        await _on_agent_run_end("muse", "claude-3.5-sonnet", "s1", success=True)
        assert not DebateState.is_active()

    @pytest.mark.asyncio
    async def test_toggle_disables_and_re_enables(self):
        """Toggling debate mode off then on preserves clean state."""
        # Start enabled
        assert is_debate_enabled() is True

        # Toggle off
        _on_custom_command("/debate off", "debate")
        assert is_debate_enabled() is False

        # request_review returns quick approve when disabled
        tools = _register_debate_tools()
        mock_agent = MagicMock()
        captured_tool = None

        def capture(fn):
            nonlocal captured_tool
            captured_tool = fn
            return fn

        mock_agent.tool = capture
        tools[0]["register_func"](mock_agent)

        mock_context = MagicMock()
        result = await captured_tool(mock_context, "X", checkpoint=1)
        assert result["verdict"]["kind"] == "approve"
        assert "disabled" in result["verdict"]["summary"].lower()
        assert DebateState.review_count() == 0  # No state update

        # Toggle back on
        _on_custom_command("/debate on", "debate")
        assert is_debate_enabled() is True

        # Now a real review should work
        mock_response = _make_response(VerdictKind.APPROVE, "OK", 0.9)
        with patch(
            "code_muse.plugins.debate.register_callbacks.run_review",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await captured_tool(mock_context, "Real proposal", checkpoint=1)
            assert result["verdict"]["kind"] == "approve"
            assert DebateState.review_count() == 1

    @pytest.mark.asyncio
    async def test_history_tracks_across_checkpoints(self):
        """Review history accumulates correctly across checkpoints."""
        # Manually build history via state
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 120.0)
        DebateState.record_review(2, VerdictKind.REVISE, "Fix tests", 250.0)
        DebateState.record_review(2, VerdictKind.APPROVE, "Fixed", 110.0)
        DebateState.record_review(3, VerdictKind.APPROVE, "Done", 95.0)

        history = DebateState.review_history()
        assert len(history) == 4
        assert history[0]["checkpoint"] == 1
        assert history[1]["checkpoint"] == 2
        assert history[2]["checkpoint"] == 2  # Same checkpoint, revised
        assert history[3]["checkpoint"] == 3

        # Verify verdict progression
        assert [h["verdict"] for h in history] == [
            "approve",
            "revise",
            "approve",
            "approve",
        ]

        # Verify latency tracking in history
        assert history[1]["latency_ms"] == 250.0
