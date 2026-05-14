"""Core review orchestration — builds context, calls LLM, parses result."""

import logging

import orjson as json

from code_muse.plugins.auto_review.cache import get_review_cache
from code_muse.plugins.auto_review.config import (
    get_auto_review_min_diff_length,
    get_auto_review_model,
    is_auto_review_enabled,
)
from code_muse.plugins.auto_review.review_prompt import REVIEWER_SYSTEM_PROMPT
from code_muse.plugins.auto_review.visibility import (
    emit_review_approved,
    emit_review_error,
    emit_review_flagged,
    emit_review_rejected,
    emit_review_started,
)

logger = logging.getLogger(__name__)

# Known file-modification tools that trigger review
_FILE_MOD_TOOLS = frozenset(
    {
        "create_file",
        "replace_in_file",
        "delete_snippet",
        "delete_file",
    }
)


def _compute_content_hash(file_path: str, diff: str) -> str:
    """Compute a stable hash for cache key."""
    import hashlib

    return hashlib.sha256(f"{file_path}::{diff}".encode()).hexdigest()[:16]


def _extract_review_context(
    tool_name: str,
    tool_args: dict,
    result: dict,
) -> dict | None:
    """Extract review context from tool call data.

    Returns dict with file_path, operation, diff, content_hash or None
    if the operation doesn't warrant review (e.g. it failed).
    """
    # Only review successful changes
    if not result.get("success") and not result.get("changed"):
        return None

    file_path = tool_args.get("file_path", tool_args.get("path", ""))
    if not file_path:
        return None

    # Build a review diff from the result
    diff = ""
    if "diff" in result:
        diff = result["diff"]

    # For create_file, the diff might be in the result as a message
    if not diff and tool_name == "create_file":
        content = tool_args.get("content", "")
        if content:
            lines = content.splitlines()
            diff = (
                f"--- /dev/null\n+++ b/{file_path}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n"
                + "\n".join(f"+{line}" for line in lines)
            )

    # For delete_file, note the deletion
    if not diff and tool_name == "delete_file":
        diff = f"--- a/{file_path}\n+++ /dev/null\n@@ -1,0 +0,0 @@\nFile deleted."

    # Skip trivial changes
    if len(diff.strip()) < get_auto_review_min_diff_length():
        return None

    return {
        "file_path": file_path,
        "operation": tool_name,
        "diff": diff,
        "content_hash": _compute_content_hash(file_path, diff),
    }


def _build_reviewer_prompt(context: dict) -> str:
    """Build the user prompt for the reviewer model."""
    file_path = context["file_path"]
    ext = file_path.rsplit(".", 1)[-1] if "." in file_path else "unknown"
    return f"""Please review this file change:

File: {context["file_path"]}
Operation: {context["operation"]}
Language/type: {ext}

Diff:
```
{context["diff"][:4000]}
```

Provide your structured review as JSON with verdict, summary, issues, and suggestion.
"""


async def _call_reviewer_llm(prompt: str) -> dict | None:
    """Call the reviewer LLM and parse the JSON response.

    Uses ModelFactory to get a model instance, creates a temporary
    pydantic-ai Agent with no tools, and extracts the review.
    """
    try:
        from pydantic_ai import Agent as PydanticAgent

        from code_muse.agents._builder import load_muse_rules
        from code_muse.config import get_global_model_name
        from code_muse.model_factory import ModelFactory, make_model_settings
        from code_muse.model_utils import prepare_prompt_for_model

        model_name = get_auto_review_model() or get_global_model_name()
        if not model_name:
            logger.warning("No model available for auto-review")
            return None

        models_config = ModelFactory.load_config()
        if model_name not in models_config:
            logger.warning("Reviewer model '%s' not found in config", model_name)
            return None

        model = ModelFactory.get_model(model_name, models_config)
        if model is None:
            logger.warning("Could not create reviewer model instance")
            return None

        # Build reviewer instructions
        instructions = REVIEWER_SYSTEM_PROMPT
        rules = load_muse_rules()
        if rules:
            instructions += f"\n\nProject rules:\n{rules}"

        prepared = prepare_prompt_for_model(
            model_name,
            instructions,
            prompt,
            prepend_system_to_user=False,
        )
        instructions = prepared.instructions
        user_prompt = prepared.user_prompt or prompt

        model_settings = make_model_settings(model_name)

        # Create a temporary agent with no tools — just text in, text out
        review_agent = PydanticAgent(
            model=model,
            instructions=instructions,
            output_type=str,
            retries=1,
            model_settings=model_settings,
        )

        result = await review_agent.run(user_prompt, message_history=[])
        text = result.data if hasattr(result, "data") else str(result)

        # Try to parse JSON from the response
        # Look for JSON block first
        import re

        json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if json_match:
            # Expand to find complete JSON object
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = text[start:end]
                return json.loads(json_str)

        # Try parsing entire response as JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fallback: simple heuristic
        text_lower = text.lower()
        if (
            "looks good" in text_lower
            or "approved" in text_lower
            or "no issues" in text_lower
        ):
            return {
                "verdict": "approved",
                "summary": text[:200],
                "issues": [],
                "suggestion": None,
            }
        return {
            "verdict": "flagged",
            "summary": text[:200],
            "issues": ["Reviewer produced unstructured output"],
            "suggestion": None,
        }

    except Exception as exc:
        logger.error("Auto-review LLM call failed: %s", exc, exc_info=True)
        return None


async def run_auto_review(
    tool_name: str,
    tool_args: dict,
    result: dict,
) -> None:
    """Main entry point — run auto-review on a completed tool call.

    Called from the ``post_tool_call`` hook. Checks eligibility,
    extracts context, checks cache, calls reviewer, emits results.
    """
    if not is_auto_review_enabled():
        return

    # Only review file modification tools
    if tool_name not in _FILE_MOD_TOOLS:
        return

    context = _extract_review_context(tool_name, tool_args, result)
    if context is None:
        return

    # Check cache
    cache = get_review_cache()
    cached = cache.get(context["file_path"], context["content_hash"])
    if cached is not None:
        emit_review_approved(context["file_path"], "Already reviewed (cached)")
        return

    # Emit visibility: review started
    emit_review_started(context["file_path"])

    # Build prompt and call reviewer
    prompt = _build_reviewer_prompt(context)
    review = await _call_reviewer_llm(prompt)

    if review is None:
        emit_review_error(context["file_path"], "Reviewer LLM call failed")
        return

    # Cache and emit result
    cache.set(context["file_path"], context["content_hash"], review)

    verdict = review.get("verdict", "flagged")
    summary = review.get("summary", "No summary provided")
    issues = review.get("issues", [])
    suggestion = review.get("suggestion")

    if verdict == "approved":
        if suggestion:
            summary += f" — Suggestion: {suggestion}"
        emit_review_approved(context["file_path"], summary)
    elif verdict == "rejected":
        emit_review_rejected(context["file_path"], summary, issues)
    else:
        emit_review_flagged(context["file_path"], summary, issues)


# Tool: manual review request
async def request_manual_review(file_path: str, reason: str | None = None) -> dict:
    """Request a manual code review for a specific file.

    This is registered as an agent tool so users can trigger review explicitly.
    """
    try:
        # Read the file content directly
        file_content = ""
        try:
            from pathlib import Path

            p = Path(file_path).expanduser().resolve()
            if p.exists() and p.is_file():
                file_content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

        context = {
            "file_path": file_path,
            "operation": "manual_review",
            "diff": file_content[:5000],
            "content_hash": _compute_content_hash(file_path, file_content[:5000]),
        }

        prompt = _build_reviewer_prompt(context)
        if reason:
            prompt += f"\n\nReview focus: {reason}"

        emit_review_started(file_path)
        review = await _call_reviewer_llm(prompt)

        if review is None:
            return {"error": "Reviewer LLM call failed", "file_path": file_path}

        return {
            "file_path": file_path,
            "verdict": review.get("verdict", "flagged"),
            "summary": review.get("summary", ""),
            "issues": review.get("issues", []),
            "suggestion": review.get("suggestion"),
        }

    except Exception as exc:
        logger.error("Manual review failed: %s", exc, exc_info=True)
        return {"error": str(exc), "file_path": file_path}
