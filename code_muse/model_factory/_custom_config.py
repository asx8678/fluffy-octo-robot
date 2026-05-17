"""Custom endpoint configuration parser.

Extracted from model_factory.py for single-responsibility separation.
Parses custom_endpoint configuration blocks, resolving environment
variable references in URLs, headers, and API keys.
"""

from code_muse.messaging import emit_warning
from code_muse.model_factory_settings import get_api_key


def get_custom_config(model_config):
    """Parse a custom_endpoint configuration block.

    Resolves ``$ENV_VAR`` references in headers and API keys, validates
    the URL field, and normalises timeout values.

    Returns:
        (url, headers, verify, api_key, timeout)

    Raises:
        ValueError: If required fields are missing or timeout is invalid.
    """
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
