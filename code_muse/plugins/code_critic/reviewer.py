"""Core review orchestration for Code Critic."""

import logging
from typing import Any

import orjson as json

from code_muse.plugins.code_critic.critic_prompt import (
    CRITIC_SYSTEM_PROMPT,
    REVIEW_CONTEXT_PROMPT,
)

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict | None:
    """Extract JSON object from text, trying various strategies."""

    # Try to find a JSON block with { ... }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        candidate = text[brace_start : brace_end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Try parsing the whole thing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: heuristic
    lower = text.lower()
    if "approved" in lower and "rejected" not in lower:
        return {
            "verdict": "approved",
            "summary": text[:300],
            "issues": [],
            "suggestion": None,
        }
    if "rejected" in lower:
        return {
            "verdict": "rejected",
            "summary": text[:300],
            "issues": ["Reviewer identified problems"],
            "suggestion": "Rewrite based on the feedback above.",
        }
    return {
        "verdict": "flagged",
        "summary": text[:300],
        "issues": ["Unstructured review output"],
        "suggestion": None,
    }


async def review_code(
    file_path: str,
    code_snippet: str,
    operation: str = "review",
    agent_name: str = "unknown",
) -> dict[str, Any]:
    """Run a code review using the configured LLM.

    Returns dict with verdict, summary, issues, suggestion.
    """
    try:
        from pydantic_ai import Agent as PydanticAgent

        from code_muse.config import get_global_model_name
        from code_muse.model_factory import ModelFactory, make_model_settings
        from code_muse.model_utils import prepare_prompt_for_model

        model_name = get_global_model_name()
        if not model_name:
            logger.warning("No model available for code review")
            return _fallback_verdict("No model configured")

        models_config = ModelFactory.load_config()
        if model_name not in models_config:
            logger.warning("Model '%s' not found in config", model_name)
            return _fallback_verdict(f"Model {model_name} not found")

        model = ModelFactory.get_model(model_name, models_config)
        if model is None:
            return _fallback_verdict("Could not create model instance")

        user_prompt = REVIEW_CONTEXT_PROMPT.format(
            file_path=file_path,
            operation=operation,
            agent_name=agent_name,
            code_snippet=code_snippet[:6000],
        )

        prepared = prepare_prompt_for_model(
            model_name,
            CRITIC_SYSTEM_PROMPT,
            user_prompt,
            prepend_system_to_user=False,
        )

        model_settings = make_model_settings(model_name)

        review_agent = PydanticAgent(
            model=model,
            instructions=prepared.instructions or CRITIC_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
            model_settings=model_settings,
        )

        result = await review_agent.run(
            prepared.user_prompt or user_prompt,
            message_history=[],
        )
        text = result.data if hasattr(result, "data") else str(result)
        parsed = _extract_json(text)

        if parsed and "verdict" in parsed:
            return parsed

        return _fallback_verdict("Could not parse structured review", text)

    except Exception as exc:
        logger.error("Code review failed: %s", exc, exc_info=True)
        return _fallback_verdict(str(exc))


def _fallback_verdict(reason: str, raw_text: str | None = None) -> dict[str, Any]:
    """Return a safe fallback verdict when review fails."""
    return {
        "verdict": "flagged",
        "summary": f"Review could not be completed: {reason}",
        "issues": [f"Review error: {reason}"],
        "suggestion": "Manual review recommended.",
        "raw_response": raw_text,
    }


async def review_file(
    file_path: str,
    agent_name: str = "code-critic",
) -> dict[str, Any]:
    """Read a file and review its contents."""
    try:
        from pathlib import Path

        p = Path(file_path).expanduser().resolve()
        if not p.exists():
            return {
                "verdict": "error",
                "summary": f"File not found: {file_path}",
                "issues": [f"Path {file_path} does not exist"],
                "suggestion": None,
            }
        if not p.is_file():
            return {
                "verdict": "error",
                "summary": f"Not a file: {file_path}",
                "issues": [f"Path {file_path} is not a file"],
                "suggestion": None,
            }

        content = p.read_text(encoding="utf-8", errors="replace")
        return await review_code(
            file_path=str(p),
            code_snippet=content,
            operation="manual_review",
            agent_name=agent_name,
        )
    except Exception as exc:
        logger.error("File review failed for %s: %s", file_path, exc, exc_info=True)
        return _fallback_verdict(str(exc))
