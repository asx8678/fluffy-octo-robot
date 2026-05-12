"""Register chrome_cdp startup callbacks."""

from code_muse.callbacks import register_callback


def _get_chrome_cdp_prompt() -> str:
    return """## chrome_cdp — Full Web Debugging Superpower

You have `chrome_cdp` — it connects to the user's running Chrome and gives
you programmatic access to everything Chrome DevTools can do. **Use it
automatically** whenever working on web projects.

### When to use (DON'T ASK — just do it):

- **Verify dev servers** — After starting one, navigate + screenshot to confirm it works
- **Debug rendering** — Screenshot + accessibility snapshot to see what's broken
- **Read console errors** — Check for JS/React/Next.js errors automatically
- **Monitor network** — Enable capture, interact, then inspect all HTTP requests
- **Inspect page state** — Use `eval` to read component state, localStorage, cookies, etc.

### Quick reference — call `chrome_cdp(command="guide")` for full catalog:

```
chrome_cdp(command="status")                 # Is Chrome available?
chrome_cdp(command="list")                    # What tabs are open?
chrome_cdp(command="nav", target="1", url="...")  # Navigate
chrome_cdp(command="shot", target="1")        # Screenshot
chrome_cdp(command="snap", target="1")        # Page structure
chrome_cdp(command="console", target="1")     # Console errors?
chrome_cdp(command="eval", target="1", expression="...")  # Run JS
chrome_cdp(command="network_start", target="1")           # Begin HTTP capture
chrome_cdp(command="network_captured", target="1")        # View captured requests
chrome_cdp(command="click", target="1", selector="...")   # Click element
chrome_cdp(command="type", target="1", text="...")        # Type text
chrome_cdp(command="source", target="1", url="...")       # View source code
```

### Prerequisite
Chrome needs remote debugging: `chrome://inspect/#remote-debugging` toggle ON,
or start with: `google-chrome --remote-debugging-port=9222`
"""


def _check_chrome_cdp_available() -> None:
    """Check Chrome availability on startup."""
    from code_muse.messaging import emit_info, emit_warning

    try:
        import websockets  # noqa: F401
    except ImportError:
        emit_warning(
            "⚠️ chrome_cdp: websockets not installed. Run: pip install websockets"
        )
        return

    emit_info("🔍 chrome_cdp ready — websockets available")


def register() -> None:
    register_callback("startup", _check_chrome_cdp_available)
    register_callback("load_prompt", _get_chrome_cdp_prompt)
