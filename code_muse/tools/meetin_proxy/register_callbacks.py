"""Register mitmproxy startup callbacks."""

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_warning


def _get_mitmproxy_prompt() -> str:
    """Return mitmproxy usage instructions for the agent prompt."""
    return """## mitmproxy — Network Traffic Capture Tool

You have access to the `mitmproxy` tool that can intercept and inspect HTTP/S traffic.

**When to use it:**
- When a website, API endpoint, or web service isn't working as expected
- When you need to see exactly what data is being sent to/from a provider
- When debugging token counts, request formats, or response shapes
- When you want to verify headers, request bodies, or response payloads
- Any web-related debugging where seeing the raw traffic helps

**How to use it:**
1. Call `mitmproxy(command="start", target_domain="example.com")` to begin capture
2. Perform the actions/requests you want to inspect
3. Call `mitmproxy(command="stop")` to stop capture and get the recorded data
4. Or use `mitmproxy(command="capture", duration_seconds=30)` for a one-shot capture

**Pro tip:** Set `target_domain` to filter traffic (e.g., "anthropic.com",
"openai.com"). Leave it empty to capture all traffic. The proxy runs on localhost
and routes muse's own HTTP clients through it automatically.
"""


def _check_mitmproxy_available() -> None:
    """Verify mitmproxy is installed and available on startup."""
    try:
        import mitmproxy  # noqa: F401
        from mitmproxy.tools.main import mitmdump  # noqa: F401

        emit_info("🔍 mitmproxy available — mitmproxy detected")
    except ImportError:
        emit_warning("⚠️ mitmproxy not available. Install with: pip install mitmproxy")


def register() -> None:
    register_callback("startup", _check_mitmproxy_available)
    register_callback("load_prompt", _get_mitmproxy_prompt)
