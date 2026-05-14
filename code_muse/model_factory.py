import logging
import os
import pathlib
from typing import Any

import httpx
import orjson
import orjson as json
from anthropic import AsyncAnthropic
from openai import AsyncAzureOpenAI
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.cerebras import CerebrasProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings

from code_muse.gemini_model import GeminiModel
from code_muse.messaging import emit_warning

from . import callbacks
from .claude_cache_client import ClaudeCacheAsyncClient, patch_anthropic_client_messages
from .config import EXTRA_MODELS_FILE, MODELS_FILE, get_value
from .http_utils import create_async_client, get_cert_bundle_path, get_http2
from .provider_identity import (
    make_anthropic_provider,
    make_openai_provider,
    resolve_provider_identity,
)
from .round_robin_model import RoundRobinModel

logger = logging.getLogger(__name__)

# Registry for custom model provider classes from plugins
_CUSTOM_MODEL_PROVIDERS: dict[str, type] = {}

# ---------------------------------------------------------------------------
# PERF-06: Mtime-based config cache to avoid re-reading JSON files on every
# ModelFactory.load_config() call.  Mirrors the pattern already used in
# summarization_agent.get_cached_models_config().  Invalidation: any source
# file's mtime changes, or invalidate_models_config_cache() is called
# explicitly (e.g. after /set commands).
# ---------------------------------------------------------------------------
import hashlib as _hashlib  # noqa: E402
import threading as _threading  # noqa: E402

_models_config_cache: tuple[dict[str, Any] | None, tuple[float, str] | None] = (
    None,
    None,
)
# FREE-THREADED: _models_config_lock guards sync-only cache access.
# All callers are sync; keep as threading.Lock.
_models_config_lock = _threading.Lock()


def _models_config_fingerprint() -> tuple[float, str]:
    """Compute a lightweight fingerprint of all model config source files.

    Returns (max_mtime, content_hash) — if either changes, the cached
    config is stale and must be reloaded.
    """
    source_paths: list[pathlib.Path] = []

    bundled = pathlib.Path(__file__).parent / "models.json"
    source_paths.append(bundled)

    try:
        from code_muse.config import (
            CHATGPT_MODELS_FILE,
            CLAUDE_MODELS_FILE,
            COPILOT_MODELS_FILE,
            EXTRA_MODELS_FILE,
            GEMINI_MODELS_FILE,
            MODELS_FILE,
        )

        for p in (
            MODELS_FILE,
            EXTRA_MODELS_FILE,
            CHATGPT_MODELS_FILE,
            CLAUDE_MODELS_FILE,
            GEMINI_MODELS_FILE,
            COPILOT_MODELS_FILE,
        ):
            source_paths.append(pathlib.Path(p))
    except Exception:
        pass

    max_mtime = 0.0
    hasher = _hashlib.blake2b(digest_size=16)
    for sp in source_paths:
        try:
            if sp.exists():
                stat = sp.stat()
                mtime = stat.st_mtime
                if isinstance(mtime, (int, float)):
                    max_mtime = max(max_mtime, mtime)
                    hasher.update(f"{sp}:{stat.st_size}:{mtime}".encode())
                else:
                    # Mocked stat objects in tests — force cache miss
                    max_mtime = float("inf")
        except OSError:
            pass

    return max_mtime, hasher.hexdigest()


def invalidate_models_config_cache() -> None:
    """Force the next ``ModelFactory.load_config()`` call to reload from disk.

    Call this when settings or model files are known to have changed
    (e.g. after a ``/set`` command that modifies model config).
    """
    global _models_config_cache
    with _models_config_lock:
        _models_config_cache = (None, None)


def _load_plugin_model_providers():
    """Load custom model providers from plugins."""
    global _CUSTOM_MODEL_PROVIDERS
    try:
        from code_muse.callbacks import on_register_model_providers

        results = on_register_model_providers()
        for result in results:
            if isinstance(result, dict):
                _CUSTOM_MODEL_PROVIDERS.update(result)
    except Exception as e:
        logger.warning("Failed to load plugin model providers: %s", e)


# Load plugin model providers at module initialization
_load_plugin_model_providers()


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
_ANTHROPIC_MODEL_TYPES = frozenset(
    {"anthropic", "aws_bedrock", "claude_code"}
)


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
        max_tokens: Optional max tokens limit. If None, automatically calculated
            as: max(2048, min(15% of context_length, 65536))

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

    model_settings_dict: dict = {}

    # Calculate max_tokens if not explicitly provided
    model_config: dict[str, Any] = {}
    if max_tokens is None:
        # Load model config to get context length
        try:
            models_config = ModelFactory.load_config()
            model_config = models_config.get(model_name, {})
            context_length = model_config.get("context_length", 128000)
        except Exception:
            # Fallback if config loading fails (e.g., in CI environments)
            context_length = 128000
        # min 2048, 15% of context, max 65536
        max_tokens = max(2048, min(int(0.15 * context_length), 65536))
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
            model_type == "chatgpt_oauth"
           
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


def get_custom_config(model_config):
    custom_config = model_config.get("custom_endpoint", {})
    if not custom_config:
        raise ValueError("Custom model requires 'custom_endpoint' configuration")

    url = custom_config.get("url")
    if not url:
        raise ValueError("Custom endpoint requires 'url' field")

    headers = {}
    for key, value in custom_config.get("headers", {}).items():
        if value.startswith("$"):
            env_var_name = value[1:]
            resolved_value = get_api_key(env_var_name)
            if resolved_value is None:
                emit_warning(
                    f"'{env_var_name}' is not set (check config or environment) for custom endpoint header '{key}'. Proceeding with empty value."
                )
                resolved_value = ""
            value = resolved_value
        elif "$" in value:
            tokens = value.split(" ")
            resolved_values = []
            for token in tokens:
                if token.startswith("$"):
                    env_var = token[1:]
                    resolved_value = get_api_key(env_var)
                    if resolved_value is None:
                        emit_warning(
                            f"'{env_var}' is not set (check config or environment) for custom endpoint header '{key}'. Proceeding with empty value."
                        )
                        resolved_values.append("")
                    else:
                        resolved_values.append(resolved_value)
                else:
                    resolved_values.append(token)
            value = " ".join(resolved_values)
        headers[key] = value
    api_key = None
    if "api_key" in custom_config:
        if custom_config["api_key"].startswith("$"):
            env_var_name = custom_config["api_key"][1:]
            api_key = get_api_key(env_var_name)
            if api_key is None:
                emit_warning(
                    f"API key '{env_var_name}' is not set (checked config and environment); proceeding without API key."
                )
        else:
            api_key = custom_config["api_key"]
    if "ca_certs_path" in custom_config:
        verify = custom_config["ca_certs_path"]
    else:
        verify = None

    timeout = model_config.get("timeout", custom_config.get("timeout"))
    if timeout is not None:
        if isinstance(timeout, bool):
            raise ValueError("Custom endpoint timeout must be a number")
        if isinstance(timeout, str):
            try:
                timeout = float(timeout)
            except ValueError as exc:
                raise ValueError("Custom endpoint timeout must be a number") from exc
        if not isinstance(timeout, (int, float)):
            raise ValueError("Custom endpoint timeout must be a number")
        if timeout <= 0:
            raise ValueError("Custom endpoint timeout must be greater than zero")

    return url, headers, verify, api_key, timeout


class ModelFactory:
    """A factory for creating and managing different AI models."""

    @staticmethod
    def load_config() -> dict[str, Any]:
        global _models_config_cache
        # PERF-06: Return cached config when source files haven't changed.
        fingerprint = _models_config_fingerprint()
        with _models_config_lock:
            cached_config, cached_fp = _models_config_cache
            if cached_config is not None and cached_fp == fingerprint:
                return cached_config

        # --- Original loading logic (cache miss) ---
        load_model_config_callbacks = callbacks.get_callbacks("load_model_config")
        if len(load_model_config_callbacks) > 0:
            if len(load_model_config_callbacks) > 1:
                logging.getLogger(__name__).warning(
                    "Multiple load_model_config callbacks registered, using the first"
                )
            config = callbacks.on_load_model_config()[0]
        else:
            # Always load from the bundled models.json so upstream
            # updates propagate automatically.  User additions belong
            # in extra_models.json (overlay loaded below).
            bundled_models = pathlib.Path(__file__).parent / "models.json"
            with open(bundled_models) as f:
                config = json.loads(f.read())

        # User-level models.json overrides bundled config
        user_models = pathlib.Path(MODELS_FILE)
        if user_models.exists():
            try:
                with open(user_models) as f:
                    config.update(json.loads(f.read()))
            except json.JSONDecodeError as exc:
                logging.getLogger(__name__).warning(
                    f"Failed to load user models config from {user_models}: Invalid JSON - {exc}"
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    f"Failed to load user models config from {user_models}: {exc}"
                )

        # Import OAuth model file paths from main config
        from code_muse.config import (
            CHATGPT_MODELS_FILE,
            CLAUDE_MODELS_FILE,
            COPILOT_MODELS_FILE,
            GEMINI_MODELS_FILE,
        )

        # Build list of extra model sources (user models handled above)
        extra_sources: list[tuple[pathlib.Path, str, bool]] = [
            (pathlib.Path(EXTRA_MODELS_FILE), "extra models", False),
            (pathlib.Path(CHATGPT_MODELS_FILE), "ChatGPT OAuth models", False),
            (pathlib.Path(CLAUDE_MODELS_FILE), "Claude Code OAuth models", True),
            (pathlib.Path(GEMINI_MODELS_FILE), "Gemini OAuth models", False),
            (pathlib.Path(COPILOT_MODELS_FILE), "Copilot models", False),
        ]

        for source_path, label, use_filtered in extra_sources:
            if not source_path.exists():
                continue
            try:
                # Use filtered loading for Claude Code OAuth models to show only latest versions
                if use_filtered:
                    try:
                        from code_muse.plugins.claude_code_oauth.utils import (
                            load_claude_models_filtered,
                        )

                        extra_config = load_claude_models_filtered()
                    except ImportError:
                        # Plugin not available, fall back to standard JSON loading
                        logging.getLogger(__name__).debug(
                            f"claude_code_oauth plugin not available, loading {label} as plain JSON"
                        )
                        with open(source_path) as f:
                            extra_config = json.loads(f.read())
                else:
                    with open(source_path) as f:
                        extra_config = json.loads(f.read())
                config.update(extra_config)
            except json.JSONDecodeError as exc:
                logging.getLogger(__name__).warning(
                    f"Failed to load {label} config from {source_path}: Invalid JSON - {exc}"
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    f"Failed to load {label} config from {source_path}: {exc}"
                )

        # Let plugins add/override models via load_models_config hook
        try:
            from code_muse.callbacks import on_load_models_config

            results = on_load_models_config()
            for result in results:
                if isinstance(result, dict):
                    config.update(result)  # Plugin models override built-in
        except Exception as exc:
            logging.getLogger(__name__).debug(
                f"Failed to load plugin models config: {exc}"
            )

        # --- End original loading logic ---

        # Store in cache
        with _models_config_lock:
            _models_config_cache = (config, fingerprint)
        return config

    @staticmethod
    def get_model(model_name: str, config: dict[str, Any]) -> Any:
        """Returns a configured model instance based on the provided name and config.

        API key validation happens naturally within each model type's initialization,
        which emits warnings and returns None if keys are missing.
        """
        model_config = config.get(model_name)
        if not model_config:
            raise ValueError(f"Model '{model_name}' not found in configuration.")

        model_type = model_config.get("type")
        provider_identity = resolve_provider_identity(model_name, model_config)

        # Check for plugin-registered model provider classes first
        if model_type in _CUSTOM_MODEL_PROVIDERS:
            provider_class = _CUSTOM_MODEL_PROVIDERS[model_type]
            try:
                return provider_class(
                    model_name=model_name, model_config=model_config, config=config
                )
            except Exception as e:
                logger.error(f"Custom model provider '{model_type}' failed: {e}")
                return None

        if model_type == "gemini":
            api_key = get_api_key("GEMINI_API_KEY")
            if not api_key:
                emit_warning(
                    f"GEMINI_API_KEY is not set (check config or environment); skipping Gemini model '{model_config.get('name')}'."
                )
                return None

            model = GeminiModel(model_name=model_config["name"], api_key=api_key)
            return model

        elif model_type == "openai":
            api_key = get_api_key("OPENAI_API_KEY")
            if not api_key:
                emit_warning(
                    f"OPENAI_API_KEY is not set (check config or environment); skipping OpenAI model '{model_config.get('name')}'."
                )
                return None

            provider = make_openai_provider(provider_identity, api_key=api_key)
            model = OpenAIChatModel(model_name=model_config["name"], provider=provider)
            if "codex" in model_name:
                model = OpenAIResponsesModel(
                    model_name=model_config["name"], provider=provider
                )
            return model

        elif model_type == "anthropic":
            api_key = get_api_key("ANTHROPIC_API_KEY")
            if not api_key:
                emit_warning(
                    f"ANTHROPIC_API_KEY is not set (check config or environment); skipping Anthropic model '{model_config.get('name')}'."
                )
                return None

            # Use the same caching client as claude_code models
            verify = get_cert_bundle_path()
            http2_enabled = get_http2()

            client = ClaudeCacheAsyncClient(
                verify=verify,
                timeout=180,
                http2=http2_enabled,
            )

            # Check if interleaved thinking is enabled for this model
            # Only applies to Claude 4 models (Opus 4.5, Opus 4.1, Opus 4, Sonnet 4)
            from code_muse.config import get_effective_model_settings

            effective_settings = get_effective_model_settings(model_name)
            interleaved_thinking = effective_settings.get("interleaved_thinking", False)

            beta_header = _build_anthropic_beta_header(
                model_config, interleaved_thinking=interleaved_thinking
            )
            default_headers = {}
            if beta_header:
                default_headers["anthropic-beta"] = beta_header

            anthropic_client = AsyncAnthropic(
                api_key=api_key,
                http_client=client,
                default_headers=default_headers if default_headers else None,
            )

            # Ensure cache_control is injected at the Anthropic SDK layer
            patch_anthropic_client_messages(anthropic_client)

            provider = make_anthropic_provider(
                provider_identity, anthropic_client=anthropic_client
            )
            return AnthropicModel(model_name=model_config["name"], provider=provider)

        elif model_type == "custom_anthropic":
            url, headers, verify, api_key, timeout = get_custom_config(model_config)
            if not api_key:
                emit_warning(
                    f"API key is not set for custom Anthropic endpoint; skipping model '{model_config.get('name')}'."
                )
                return None

            # Use the same caching client as claude_code models
            if verify is None:
                verify = get_cert_bundle_path()

            http2_enabled = get_http2()

            client = ClaudeCacheAsyncClient(
                headers=headers,
                verify=verify,
                timeout=timeout if timeout is not None else 180,
                http2=http2_enabled,
            )

            # Check if interleaved thinking is enabled for this model
            from code_muse.config import get_effective_model_settings

            effective_settings = get_effective_model_settings(model_name)
            interleaved_thinking = effective_settings.get("interleaved_thinking", False)

            beta_header = _build_anthropic_beta_header(
                model_config, interleaved_thinking=interleaved_thinking
            )
            default_headers = {}
            if beta_header:
                default_headers["anthropic-beta"] = beta_header

            anthropic_client = AsyncAnthropic(
                base_url=url,
                http_client=client,
                api_key=api_key,
                default_headers=default_headers if default_headers else None,
            )

            # Ensure cache_control is injected at the Anthropic SDK layer
            patch_anthropic_client_messages(anthropic_client)

            provider = make_anthropic_provider(
                provider_identity, anthropic_client=anthropic_client
            )
            return AnthropicModel(model_name=model_config["name"], provider=provider)
        # NOTE: 'claude_code' model type is now handled by the claude_code_oauth plugin
        # via the register_model_type callback. See plugins/claude_code_oauth/register_callbacks.py

        elif model_type == "azure_openai":
            azure_endpoint_config = model_config.get("azure_endpoint")
            if not azure_endpoint_config:
                raise ValueError(
                    "Azure OpenAI model type requires 'azure_endpoint' in its configuration."
                )
            azure_endpoint = azure_endpoint_config
            if azure_endpoint_config.startswith("$"):
                azure_endpoint = get_api_key(azure_endpoint_config[1:])
            if not azure_endpoint:
                emit_warning(
                    f"Azure OpenAI endpoint '{azure_endpoint_config[1:] if azure_endpoint_config.startswith('$') else azure_endpoint_config}' not found (check config or environment); skipping model '{model_config.get('name')}'."
                )
                return None

            api_version_config = model_config.get("api_version")
            if not api_version_config:
                raise ValueError(
                    "Azure OpenAI model type requires 'api_version' in its configuration."
                )
            api_version = api_version_config
            if api_version_config.startswith("$"):
                api_version = get_api_key(api_version_config[1:])
            if not api_version:
                emit_warning(
                    f"Azure OpenAI API version '{api_version_config[1:] if api_version_config.startswith('$') else api_version_config}' not found (check config or environment); skipping model '{model_config.get('name')}'."
                )
                return None

            api_key_config = model_config.get("api_key")
            if not api_key_config:
                raise ValueError(
                    "Azure OpenAI model type requires 'api_key' in its configuration."
                )
            api_key = api_key_config
            if api_key_config.startswith("$"):
                api_key = get_api_key(api_key_config[1:])
            if not api_key:
                emit_warning(
                    f"Azure OpenAI API key '{api_key_config[1:] if api_key_config.startswith('$') else api_key_config}' not found (check config or environment); skipping model '{model_config.get('name')}'."
                )
                return None

            # Configure max_retries for the Azure client, defaulting if not specified in config
            azure_max_retries = model_config.get("max_retries", 2)

            azure_client = AsyncAzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_version=api_version,
                api_key=api_key,
                max_retries=azure_max_retries,
            )
            provider = make_openai_provider(
                provider_identity, openai_client=azure_client
            )
            return OpenAIChatModel(model_name=model_config["name"], provider=provider)

        elif model_type == "custom_openai":
            url, headers, verify, api_key, timeout = get_custom_config(model_config)
            client = create_async_client(
                headers=headers,
                verify=verify,
                timeout=timeout if timeout is not None else 180,
            )
            provider_args = {"base_url": url}
            if isinstance(client, httpx.AsyncClient):
                provider_args["http_client"] = client
            if api_key:
                provider_args["api_key"] = api_key
            provider = make_openai_provider(provider_identity, **provider_args)

            # Provider-specific compatibility shims.
            #
            # - Some providers (e.g. crof.ai / kimi) don't support OpenAI's
            #   ``strict: true`` on tool schemas.
            # - Some providers appear to accept tool *calls* in assistant
            #   messages but error when the next request includes tool *results*
            #   with ``role='tool'``. For these providers we degrade tool results
            #   into regular user messages (the model still sees the output and
            #   can continue, but we avoid a hard API failure).
            provider_name = str(model_config.get("provider") or "")
            strip_strict_tools = model_config.get("strict_tools") is False
            tool_results_as_user = provider_name == "crof"
            flatten_tool_calls = provider_name == "crof"

            if strip_strict_tools or tool_results_as_user or flatten_tool_calls:

                class _CompatChatModel(OpenAIChatModel):
                    """OpenAIChatModel with provider compatibility patches."""

                    def _map_tool_definition(self, f):  # type: ignore[override]
                        tool_param = super()._map_tool_definition(f)
                        if strip_strict_tools:
                            tool_param["function"].pop("strict", None)
                        return tool_param

                    def _map_model_response(self, message):  # type: ignore[override]
                        """Optionally flatten tool calls into assistant text.

                        Some OpenAI-compatible providers accept tool calling in
                        responses but error on tool call/result message wiring
                        in subsequent requests. For these providers we avoid
                        sending `tool_calls` in assistant messages at all and
                        instead embed a human-readable representation in the
                        assistant content.
                        """
                        if not flatten_tool_calls:
                            return super()._map_model_response(message)

                        import orjson as json
                        from openai.types.chat import (
                            ChatCompletionAssistantMessageParam,
                        )
                        from pydantic_ai.messages import TextPart, ToolCallPart

                        chunks: list[str] = []
                        for part in message.parts:
                            if isinstance(part, TextPart):
                                if part.content:
                                    chunks.append(part.content)
                            elif isinstance(part, ToolCallPart):
                                args = part.args
                                if isinstance(args, dict):
                                    args_str = json.dumps(args, option=orjson.OPT_SORT_KEYS)
                                else:
                                    args_str = "" if args is None else str(args)
                                chunks.append(
                                    f"TOOL CALL ({part.tool_name}, id={part.tool_call_id}): {args_str}"
                                )
                            else:
                                # Ignore other part kinds (thinking, builtin, etc.) for provider safety.
                                continue

                        content = "\n\n".join([c for c in chunks if c is not None])
                        return ChatCompletionAssistantMessageParam(
                            role="assistant",
                            content=content or None,
                        )

                    async def _map_user_message(self, message):  # type: ignore[override]
                        # Import locally to keep import-time cost down.
                        from openai.types.chat import (
                            ChatCompletionDeveloperMessageParam,
                            ChatCompletionSystemMessageParam,
                            ChatCompletionToolMessageParam,
                            ChatCompletionUserMessageParam,
                        )
                        from pydantic_ai._utils import (
                            guard_tool_call_id as _guard_tool_call_id,
                        )
                        from pydantic_ai.messages import (
                            RetryPromptPart,
                            SystemPromptPart,
                            ToolReturnPart,
                            UserPromptPart,
                        )
                        from pydantic_ai.profiles.openai import OpenAIModelProfile

                        for part in message.parts:
                            if isinstance(part, SystemPromptPart):
                                system_prompt_role = OpenAIModelProfile.from_profile(
                                    self.profile
                                ).openai_system_prompt_role
                                if system_prompt_role == "developer":
                                    yield ChatCompletionDeveloperMessageParam(
                                        role="developer", content=part.content
                                    )
                                elif system_prompt_role == "user":
                                    yield ChatCompletionUserMessageParam(
                                        role="user", content=part.content
                                    )
                                else:
                                    yield ChatCompletionSystemMessageParam(
                                        role="system", content=part.content
                                    )
                            elif isinstance(part, UserPromptPart):
                                yield await super()._map_user_prompt(part)
                            elif isinstance(part, ToolReturnPart):
                                if tool_results_as_user:
                                    yield ChatCompletionUserMessageParam(
                                        role="user",
                                        content=(
                                            f"TOOL RESULT ({part.tool_name}, id={part.tool_call_id}):\n"
                                            f"{part.model_response_str()}"
                                        ),
                                    )
                                else:
                                    yield ChatCompletionToolMessageParam(
                                        role="tool",
                                        tool_call_id=_guard_tool_call_id(t=part),
                                        content=part.model_response_str(),
                                    )
                            elif isinstance(part, RetryPromptPart):
                                if part.tool_name is None:
                                    yield ChatCompletionUserMessageParam(
                                        role="user", content=part.model_response()
                                    )
                                else:
                                    if tool_results_as_user:
                                        yield ChatCompletionUserMessageParam(
                                            role="user",
                                            content=(
                                                f"TOOL RESULT ({part.tool_name}, id={part.tool_call_id}):\n"
                                                f"{part.model_response()}"
                                            ),
                                        )
                                    else:
                                        yield ChatCompletionToolMessageParam(
                                            role="tool",
                                            tool_call_id=_guard_tool_call_id(t=part),
                                            content=part.model_response(),
                                        )
                            else:
                                raise TypeError(
                                    f"Unsupported request part type: {type(part).__name__}"
                                )

                model = _CompatChatModel(
                    model_name=model_config["name"], provider=provider
                )
            else:
                model = OpenAIChatModel(
                    model_name=model_config["name"], provider=provider
                )
            if model_name == "chatgpt-gpt-5-codex":
                model = OpenAIResponsesModel(model_config["name"], provider=provider)
            return model
        elif model_type == "zai_coding":
            api_key = get_api_key("ZAI_API_KEY")
            if not api_key:
                emit_warning(
                    f"ZAI_API_KEY is not set (check config or environment); skipping ZAI coding model '{model_config.get('name')}'."
                )
                return None
            provider = make_openai_provider(
                provider_identity,
                api_key=api_key,
                base_url="https://api.z.ai/api/coding/paas/v4",
            )
            return ZaiChatModel(
                model_name=model_config["name"],
                provider=provider,
            )
        elif model_type == "zai_api":
            api_key = get_api_key("ZAI_API_KEY")
            if not api_key:
                emit_warning(
                    f"ZAI_API_KEY is not set (check config or environment); skipping ZAI API model '{model_config.get('name')}'."
                )
                return None
            provider = make_openai_provider(
                provider_identity,
                api_key=api_key,
                base_url="https://api.z.ai/api/paas/v4/",
            )
            return ZaiChatModel(
                model_name=model_config["name"],
                provider=provider,
            )

        elif model_type == "custom_gemini":
            url, headers, verify, api_key, timeout = get_custom_config(model_config)
            if not api_key:
                emit_warning(
                    f"API key is not set for custom Gemini endpoint; skipping model '{model_config.get('name')}'."
                )
                return None

            client = create_async_client(
                headers=headers,
                verify=verify,
                timeout=timeout if timeout is not None else 180,
            )
            model = GeminiModel(
                model_name=model_config["name"],
                api_key=api_key,
                base_url=url,
                http_client=client,
            )
            return model
        elif model_type == "cerebras":

            class ZaiCerebrasProvider(CerebrasProvider):
                def model_profile(self, model_name: str) -> ModelProfile | None:
                    profile = super().model_profile(model_name)
                    if model_name.startswith("zai"):
                        from pydantic_ai.profiles.qwen import qwen_model_profile

                        profile = profile.update(qwen_model_profile("qwen-3-coder"))
                    return profile

            url, headers, verify, api_key, timeout = get_custom_config(model_config)
            if not api_key:
                emit_warning(
                    f"API key is not set for Cerebras endpoint; skipping model '{model_config.get('name')}'."
                )
                return None
            # Add Cerebras 3rd party integration header
            headers["X-Cerebras-3rd-Party-Integration"] = "muse"
            # Pass "cerebras" so RetryingAsyncClient knows to ignore Cerebras's
            # absurdly aggressive Retry-After headers (they send 60s!)
            # Note: model_config["name"] is the model's internal name, not the provider
            client = create_async_client(
                headers=headers,
                verify=verify,
                model_name="cerebras",
                timeout=timeout if timeout is not None else 180,
            )
            provider_args = dict(
                api_key=api_key,
                http_client=client,
            )
            provider = ZaiCerebrasProvider(**provider_args)

            return OpenAIChatModel(model_name=model_config["name"], provider=provider)

        elif model_type == "openrouter":
            # Get API key from config, which can be an environment variable reference or raw value
            api_key_config = model_config.get("api_key")
            api_key = None

            if api_key_config:
                if api_key_config.startswith("$"):
                    # It's an environment variable reference
                    env_var_name = api_key_config[1:]  # Remove the $ prefix
                    api_key = get_api_key(env_var_name)
                    if api_key is None:
                        emit_warning(
                            f"OpenRouter API key '{env_var_name}' not found (check config or environment); skipping model '{model_config.get('name')}'."
                        )
                        return None
                else:
                    # It's a raw API key value
                    api_key = api_key_config
            else:
                # No API key in config, try to get it from config or the default environment variable
                api_key = get_api_key("OPENROUTER_API_KEY")
                if api_key is None:
                    emit_warning(
                        f"OPENROUTER_API_KEY is not set (check config or environment); skipping OpenRouter model '{model_config.get('name')}'."
                    )
                    return None

            provider = OpenRouterProvider(api_key=api_key)

            return OpenAIChatModel(model_name=model_config["name"], provider=provider)

        elif model_type == "gemini_oauth":
            # Gemini OAuth models use the Code Assist API (cloudcode-pa.googleapis.com)
            # This is a different API than the standard Generative Language API
            try:
                # Try user plugin first, then built-in plugin
                try:
                    from gemini_oauth.config import GEMINI_OAUTH_CONFIG
                    from gemini_oauth.utils import (
                        get_project_id,
                        get_valid_access_token,
                    )
                except ImportError:
                    from code_muse.plugins.gemini_oauth.config import (
                        GEMINI_OAUTH_CONFIG,
                    )
                    from code_muse.plugins.gemini_oauth.utils import (
                        get_project_id,
                        get_valid_access_token,
                    )
            except ImportError as exc:
                emit_warning(
                    f"Gemini OAuth plugin not available; skipping model '{model_config.get('name')}'. "
                    f"Error: {exc}"
                )
                return None

            # Get a valid access token (refreshing if needed)
            access_token = get_valid_access_token()
            if not access_token:
                emit_warning(
                    f"Failed to get valid Gemini OAuth token; skipping model '{model_config.get('name')}'. "
                    "Run /gemini-auth to re-authenticate."
                )
                return None

            # Get project ID from stored tokens
            project_id = get_project_id()
            if not project_id:
                emit_warning(
                    f"No Code Assist project ID found; skipping model '{model_config.get('name')}'. "
                    "Run /gemini-auth to re-authenticate."
                )
                return None

            # Import the Code Assist model wrapper
            from code_muse.gemini_code_assist import GeminiCodeAssistModel

            # Create the Code Assist model
            model = GeminiCodeAssistModel(
                model_name=model_config["name"],
                access_token=access_token,
                project_id=project_id,
                api_base_url=GEMINI_OAUTH_CONFIG["api_base_url"],
                api_version=GEMINI_OAUTH_CONFIG["api_version"],
            )
            return model

        # NOTE: 'chatgpt_oauth' model type is now handled by the chatgpt_oauth plugin
        # via the register_model_type callback. See plugins/chatgpt_oauth/register_callbacks.py

        elif model_type == "round_robin":
            # Get the list of model names to use in the round-robin
            model_names = model_config.get("models")
            if not model_names or not isinstance(model_names, list):
                raise ValueError(
                    f"Round-robin model '{model_name}' requires a 'models' list in its configuration."
                )

            # Get the rotate_every parameter (default: 1)
            rotate_every = model_config.get("rotate_every", 1)

            # Resolve each model name to an actual model instance
            models = []
            for name in model_names:
                # Recursively get each model using the factory
                model = ModelFactory.get_model(name, config)
                models.append(model)

            # Create and return the round-robin model
            return RoundRobinModel(*models, rotate_every=rotate_every)

        else:
            # Check for plugin-registered model type handlers
            registered_handlers = callbacks.on_register_model_types()
            for handler_info in registered_handlers:
                # Handler info can be a list of dicts or a single dict
                if isinstance(handler_info, list):
                    handlers = handler_info
                else:
                    handlers = [handler_info] if handler_info else []

                for handler_entry in handlers:
                    if not isinstance(handler_entry, dict):
                        continue
                    if handler_entry.get("type") == model_type:
                        handler = handler_entry.get("handler")
                        if callable(handler):
                            try:
                                return handler(model_name, model_config, config)
                            except Exception as e:
                                logger.error(
                                    f"Plugin handler for model type '{model_type}' failed: {e}"
                                )
                                return None

            raise ValueError(f"Unsupported model type: {model_type}")
