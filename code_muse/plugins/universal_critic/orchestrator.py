"""Review orchestration for Universal Code Critic."""

import logging
import re

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning
from code_muse.plugins.universal_critic.models import (
    ReviewResult,
)

logger = logging.getLogger(__name__)

# Track iteration state per task (session_id -> iteration count)
_ITERATION_TRACKER: dict[str, int] = {}
MAX_REVIEW_ITERATIONS = 3

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


async def _request_rewrite(
    agent_name: str,
    original_prompt: str,
    review_result: ReviewResult,
    iteration: int,
) -> None:
    """Request a rewrite from the originating agent (informational for now)."""
    display = get_display_name(agent_name)
    emit_warning(
        f"❌ Universal Code Critic REJECTED output from {display}: "
        f"{review_result.summary}"
    )
    for issue in review_result.issues:
        emit_warning(f"   • {issue}")
    if review_result.suggestion:
        emit_info(f"   💡 Suggestion: {review_result.suggestion}")

    if iteration < MAX_REVIEW_ITERATIONS:
        emit_info(
            f"🔄 Requesting rewrite from {display} "
            f"(iteration {iteration + 1}/{MAX_REVIEW_ITERATIONS})"
        )
    else:
        emit_warning(
            f"⚠️ Max review iterations ({MAX_REVIEW_ITERATIONS}) reached "
            f"for {display}. Stopping review loop."
        )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```[\w]*\s*(\S+\.\w+)?\s*\n(.*?)```", re.DOTALL)
_FILE_PATH_RE = re.compile(
    r"(?:^|\s|`)([\w./-]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml|toml|"
    r"cfg|ini|md|txt|html|css|sh|rs|go|java|rb))"
)


def _parse_response_for_review(response_text: str) -> list[dict]:
    """Parse response text to find code blocks and file paths to review."""
    results: list[dict] = []

    # Code blocks with optional file annotation (```python file.py)
    for match in _CODE_BLOCK_RE.finditer(response_text):
        file_path = match.group(1) or "unknown"
        code_snippet = match.group(2).strip()
        if code_snippet:
            results.append({"file_path": file_path, "code_snippet": code_snippet})

    # If no code blocks found, check for mentioned file paths
    if not results:
        for fp in _extract_file_paths(response_text):
            results.append({"file_path": fp, "code_snippet": response_text[:2000]})

    return results


def _extract_file_paths(text: str) -> list[str]:
    """Extract file paths from text using common patterns."""
    return list(dict.fromkeys(_FILE_PATH_RE.findall(text)))


# ---------------------------------------------------------------------------
# Hook handler
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
    """Hook handler for agent_run_end — auto-review coding agent output."""
    # Don't review the critic's own runs
    if agent_name == "code-critic":
        return

    if not success or not response_text:
        return

    display = get_display_name(agent_name)
    emit_info(f"🔍 Universal Code Critic reviewing output from {display}...")

    items = _parse_response_for_review(response_text)
    if not items:
        emit_info("ℹ️ No reviewable code blocks found in agent output.")
        return

    sid = session_id or "default"
    iteration = _ITERATION_TRACKER.get(sid, 0)

    for item in items:
        result = await run_review(
            code_snippet=item["code_snippet"],
            file_path=item["file_path"],
            originating_agent=agent_name,
        )
        if result.verdict == "approved":
            emit_success(
                f"✅ Universal Code Critic APPROVED "
                f"{item['file_path']}: {result.summary}"
            )
        elif result.verdict in ("rejected", "flagged"):
            iteration += 1
            _ITERATION_TRACKER[sid] = iteration
            await _request_rewrite(agent_name, "", result, iteration)
        else:
            emit_info(
                f"⚠️ Universal Code Critic flagged {item['file_path']}: {result.summary}"
            )


# ---------------------------------------------------------------------------
# Register the callback
# ---------------------------------------------------------------------------

register_callback("agent_run_end", auto_review_after_run)

logger.debug("Universal Critic orchestrator callbacks registered")
