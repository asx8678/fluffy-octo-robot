"""Review orchestration for Universal Code Critic.

Primary review mechanism is ``review_on_result`` registered on the
``agent_run_result`` hook.  It receives the actual ``RunResult`` object,
extracts file changes from ``result.all_messages()``, reads the real code
from disk, and returns a ``{"retry": True, ...}`` dict on rejection —
driving the runtime's retry loop.

A secondary ``auto_review_after_run`` on ``agent_run_end`` is purely
informational (no retry).
"""

import ast
import logging
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelResponse, ToolCallPart

from code_muse.messaging import emit_info, emit_success, emit_warning
from code_muse.plugins.code_critic.reviewer import _detect_code_truncation
from code_muse.plugins.universal_critic.models import ReviewResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_REVIEW_ITERATIONS = 10

# Track iteration state per agent_name
_ITERATION_TRACKER: dict[str, int] = {}

# Tool names that write files — used to extract changed files from RunResult
_FILE_WRITE_TOOLS = frozenset(
    {
        "replace_in_file",
        "create_file",
        "delete_file",
        "write_file",
    }
)

# ---------------------------------------------------------------------------
# Display-name mapping
# ---------------------------------------------------------------------------

_DISPLAY_NAMES: dict[str, str] = {
    "heavy-coding-agent": "heavy coding agent",
    "light-coding-agent": "light coding agent",
    "code-critic": "Universal Code Critic",
}


def get_display_name(agent_name: str) -> str:
    """Map internal agent names to official display names."""
    return _DISPLAY_NAMES.get(agent_name, agent_name.replace("-", " ").title())


# ---------------------------------------------------------------------------
# Core review logic
# ---------------------------------------------------------------------------


async def run_review(
    code_snippet: str, file_path: str, originating_agent: str
) -> ReviewResult:
    """Run a review using the Code Critic's reviewer."""
    from code_muse.plugins.code_critic.reviewer import review_code

    verdict_dict = await review_code(
        file_path=file_path,
        code_snippet=code_snippet[:6000],
        operation="universal_critic_review",
        agent_name=originating_agent,
    )
    return ReviewResult(
        verdict=verdict_dict.get("verdict", "flagged"),
        summary=verdict_dict.get("summary", ""),
        issues=verdict_dict.get("issues", []),
        suggestion=verdict_dict.get("suggestion"),
        raw_response=verdict_dict.get("raw_response"),
    )


# ---------------------------------------------------------------------------
# File extraction from RunResult
# ---------------------------------------------------------------------------


def _extract_changed_files(result: Any) -> list[str]:
    """Extract file paths that were written by the agent from a RunResult.

    Scans ``result.all_messages()`` for ``ToolCallPart`` instances with
    file-writing tool names, then deduplicates the paths.
    """
    if not hasattr(result, "all_messages"):
        return []

    changed_files: list[str] = []
    seen: set[str] = set()

    for msg in result.all_messages():
        if not isinstance(msg, ModelResponse):
            continue
        for part in getattr(msg, "parts", []) or []:
            if not isinstance(part, ToolCallPart):
                continue
            if part.tool_name not in _FILE_WRITE_TOOLS:
                continue
            file_path = _extract_file_path_from_tool_call(part)
            if file_path and file_path not in seen:
                seen.add(file_path)
                changed_files.append(file_path)

    return changed_files


def _extract_file_path_from_tool_call(part: ToolCallPart) -> str | None:
    """Extract the ``file_path`` argument from a ``ToolCallPart``.

    Uses ``args_as_dict()`` which handles both dict and JSON-string args.
    """
    try:
        args = part.args_as_dict()
    except Exception:
        return None
    if isinstance(args, dict):
        return args.get("file_path") or args.get("path")
    return None


def _read_file_content(file_path: str) -> str | None:
    """Read file content from disk, returning ``None`` if not found."""
    try:
        p = Path(file_path).expanduser().resolve()
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        logger.debug("Could not read %s for review", file_path, exc_info=True)
    return None


# ---------------------------------------------------------------------------
# Feedback prompt builders
# ---------------------------------------------------------------------------


def _build_rewrite_prompt(
    review_result: ReviewResult, file_path: str, iteration: int
) -> str:
    """Build a prompt for the agent to rewrite based on critic feedback."""
    issues_text = "\n".join(f"  - {issue}" for issue in review_result.issues)
    suggestion = (
        f"\nSuggestion: {review_result.suggestion}" if review_result.suggestion else ""
    )
    return (
        f"The Universal Code Critic REJECTED your changes to {file_path}.\n"
        f"Summary: {review_result.summary}\n"
        f"Issues:\n{issues_text}{suggestion}\n\n"
        f"Please fix the above issues and rewrite the file."
    )


def _build_escalation_prompt(
    review_result: ReviewResult, file_path: str, iteration: int
) -> str:
    """Build an escalation prompt when max iterations is approaching."""
    issues_text = "\n".join(f"  - {issue}" for issue in review_result.issues)
    return (
        f"⚠️ CRITICAL: The Universal Code Critic has rejected your changes to "
        f"{file_path} {iteration} times. "
        f"This suggests a fundamental approach problem.\n"
        f"Summary: {review_result.summary}\n"
        f"Issues:\n{issues_text}\n\n"
        f"You must completely rethink your approach. Consider:\n"
        f"1. Is there a fundamentally different way to solve this?\n"
        f"2. Should you break the task into smaller pieces?\n"
        f"3. Are you introducing unnecessary complexity?\n"
        f"Please try a completely different approach."
    )


# ---------------------------------------------------------------------------
# agent_run_result hook — primary review with retry
# ---------------------------------------------------------------------------


async def review_on_result(
    result: Any,
    agent_name: str,
    model_name: str,
) -> dict | None:
    """Hook handler for ``agent_run_result`` — review code changes and request retry.

    This is the primary review mechanism.  It:

    1. Extracts file changes from the ``RunResult``'s tool-call history
    2. Reads the actual file content from disk
    3. Sends real code to the critic for review
    4. Returns a ``{"retry": True, ...}`` dict on rejection, which drives
       the runtime's retry loop
    5. Escalates with a stronger prompt when ``MAX_REVIEW_ITERATIONS`` is
       approached, and stops retrying entirely when the limit is reached
    """
    # Don't review the critic's own runs
    if agent_name == "code-critic":
        return None

    changed_files = _extract_changed_files(result)
    if not changed_files:
        return None

    display = get_display_name(agent_name)
    emit_info(
        f"🔍 Universal Code Critic reviewing {len(changed_files)} "
        f"file(s) from {display}..."
    )

    iteration = _ITERATION_TRACKER.get(agent_name, 0)
    all_approved = True

    for file_path in changed_files:
        content = _read_file_content(file_path)
        if content is None:
            emit_info(f"ℹ️ Skipped {file_path} (file not found on disk)")
            continue

        # Fast local syntax / truncation check — catches truncated generations
        # from the Planning Agent or heavy coding agent without an LLM round-trip.
        if file_path.endswith((".py", ".pyi")):
            try:
                ast.parse(content)
            except SyntaxError as e:
                emit_warning(
                    f"❌ Universal Code Critic REJECTED {file_path}: "
                    f"syntactically truncated or invalid Python (AST parse failed)"
                )
                emit_warning(f"   • {e.msg} at line {e.lineno}")
                review_result = ReviewResult(
                    verdict="rejected",
                    summary="Python code is syntactically truncated or invalid",
                    issues=[
                        f"SyntaxError: {e.msg} (line {e.lineno})",
                        "File ends mid-statement (e.g. `monkeypatch.`).",
                        "Model output was cut off before file was complete.",
                    ],
                    suggestion=(
                        "Rewrite the ENTIRE file in one response. "
                        "Output complete, valid Python that parses with ast.parse()."
                    ),
                )
            else:
                review_result = await run_review(
                    code_snippet=content,
                    file_path=file_path,
                    originating_agent=agent_name,
                )
        else:
            # Non-Python: use lightweight structural heuristic
            is_trunc, reason = _detect_code_truncation(content, file_path)
            if is_trunc:
                emit_warning(f"❌ Universal Code Critic REJECTED {file_path}: {reason}")
                review_result = ReviewResult(
                    verdict="rejected",
                    summary="Code appears syntactically truncated or incomplete",
                    issues=[reason or "Output ends in an incomplete construct."],
                    suggestion=(
                        "Rewrite the ENTIRE file in one response. "
                        "Output the complete, valid source for the whole file."
                    ),
                )
            else:
                review_result = await run_review(
                    code_snippet=content,
                    file_path=file_path,
                    originating_agent=agent_name,
                )

        if review_result.verdict == "approved":
            emit_success(
                f"✅ Universal Code Critic APPROVED "
                f"{file_path}: {review_result.summary}"
            )
            continue

        # --- Rejected or flagged ---
        all_approved = False
        iteration += 1
        _ITERATION_TRACKER[agent_name] = iteration

        if review_result.verdict == "rejected":
            emit_warning(
                f"❌ Universal Code Critic REJECTED "
                f"{file_path}: {review_result.summary}"
            )
            for issue in review_result.issues:
                emit_warning(f"   • {issue}")
            if review_result.suggestion:
                emit_info(f"   💡 Suggestion: {review_result.suggestion}")
        else:  # "flagged"
            emit_info(
                f"⚠️ Universal Code Critic flagged {file_path}: {review_result.summary}"
            )
            for issue in review_result.issues:
                emit_info(f"   • {issue}")

        # --- Decide whether to retry or escalate ---
        if iteration >= MAX_REVIEW_ITERATIONS:
            emit_warning(
                f"🛑 Max review iterations ({MAX_REVIEW_ITERATIONS}) reached "
                f"for {display}. Escalating to Planning Agent review."
            )
            _ITERATION_TRACKER.pop(agent_name, None)
            return None  # Stop retrying — let the run end

        if iteration >= MAX_REVIEW_ITERATIONS - 1:
            # One more chance — escalate with stronger prompt
            prompt = _build_escalation_prompt(review_result, file_path, iteration)
        else:
            prompt = _build_rewrite_prompt(review_result, file_path, iteration)

        emit_info(
            f"🔄 Requesting rewrite from {display} "
            f"(iteration {iteration}/{MAX_REVIEW_ITERATIONS})"
        )

        return {
            "retry": True,
            "prompt": prompt,
            "delay": 0.5,
            "source": "critic",
        }

    # All files approved — reset tracker
    if all_approved:
        _ITERATION_TRACKER.pop(agent_name, None)

    return None


# ---------------------------------------------------------------------------
# agent_run_end hook — informational only (no retry)
# ---------------------------------------------------------------------------


async def auto_review_after_run(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: str | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Hook handler for ``agent_run_end`` — informational only.

    The actual review with retry happens in ``review_on_result`` via the
    ``agent_run_result`` hook.  This hook is kept for logging and
    diagnostics.
    """
    if agent_name == "code-critic":
        return

    if not success or not response_text:
        return

    display = get_display_name(agent_name)
    iteration = _ITERATION_TRACKER.get(agent_name, 0)
    if iteration > 0:
        emit_info(f"📊 {display} completed after {iteration} critic iteration(s)")
    else:
        logger.debug(
            "Universal Code Critic: %s run completed, no review iterations",
            display,
        )


# ---------------------------------------------------------------------------
# Register callbacks
# ---------------------------------------------------------------------------

logger.debug("Universal Critic orchestrator module loaded")
