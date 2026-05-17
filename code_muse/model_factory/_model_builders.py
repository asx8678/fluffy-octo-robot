"""Model builder functions for each supported model type.

Extracted from model_factory.py.  Each ``_build_<type>_model`` function
handles a single ``model_type`` branch and returns a model instance or
``None`` (on missing API keys, etc.).
"""

import logging

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncAzureOpenAI
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIResponsesModel,
)
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.cerebras import CerebrasProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from code_muse.claude_cache_client import (
    ClaudeCacheAsyncClient,
    patch_anthropic_client_messages,
)
from code_muse.gemini_model import GeminiModel
from code_muse.http_utils import create_async_client, get_cert_bundle_path, get_http2
from code_muse.messaging import emit_warning
from code_muse.model_factory._compat_model import CompatChatModel
from code_muse.model_factory._custom_config import get_custom_config
from code_muse.model_factory_settings import (
    ZaiChatModel,
    _build_anthropic_beta_header,
    get_api_key,
)
from code_muse.provider_identity import (
    make_anthropic_provider,
    make_openai_provider,
)
from code_muse.round_robin_model import RoundRobinModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cerebras provider with Qwen profile override
# ---------------------------------------------------------------------------


class ZaiCerebrasProvider(CerebrasProvider):
    """CerebrasProvider that applies the Qwen profile for ``zai`` models."""

    def model_profile(self, model_name: str) -> ModelProfile | None:
        profile = super().model_profile(model_name)
        if model_name.startswith("zai"):
            from pydantic_ai.profiles.qwen import qwen_model_profile

            profile = profile.update(qwen_model_profile("qwen-3-coder"))
        return profile


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def _build_gemini_model(*, model_name, model_config, config, **_kwargs):
    """Build a Gemini model instance."""
    api_key = get_api_key("GEMINI_API_KEY")
    if not api_key:
        emit_warning(
            f"GEMINI_API_KEY is not set (check config or environment); skipping Gemini model '{model_config.get('name')}'."
        )
        return None

    model = GeminiModel(model_name=model_config["name"], api_key=api_key)
    return model


def _build_openai_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build an OpenAI model instance."""
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        emit_warning(
            f"OPENAI_API_KEY is not set (check config or environment); skipping OpenAI model '{model_config.get('name')}'."
        )
        return None

    provider = make_openai_provider(provider_identity, api_key=api_key)
    model = OpenAIChatModel(model_name=model_config["name"], provider=provider)
    if "codex" in model_name:
        model = OpenAIResponsesModel(model_name=model_config["name"], provider=provider)
    return model


def _build_anthropic_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build an Anthropic (direct API) model instance."""
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


def _build_custom_anthropic_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build a custom Anthropic endpoint model instance."""
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


def _build_azure_openai_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build an Azure OpenAI model instance."""
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
    provider = make_openai_provider(provider_identity, openai_client=azure_client)
    return OpenAIChatModel(model_name=model_config["name"], provider=provider)


def _build_custom_openai_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build a custom OpenAI-compatible endpoint model instance."""
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
        model = CompatChatModel(
            model_name=model_config["name"],
            provider=provider,
            strip_strict_tools=strip_strict_tools,
            tool_results_as_user=tool_results_as_user,
            flatten_tool_calls=flatten_tool_calls,
        )
    else:
        model = OpenAIChatModel(model_name=model_config["name"], provider=provider)
    if model_name == "chatgpt-gpt-5-codex":
        model = OpenAIResponsesModel(model_config["name"], provider=provider)
    return model


def _build_zai_coding_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build a ZAI coding model instance."""
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


def _build_zai_api_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build a ZAI API model instance."""
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


def _build_custom_gemini_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build a custom Gemini endpoint model instance."""
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


def _build_cerebras_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build a Cerebras endpoint model instance."""
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


def _build_openrouter_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build an OpenRouter model instance."""
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


def _build_gemini_oauth_model(
    *, model_name, model_config, config, provider_identity, **_kwargs
):
    """Build a Gemini OAuth (Code Assist) model instance."""
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


def _build_round_robin_model(
    *, model_name, model_config, config, model_factory_get_model, **_kwargs
):
    """Build a round-robin model that delegates to a list of models."""
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
        model = model_factory_get_model(name, config)
        models.append(model)

    # Create and return the round-robin model
    return RoundRobinModel(*models, rotate_every=rotate_every)
