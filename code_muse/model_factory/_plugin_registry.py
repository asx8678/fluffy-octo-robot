"""Plugin model provider registry.

Extracted from model_factory.py.  Manages the ``_CUSTOM_MODEL_PROVIDERS``
dict that maps model type strings to provider classes registered by
plugins via the ``on_register_model_providers`` callback.
"""

import logging

logger = logging.getLogger(__name__)

# Registry for custom model provider classes from plugins
_CUSTOM_MODEL_PROVIDERS: dict[str, type] = {}


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
