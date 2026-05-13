"""Config: security settings."""

import os
from pathlib import Path

import code_muse.config.parser as _parser


def get_api_key(key_name: str) -> str:
    """Get an API key from muse.cfg.

    Args:
        key_name: The name of the API key (e.g., 'OPENAI_API_KEY')

    Returns:
        The API key value, or empty string if not set
    """
    return _parser.get_value(key_name) or ""


def set_api_key(key_name: str, value: str):
    """Set an API key in muse.cfg.

    Args:
        key_name: The name of the API key (e.g., 'OPENAI_API_KEY')
        value: The API key value (empty string to remove)
    """
    _parser.set_config_value(key_name, value)


def load_api_keys_to_environment():
    """Load all API keys from .env and muse.cfg into environment variables.

    Priority order:
    1. .env file (highest priority) - if present in current directory
    2. muse.cfg - fallback if not in .env
    3. Existing environment variables - preserved if already set

    This should be called on startup to ensure API keys are available.
    """

    api_key_names = [
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CEREBRAS_API_KEY",
        "SYN_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "OPENROUTER_API_KEY",
        "ZAI_API_KEY",
    ]

    # Step 1: Load from .env file if it exists (highest priority)
    # Look for .env in current working directory
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv

            # override=True means .env values take precedence over existing env vars
            load_dotenv(env_file, override=True)
        except ImportError:
            # python-dotenv not installed, skip .env loading
            pass

    # Step 2: Load from muse.cfg, but only if not already set
    # This ensures .env has priority over muse.cfg
    for key_name in api_key_names:
        # Only load from config if not already in environment
        if key_name not in os.environ or not os.environ[key_name]:
            value = get_api_key(key_name)
            if value:
                os.environ[key_name] = value
