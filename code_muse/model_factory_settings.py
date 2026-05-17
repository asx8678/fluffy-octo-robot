"""Model settings helpers extracted from model_factory.py.

This module contains:
- CONTEXT_1M_BETA constant
- _ANTHROPIC_MODEL_TYPES frozenset
- _build_anthropic_beta_header()
- _is_anthropic_model()
- get_api_key()
- make_model_settings()  (main target)
- ZaiChatModel class
"""

import logging
import os
from typing import Any

from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.settings import ModelSettings

from code_muse.config import get_value

logger = logging.getLogger(__name__)

# Anthropic beta header required for 1M context window support.
CONTEXT_1M_BETA = "context-1m-2025-08-07"


def _build_anthropic_beta_header(
    model_config: dict,
    *,
    interleaved_thinking: bool = False,
) -> str | None:
    """Build the anthropic-beta header value for an Anthropic model.

    Combines beta flags based on model capabilities:
    - interleaved-thinking-2025-05-14  (when interleaved_thinking is enabled)
    - context-1m-2025-08-07            (when context_length >= 1_000_000)

    Returns None if no beta flags are needed.
    """
    parts: list[str] = []
    if interleaved_thinking:
        parts.append("interleaved-thinking-2025-05-14")
    if model_config.get("context_length", 0) >= 1_000_000:
        parts.append(CONTEXT_1M_BETA)
    return ",".join(parts) if parts else None


def get_api_key(env_var_name: str) -> str | None:
    """Get an API key from config first, then fall back to environment variable.

    This allows users to set API keys via `/set KIMI_API_KEY=xxx` in addition to
    setting them as environment variables.

    Args:
        env_var_name: The name of the environment variable (e.g., "OPENAI_API_KEY")

    Returns:
        The API key value, or None if not found in either config or environment.
    """
    # First check config (case-insensitive key lookup)
    config_value = get_value(env_var_name.lower())
    if config_value:
        return config_value

    # Fall back to environment variable
    return os.environ.get(env_var_name)


# Model types that use the Anthropic Messages API under the hood.
# These all need Anthropic-specific settings (thinking, effort, etc.).
_ANTHROPIC_MODEL_TYPES = frozenset({"anthropic", "aws_bedrock", "claude_code"})


def _is_anthropic_model(model_name: str, model_config: dict[str, Any]) -> bool:
    """Check if a model uses the Anthropic API (by name prefix or config type)."""
    if model_name.startswith("claude-") or model_name.startswith("anthropic-"):
        return True
    return model_config.get("type") in _ANTHROPIC_MODEL_TYPES


def make_model_settings(
    model_name: str, max_tokens: int | None = None
) -> ModelSettings:
    """Create appropriate ModelSettings for a given model.

    This handles model-specific settings:
    - GPT-5 models: reasoning_effort and verbosity (non-codex only)
    - Claude/Anthropic models: extended_thinking and budget_tokens
    - Automatic max_tokens calculation based on model context length

    Args:
        model_name: The name of the model to create settings for.
        max_tokens: Optional max tokens limit. If None, prefers the model's declared
            max_output/max_output_tokens (when present), else conservative 12% of context.

    Returns:
        Appropriate ModelSettings subclass instance for the model.
    """
    from code_muse.config import (
        get_effective_model_settings,
        get_openai_reasoning_effort,
        get_openai_reasoning_summary,
        get_openai_verbosity,
        model_supports_setting,
    )

    # Deferred import to avoid circular dependency (model_factory imports this module)
    from code_muse.model_factory import ModelFactory

    model_settings_dict: dict = {}

    # Calculate max_tokens if not explicitly provided
    model_config: dict[str, Any] = {}
    if max_tokens is None:
        # Load model config to get context length + preferred max_output
        try:
            models_config = ModelFactory.load_config()
            model_config = models_config.get(model_name, {})
            context_length = model_config.get("context_length", 128000)
        except Exception:
            # Fallback if config loading fails (e.g., in CI environments)
            context_length = 128000
            model_config = {}

        # Respect per-model max_output / max_output_tokens when declared
        # (Claude 1M often supports 64k-128k output, many 200k+ models too).
        declared_max_out = (
            model_config.get("max_output") or model_config.get("max_output_tokens") or 0
        )
        if declared_max_out > 0:
            max_tokens = max(
                2048, min(int(declared_max_out), int(0.12 * context_length), 65536)
            )
        else:
            # Conservative default: 12% of context (was 15%), still capped at 65k
            max_tokens = max(2048, min(int(0.12 * context_length), 65536))
    elif not model_config:
        try:
            model_config = ModelFactory.load_config().get(model_name, {})
        except Exception:
            model_config = {}

    model_settings_dict["max_tokens"] = max_tokens
    effective_settings = get_effective_model_settings(model_name)
    model_settings_dict.update(effective_settings)

    # Parallel tool calls are always enabled.  Read-only tools (file reads,
    # greps, list_files, etc.) are safe to run concurrently without user
    # review.  Destructive tools still go through the approval loop before
    # execution, and the CLI user can cancel individual calls.

    # Default to clear_thinking=False for GLM-4.7 and GLM-5 models (preserved thinking)
    if "glm-4.7" in model_name.lower() or "glm-5" in model_name.lower():
        clear_thinking = effective_settings.get("clear_thinking", False)
        model_settings_dict["thinking"] = {
            "type": "enabled",
            "clear_thinking": clear_thinking,
        }

    model_settings: ModelSettings = ModelSettings(**model_settings_dict)

    # Copilot models use OpenAI-compatible format even for Claude backends.
    # Claude thinking translates to reasoning_effort; GPT models get the
    # standard OpenAI reasoning settings.
    model_type = model_config.get("type")
    is_copilot = model_type == "copilot"
    copilot_underlying = model_config.get("name", "").lower() if is_copilot else ""

    if is_copilot and copilot_underlying.startswith("claude-"):
        # Copilot wraps Claude behind an OpenAI-compatible API.
        # Translate extended_thinking / effort into reasoning_effort.
        from code_muse.model_utils import get_default_extended_thinking

        default_thinking = get_default_extended_thinking(copilot_underlying)
        extended_thinking = effective_settings.get(
            "extended_thinking", default_thinking
        )
        # Legacy boolean compat
        if extended_thinking is True:
            extended_thinking = "enabled"
        elif extended_thinking is False:
            extended_thinking = "off"

        if extended_thinking in ("enabled", "adaptive"):
            # Map effort setting to reasoning_effort for the OpenAI format
            effort = effective_settings.get("effort", "high")
            model_settings_dict["openai_reasoning_effort"] = effort

        # Strip Anthropic-only keys that leaked from effective_settings
        for key in ("extended_thinking", "budget_tokens", "interleaved_thinking"):
            model_settings_dict.pop(key, None)

        model_settings = OpenAIChatModelSettings(**model_settings_dict)

    elif is_copilot and (
        copilot_underlying.startswith("gpt-")
        or copilot_underlying.startswith("o3")
        or copilot_underlying.startswith("o4")
    ):
        # Copilot GPT/O-series — the Copilot API currently does NOT
        # support reasoning_effort for GPT models (400 Bad Request).
        # Just use plain OpenAIChatModelSettings without reasoning params.
        model_settings = OpenAIChatModelSettings(**model_settings_dict)

    elif "gpt-5" in model_name:
        model_settings_dict["openai_reasoning_effort"] = get_openai_reasoning_effort()

        uses_responses_api = (
            False
            or (model_type == "openai" and "codex" in model_name)
            or (model_type == "custom_openai" and "codex" in model_name)
        )

        if uses_responses_api:
            model_settings_dict["openai_reasoning_summary"] = (
                get_openai_reasoning_summary()
            )
            if "codex" not in model_name:
                model_settings_dict["openai_text_verbosity"] = get_openai_verbosity()
            model_settings = OpenAIResponsesModelSettings(**model_settings_dict)
        else:
            # Chat Completions models don't support configurable reasoning summaries.
            # Keep the old verbosity injection path for non-Responses GPT-5 models.
            if "codex" not in model_name:
                verbosity = get_openai_verbosity()
                model_settings_dict["extra_body"] = {"verbosity": verbosity}
            model_settings = OpenAIChatModelSettings(**model_settings_dict)
    elif _is_anthropic_model(model_name, model_config):
        # Handle Anthropic extended thinking settings
        # Remove top_p as Anthropic doesn't support it with extended thinking
        model_settings_dict.pop("top_p", None)

        # Claude extended thinking requires temperature=1.0 (API restriction)
        # Default to 1.0 if not explicitly set by user
        if model_settings_dict.get("temperature") is None:
            model_settings_dict["temperature"] = 1.0

        from code_muse.model_utils import (
            get_default_extended_thinking,
            should_use_anthropic_thinking_summary,
        )

        actual_model_id = model_config.get("name", model_name)
        default_thinking = get_default_extended_thinking(model_name, actual_model_id)
        extended_thinking = effective_settings.get(
            "extended_thinking", default_thinking
        )
        # Backwards compat: handle legacy boolean values
        if extended_thinking is True:
            extended_thinking = "enabled"
        elif extended_thinking is False:
            extended_thinking = "off"

        budget_tokens = effective_settings.get("budget_tokens", 10000)
        if extended_thinking in ("enabled", "adaptive"):
            model_settings_dict["anthropic_thinking"] = {
                "type": extended_thinking,
            }
            if (
                extended_thinking == "adaptive"
                and should_use_anthropic_thinking_summary(model_name, actual_model_id)
            ):
                model_settings_dict["anthropic_thinking"]["display"] = "summarized"
            # Only send budget_tokens for classic "enabled" mode
            if extended_thinking == "enabled" and budget_tokens:
                model_settings_dict["anthropic_thinking"]["budget_tokens"] = (
                    budget_tokens
                )

        # Opus 4-6 models support the `effort` setting via output_config.
        # pydantic-ai doesn't have a native field for output_config yet,
        # so we inject it through extra_body which gets merged into the
        # HTTP request body.
        # NOTE: effort/output_config only applies to adaptive thinking.
        # With standard "enabled" thinking, budget_tokens controls depth.
        if (
            model_supports_setting(model_name, "effort")
            and extended_thinking == "adaptive"
        ):
            effort = effective_settings.get(
                "effort", model_config.get("default_effort", "high")
            )
            if "anthropic_thinking" in model_settings_dict:
                extra_body = model_settings_dict.get("extra_body") or {}
                extra_body["output_config"] = {"effort": effort}
                model_settings_dict["extra_body"] = extra_body

        model_settings = AnthropicModelSettings(**model_settings_dict)

    # Handle thinking models
    # Check if model supports thinking settings and apply defaults
    if model_supports_setting(model_name, "thinking_level"):
        # Apply defaults if not explicitly set by user
        # Default: thinking_enabled=True, thinking_level="low"
        if "thinking_enabled" not in model_settings_dict:
            model_settings_dict["thinking_enabled"] = True
        if "thinking_level" not in model_settings_dict:
            model_settings_dict["thinking_level"] = "low"
        # Recreate settings with Gemini thinking config
        model_settings = ModelSettings(**model_settings_dict)

    return model_settings


class ZaiChatModel(OpenAIChatModel):
    def _process_response(self, response):
        response.object = "chat.completion"
        return super()._process_response(response)
