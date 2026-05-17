"""Core review orchestration for Code Critic.

Preflight (truncation / structural sanity) is now delegated to
``critic_fabric.preflight``, which is the canonical single place for
all pre-LLM checks.  The LLM review body lives in
``_review_code_with_llm()`` so that the fabric's ``code_critic``
backend can call it after preflight passes.

Public API (backward-compatible):
    - ``review_code()`` — returns dict with verdict/summary/issues/suggestion
    - ``review_file()`` — reads a file and reviews it
    - ``_detect_code_truncation()`` — backward-compat re-export
"""

import ast
import logging
from pathlib import Path
from typing import Any

import orjson as json

from code_muse.plugins.code_critic.critic_prompt import (
    CRITIC_SYSTEM_PROMPT,
    REVIEW_CONTEXT_PROMPT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backward-compatible re-export from truncation_detector plugin
# ---------------------------------------------------------------------------
# The canonical implementation now lives in
# ``code_muse.plugins.truncation_detector.detector``.  This wrapper delegates
# to it when available, falling back to the inline implementation otherwise.
# Existing consumers (``universal_critic/orchestrator.py``,
# ``universal_constructor/sandbox.py``) import ``_detect_code_truncation``
# from this module and continue working unchanged.

try:
    from code_muse.plugins.truncation_detector.detector import (
        detect_truncation,
    )

    def _detect_code_truncation(code: str, file_path: str) -> tuple[bool, str | None]:
        """Backward-compatible wrapper delegating to truncation_detector."""
        result = detect_truncation(code, file_path=file_path)
        return (result.is_truncated, result.reason)

except ImportError:
    # truncation_detector plugin not available — use inline fallback below

    def _detect_code_truncation(code: str, file_path: str) -> tuple[bool, str | None]:
        """
        Inline fallback — fast, cheap detection of obviously truncated code output.

        Returns (is_truncated, reason).
        Python uses exact ast.parse (caller should prefer that).
        Other languages use structural heuristics.
        """
        if not code or not code.strip():
            return True, "File is empty or contains only whitespace."

        stripped = code.rstrip("\n\r \t")
        ext = Path(file_path).suffix.lower()
        last_line = stripped.splitlines()[-1].strip() if stripped.splitlines() else ""

        # Obvious "open" endings that almost always mean truncation
        open_endings = (
            "{",
            "[",
            "(",
            ":",
            ",",
            "&&",
            "||",
            "and ",
            "or ",
            "+",
            "-",
            "=",
            "->",
            "=>",
        )
        if any(stripped.endswith(end) for end in open_endings):
            return True, (
                f"Code ends abruptly with incomplete token: `{last_line[-40:]}`"
            )

        # Declaration starters that are truncated when last. Only on short lines
        # lacking body/closers (avoids noise on compact valid one-liners).
        if len(last_line) < 90 and not any(c in last_line for c in "{}();:"):
            starters = (
                "function ",
                "const ",
                "let ",
                "var ",
                "class ",
                "interface ",
                "type ",
                "import ",
                "from ",
                "export ",
                "def ",
                "fn ",
                "pub ",
                "async ",
                "await ",
                "if ",
                "for ",
                "while ",
                "switch ",
                "match ",
                "enum ",
                "struct ",
                "impl ",
                "trait ",
                "mod ",
                "package ",
            )
            if any(last_line.startswith(s) for s in starters):
                return True, (
                    f"Last line looks like a truncated declaration: `{last_line}`"
                )

        # Rough bracket balance check (helps with JS/TS/Go/Rust/etc.)
        opens = stripped.count("{") + stripped.count("[") + stripped.count("(")
        closes = stripped.count("}") + stripped.count("]") + stripped.count(")")
        if opens > closes + 3:
            return True, (
                f"Too many opening brackets ({opens}) vs closing ({closes}) — "
                "likely truncated."
            )

        # Python is expected to be caught by exact ast.parse before this function.
        # We still do a weak check for non-.py files that happen to be Python.
        if ext in {".py", ".pyi"}:
            try:
                ast.parse(code)
            except SyntaxError as e:
                return True, f"Python syntax error: {e.msg} (line {e.lineno})"

        return False, None


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


# ---------------------------------------------------------------------------
# LLM review body (extracted for fabric backend reuse)
# ---------------------------------------------------------------------------


async def _review_code_with_llm(
    file_path: str,
    code_snippet: str,
    operation: str = "review",
    agent_name: str = "unknown",
) -> dict[str, Any]:
    """Run the LLM-based code review.

    This is the *post-preflight* path — callers must have already
    validated that the code is not truncated.  The fabric's
    ``code_critic`` backend delegates here.

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


# ---------------------------------------------------------------------------
# Public API — backward-compatible dict return shape
# ---------------------------------------------------------------------------


async def review_code(
    file_path: str,
    code_snippet: str,
    operation: str = "review",
    agent_name: str = "unknown",
) -> dict[str, Any]:
    """Run a code review using the configured LLM.

    Returns dict with verdict, summary, issues, suggestion.

    Delegates preflight (truncation / structural checks) to
    ``critic_fabric.preflight`` — the canonical single place for all
    pre-LLM sanity checks.  If the fabric is unavailable, falls back
    to inline AST / truncation checks for backward compatibility.
    """
    # --- Preflight via fabric (preferred) ---
    try:
        from code_muse.plugins.critic_fabric.preflight import run_preflight

        preflight_result = run_preflight(code_snippet, file_path)
        if preflight_result is not None:
            return preflight_result.to_dict()
    except ImportError:
        # critic_fabric not available — fall through to inline checks
        logger.debug("critic_fabric unavailable, using inline preflight")

    # --- Inline fallback preflight (when fabric is missing) ---
    if file_path.endswith((".py", ".pyi")):
        try:
            ast.parse(code_snippet)
        except SyntaxError as e:
            return {
                "verdict": "rejected",
                "summary": "Python code is syntactically truncated or invalid",
                "issues": [
                    f"SyntaxError: {e.msg} (line {e.lineno})",
                    "The file ends mid-statement or is missing closing constructs.",
                    "The model output was cut off before the file was complete.",
                ],
                "suggestion": (
                    "Rewrite the ENTIRE file in one response. "
                    "Output complete Python that parses with ast.parse()."
                ),
            }

    is_trunc, reason = _detect_code_truncation(code_snippet, file_path)
    if is_trunc:
        return {
            "verdict": "rejected",
            "summary": "Code appears syntactically truncated or incomplete",
            "issues": [
                reason or "Output ends in an incomplete statement or declaration."
            ],
            "suggestion": (
                "Rewrite the ENTIRE file in one response. "
                "Output the complete, valid source for the whole file."
            ),
        }

    # --- LLM review ---
    return await _review_code_with_llm(
        file_path=file_path,
        code_snippet=code_snippet,
        operation=operation,
        agent_name=agent_name,
    )


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
