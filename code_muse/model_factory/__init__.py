"""Model factory package — backward-compatible entry point.

This package was refactored from a single ``model_factory.py`` into
submodules for maintainability.  All previously-public names are
re-exported here so that existing ``from code_muse.model_factory import
…`` statements continue to work identically.

Submodule layout
----------------
_custom_config     Custom endpoint parsing (``get_custom_config``)
_config_loader     Models config loading with caching (``load_models_config``)
_compat_model      OpenAI compat shims (``CompatChatModel``)
_model_builders   Per-type builder functions + ``ZaiCerebrasProvider``
_plugin_registry   Plugin model-provider registry
"""

import logging
from typing import Any

from code_muse import callbacks
from code_muse._models_config_utils import (
    invalidate_models_config_cache as invalidate_models_config_cache,  # noqa: F401
)
from code_muse.model_factory._config_loader import load_models_config
from code_muse.model_factory._custom_config import (
    get_custom_config as get_custom_config,  # noqa: F401
)
from code_muse.model_factory._model_builders import (
    _build_anthropic_model,
    _build_azure_openai_model,
    _build_cerebras_model,
    _build_custom_anthropic_model,
    _build_custom_gemini_model,
    _build_custom_openai_model,
    _build_gemini_model,
    _build_gemini_oauth_model,
    _build_openai_model,
    _build_openrouter_model,
    _build_round_robin_model,
    _build_zai_api_model,
    _build_zai_coding_model,
)
from code_muse.model_factory._plugin_registry import _CUSTOM_MODEL_PROVIDERS
from code_muse.model_factory_settings import (  # noqa: F401
    _ANTHROPIC_MODEL_TYPES,
    CONTEXT_1M_BETA,
    ZaiChatModel,
    _build_anthropic_beta_header,
    _is_anthropic_model,
    get_api_key,
    make_model_settings,
)
from code_muse.provider_identity import resolve_provider_identity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ModelFactory — thin wrapper that delegates to submodules
# ---------------------------------------------------------------------------


class ModelFactory:
    """A factory for creating and managing different AI models."""

    @staticmethod
    def load_config() -> dict[str, Any]:
        return load_models_config()

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

        # Dispatch to builder functions
        builders = {
            "gemini": _build_gemini_model,
            "openai": _build_openai_model,
            "anthropic": _build_anthropic_model,
            "custom_anthropic": _build_custom_anthropic_model,
            "azure_openai": _build_azure_openai_model,
            "custom_openai": _build_custom_openai_model,
            "zai_coding": _build_zai_coding_model,
            "zai_api": _build_zai_api_model,
            "custom_gemini": _build_custom_gemini_model,
            "cerebras": _build_cerebras_model,
            "openrouter": _build_openrouter_model,
            "gemini_oauth": _build_gemini_oauth_model,
            "round_robin": _build_round_robin_model,
        }

        builder = builders.get(model_type)
        if builder:
            return builder(
                model_name=model_name,
                model_config=model_config,
                config=config,
                provider_identity=provider_identity,
                model_factory_get_model=ModelFactory.get_model,
            )

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
