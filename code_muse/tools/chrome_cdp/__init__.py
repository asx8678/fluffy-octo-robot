"""Chrome CDP — Chrome DevTools Protocol inspection tool.

Pure-Python CDP client using websockets. No Node.js dependency.
Connects directly to Chrome's remote-debugging WebSocket endpoint.
"""

import asyncio
import json
import logging
import os
import platform
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import RunContext

from code_muse.messaging import emit_info, emit_success

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level caches
# ---------------------------------------------------------------------------
_CHROME_WS: str | None = None
_PERSISTENT_SESSIONS: dict[str, CdpSession] = {}
_ACTIVE_TABS_CACHE: dict[str, str] = {}  # prefix -> targetId
_PAGES_CACHE: list[dict[str, Any]] = []

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ChromeCdpResult(BaseModel):
    """Result of a chrome_cdp command."""

    success: bool = True
    output: str = ""
    screenshot_file: str = ""
    page_list: list[dict[str, Any]] = []
    error: str = ""
    dpr: float = 1.0


class ChromeCdpInfo(BaseModel):
    """Status/info about Chrome CDP availability."""

    available: bool = False
    ws_url: str = ""
    version: str = ""


# ---------------------------------------------------------------------------
# Port / WS discovery
# ---------------------------------------------------------------------------


def _get_devtools_port() -> int:
    """Read Chrome's DevToolsActivePort file from common locations."""
    env_path = os.environ.get("CDP_PORT_FILE")
    if env_path:
        paths = [Path(env_path)]
    else:
        home = Path.home()
        system = platform.system()
        if system == "Darwin":
            base = home / "Library/Application Support"
        else:
            base = home / ".config"

        profiles = [
            "Google/Chrome",
            "google-chrome",
            "BraveSoftware/Brave-Browser",
            "brave-browser",
            "microsoft-edge",
            "chromium",
            "vivaldi",
        ]

        paths: list[Path] = []
        for profile in profiles:
            paths.append(base / profile / "DevToolsActivePort")
            # Flatpak / snap variants
            flatpak_path = (
                ".var/app/com.google.Chrome/config/google-chrome/DevToolsActivePort"
            )
            paths.append(home / flatpak_path)
            paths.append(home / "snap/chromium/common/chromium/DevToolsActivePort")

    for p in paths:
        try:
            text = p.read_text(encoding="utf-8").strip()
            first_line = text.splitlines()[0]
            return int(first_line)
        except Exception:
            continue

    raise FileNotFoundError(
        "Could not find Chrome DevToolsActivePort. "
        "Enable remote debugging (chrome://inspect/#devices) or set CDP_PORT_FILE."
    )


def _get_browser_ws_url(port: int) -> str:
    """Fetch the browser WebSocket URL from Chrome's JSON/version endpoint."""
    import urllib.request

    url = f"http://localhost:{port}/json/version"
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    ws_url = data.get("webSocketDebuggerUrl", "")
    if not ws_url:
        raise RuntimeError("No webSocketDebuggerUrl in /json/version")
    return ws_url


def _discover_browser_ws() -> str:
    """Discover and cache the browser WebSocket URL."""
    global _CHROME_WS
    if _CHROME_WS:
        return _CHROME_WS
    port = _get_devtools_port()
    ws_url = _get_browser_ws_url(port)
    _CHROME_WS = ws_url
    return ws_url


# ---------------------------------------------------------------------------
# HTTP helpers for page listing
# ---------------------------------------------------------------------------


def _fetch_json_list(port: int) -> list[dict[str, Any]]:
    """Fetch the list of open pages from Chrome's JSON/list endpoint."""
    import urllib.request

    url = f"http://localhost:{port}/json/list"
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------


def _is_ws_closed(ws: Any) -> bool:
    """Check whether a websockets connection is closed.
    Compatible with both old and new websockets APIs.
    """
    if hasattr(ws, "closed"):
        return bool(ws.closed)
    import websockets

    return ws.state == websockets.State.CLOSED


async def _ws_connect(ws_url: str) -> Any:
    """Open a WebSocket connection to the given URL."""
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets library not installed. Run: pip install websockets"
        ) from exc

    return await websockets.connect(ws_url, open_timeout=5, close_timeout=5)


async def _send_cdp(
    ws,
    method: str,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
    timeout: float = 10.0,
) -> Any:
    """Send a CDP command and wait for the matching response."""
    msg_id = _next_msg_id()
    payload: dict[str, Any] = {"id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    if session_id is not None:
        payload["sessionId"] = session_id

    future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    _PENDING[msg_id] = future

    try:
        await ws.send(json.dumps(payload))
        msg = await asyncio.wait_for(future, timeout=timeout)
    finally:
        _PENDING.pop(msg_id, None)

    if "error" in msg:
        err_msg = msg["error"].get("message", str(msg["error"]))
        raise RuntimeError(f"CDP error: {err_msg}")
    return msg.get("result", {})


_MSG_COUNTER = 0
_PENDING: dict[int, asyncio.Future[Any]] = {}


def _next_msg_id() -> int:
    global _MSG_COUNTER
    _MSG_COUNTER += 1
    return _MSG_COUNTER


async def _read_ws_loop(ws, event_buffers: dict[str, list] | None = None) -> None:
    """Background task: reads WS messages, resolves futures, buffers events."""
    import websockets

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            if msg_id is not None and msg_id in _PENDING:
                future = _PENDING.pop(msg_id)
                if not future.done():
                    future.set_result(msg)

            # Route events to buffers (console logs, network events, etc.)
            if method and event_buffers is not None:
                if method in event_buffers:
                    event_buffers[method].append(params)
                # Also store under a wildcard for generic "all events"
                if "*" in event_buffers:
                    event_buffers["*"].append({"method": method, "params": params})
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception:
        logger.exception("chrome_cdp WS read loop error")
    finally:
        for fut in list(_PENDING.values()):
            if not fut.done():
                fut.cancel()
        _PENDING.clear()


# ---------------------------------------------------------------------------
# CdpSession
# ---------------------------------------------------------------------------


class CdpSession:
    """Persistent CDP session for a single target tab."""

    def __init__(self, target_id: str):
        self.target_id = target_id
        self.ws: Any | None = None
        self.session_id: str | None = None
        self._read_task: asyncio.Task[Any] | None = None
        # Event buffers for monitoring
        self._event_buffers: dict[str, list[dict]] = {}
        self._console_capturing = False
        self._network_capturing = False

    async def enable_console_capture(self) -> None:
        """Start capturing console logs from the page."""
        if self._console_capturing:
            return
        self._event_buffers["Runtime.consoleAPICalled"] = []
        self._event_buffers["Runtime.exceptionThrown"] = []
        await self.send("Runtime.enable")
        self._console_capturing = True

    async def get_console_logs(self) -> list[dict]:
        """Get captured console logs and clear the buffer."""
        logs = []
        for entry in self._event_buffers.get("Runtime.consoleAPICalled", []):
            args = entry.get("args", [])
            text = " ".join(
                a.get("value", str(a)) if isinstance(a, dict) else str(a) for a in args
            )
            level = entry.get("type", "log")
            logs.append({"level": level, "text": text})
        self._event_buffers["Runtime.consoleAPICalled"] = []

        exceptions = []
        for exc in self._event_buffers.get("Runtime.exceptionThrown", []):
            details = exc.get("exceptionDetails", {})
            text = details.get("text", "") or str(
                details.get("exception", {}).get("description", "")
            )
            exceptions.append({"level": "exception", "text": text})
        self._event_buffers["Runtime.exceptionThrown"] = []

        return logs + exceptions

    async def enable_network_capture(self) -> None:
        """Start capturing network requests."""
        if self._network_capturing:
            return
        self._event_buffers["Network.requestWillBeSent"] = []
        self._event_buffers["Network.responseReceived"] = []
        self._event_buffers["Network.loadingFailed"] = []
        await self.send("Network.enable")
        self._network_capturing = True

    async def disable_network_capture(self) -> None:
        """Stop capturing network requests."""
        if not self._network_capturing:
            return
        import contextlib

        with contextlib.suppress(Exception):
            await self.send("Network.disable")
        self._network_capturing = False

    async def get_network_activity(self) -> list[dict]:
        """Get captured network activity and clear the buffer."""
        # Combine requests and responses by requestId
        requests = {
            r["requestId"]: {
                "url": r.get("request", {}).get("url", ""),
                "method": r.get("request", {}).get("method", ""),
                "type": r.get("type", ""),
                "timestamp": r.get("timestamp", 0),
            }
            for r in self._event_buffers.get("Network.requestWillBeSent", [])
        }
        responses = {
            r["requestId"]: {
                "status": r.get("response", {}).get("status", 0),
                "status_text": r.get("response", {}).get("statusText", ""),
                "content_type": r.get("response", {}).get("mimeType", ""),
                "size": r.get("response", {}).get("transferSize", 0),
            }
            for r in self._event_buffers.get("Network.responseReceived", [])
        }
        failures = {
            f["requestId"]: f.get("errorText", "Failed")
            for f in self._event_buffers.get("Network.loadingFailed", [])
        }

        # Merge
        all_ids = set(requests) | set(responses) | set(failures)
        merged = []
        for rid in all_ids:
            entry = {"request_id": rid}
            entry.update(requests.get(rid, {}))
            entry.update(responses.get(rid, {}))
            if rid in failures:
                entry["error"] = failures[rid]
            merged.append(entry)

        # Clear buffers
        for key in (
            "Network.requestWillBeSent",
            "Network.responseReceived",
            "Network.loadingFailed",
        ):
            self._event_buffers[key] = []

        return merged

    async def get_source(self, url: str) -> str:
        """Get the source code of a script or style by URL."""
        # Try as script source first
        try:
            result = await self.send("Debugger.getScriptSource", {"scriptId": url})
            return result.get("scriptSource", "")
        except Exception:
            pass
        # Try getting source from page via eval (fetch the URL content)
        result = await self.eval(f"fetch({json.dumps(url)}).then(r => r.text())")
        return result

    async def ensure_connected(self) -> None:
        """Connect to the browser WS, attach to target, and store sessionId."""
        if self.ws is not None and not _is_ws_closed(self.ws):
            return

        browser_ws = _discover_browser_ws()
        self.ws = await _ws_connect(browser_ws)
        self._read_task = asyncio.create_task(
            _read_ws_loop(self.ws, self._event_buffers)
        )

        result = await _send_cdp(
            self.ws,
            "Target.attachToTarget",
            {"targetId": self.target_id, "flatten": True},
        )
        self.session_id = result.get("sessionId")
        if not self.session_id:
            raise RuntimeError("No sessionId returned from attachToTarget")

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> Any:
        """Send a CDP command via the target session."""
        if self.ws is None or _is_ws_closed(self.ws):
            await self.ensure_connected()
        return await _send_cdp(
            self.ws, method, params, session_id=self.session_id, timeout=timeout
        )

    async def disconnect(self) -> None:
        """Close the WebSocket and clean up."""
        if self._read_task is not None:
            self._read_task.cancel()
            self._read_task = None
        if self.ws is not None:
            import contextlib

            with contextlib.suppress(Exception):
                await self.ws.close()
            self.ws = None
        self.session_id = None

    async def eval(self, expression: str) -> str:
        """Evaluate a JS expression and return the string result."""
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
        res = result.get("result", {})
        if res.get("subtype") == "error":
            desc = res.get("description", res.get("value", "JS error"))
            raise RuntimeError(desc)
        val = res.get("value")
        return str(val) if val is not None else ""

    async def get_screenshot(self) -> tuple[bytes, float]:
        """Capture a screenshot and return (bytes, dpr)."""
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        b64 = result.get("data", "")
        if not b64:
            raise RuntimeError("Screenshot data empty")
        import base64

        raw = base64.b64decode(b64)

        # Try to fetch DPR
        dpr = 1.0
        try:
            metrics = await self.send("Page.getLayoutMetrics")
            dpr = metrics.get("visualViewport", {}).get("scale", 1.0)
        except Exception:
            pass
        return raw, float(dpr)

    async def get_snapshot(self) -> str:
        """Fetch accessibility tree and return formatted text."""
        result = await self.send("Accessibility.getFullAXTree")
        nodes = result.get("nodes", [])
        if not nodes:
            return "(empty accessibility tree)"
        lines: list[str] = []
        for node in nodes:
            role = node.get("role", {}).get("value", "")
            name = node.get("name", {}).get("value", "")
            if role or name:
                lines.append(f"[{role}] {name}")
        return "\n".join(lines) if lines else "(empty accessibility tree)"

    async def navigate(self, url: str) -> None:
        """Navigate to a URL and wait for load."""
        # Enable Page events first
        await self.send("Page.enable")
        result = await self.send("Page.navigate", {"url": url})
        frame_id = result.get("frameId")
        if not frame_id:
            raise RuntimeError("Navigation failed: no frameId")

        # Wait for loadEventFired via event — but our simple loop only resolves
        # responses, not events. Poll document.readyState instead.
        for _ in range(50):
            ready = await self.eval("document.readyState")
            if ready == "complete":
                return
            await asyncio.sleep(0.2)
        raise RuntimeError("Navigation timeout: page did not reach readyState=complete")

    async def click_selector(self, selector: str) -> None:
        """Click an element via JS."""
        expression = (
            "(function(){"
            "var el=document.querySelector('" + selector.replace("'", "\\'") + "');"
            "if(!el) throw new Error('"
            "Element not found: " + selector.replace("'", "\\'") + "');"
            "el.click();"
            "return true;"
            "})()"
        )
        await self.eval(expression)

    async def click_xy(self, x: int, y: int) -> None:
        """Dispatch a mouse click at (x, y)."""
        await self.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            },
        )
        await self.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            },
        )

    async def type_text(self, text: str) -> None:
        """Insert text into the focused element."""
        await self.send("Input.insertText", {"text": text})

    async def get_html(self, selector: str | None = None) -> str:
        """Get outerHTML of the page or a matched element."""
        if selector:
            expr = (
                "(function(){"
                "var el=document.querySelector('" + selector.replace("'", "\\'") + "');"
                "if(!el) throw new Error('"
                "Element not found: " + selector.replace("'", "\\'") + "');"
                "return el.outerHTML;"
                "})()"
            )
            return await self.eval(expr)
        return await self.eval("document.documentElement.outerHTML")

    async def get_network_entries(self) -> list[dict[str, Any]]:
        """Return performance resource timing entries."""
        raw = await self.eval(
            "JSON.stringify(performance.getEntriesByType('resource').map(e=>{"
            "return {name:e.name,initiatorType:e.initiatorType,duration:e.duration};"
            "}))"
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []


# ---------------------------------------------------------------------------
# Page cache helpers
# ---------------------------------------------------------------------------


def _refresh_page_cache() -> list[dict[str, Any]]:
    """Fetch all pages from Chrome and update caches."""
    global _PAGES_CACHE, _ACTIVE_TABS_CACHE
    port = _get_devtools_port()
    pages = _fetch_json_list(port)
    _PAGES_CACHE = [p for p in pages if p.get("type") == "page"]
    _ACTIVE_TABS_CACHE.clear()
    for idx, page in enumerate(_PAGES_CACHE, start=1):
        target_id = page.get("id", "")
        prefix = f"{idx}"
        _ACTIVE_TABS_CACHE[prefix] = target_id
    return _PAGES_CACHE


def _resolve_target(prefix: str) -> str:
    """Resolve a short prefix to a full targetId."""
    if prefix in _ACTIVE_TABS_CACHE:
        return _ACTIVE_TABS_CACHE[prefix]
    # Try refreshing
    _refresh_page_cache()
    if prefix in _ACTIVE_TABS_CACHE:
        return _ACTIVE_TABS_CACHE[prefix]
    raise ValueError(f"Unknown target prefix '{prefix}'. Run list first.")


def _get_or_create_session(target_id: str) -> CdpSession:
    """Return an existing CdpSession or create a new one."""
    if target_id not in _PERSISTENT_SESSIONS:
        _PERSISTENT_SESSIONS[target_id] = CdpSession(target_id)
    return _PERSISTENT_SESSIONS[target_id]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_chrome_cdp(agent):
    """Register the chrome_cdp unified tool on the agent."""

    @agent.tool
    async def chrome_cdp(
        context: RunContext,
        command: str,
        target: str = "",
        expression: str = "",
        selector: str = "",
        url: str = "",
        x: int = 0,
        y: int = 0,
        text: str = "",
    ) -> ChromeCdpResult | ChromeCdpInfo | dict[str, Any]:
        """Inspect, debug, and interact with web pages via Chrome DevTools Protocol.

        Connects to your running Chrome browser — like having the DevTools
        inspector programmatically. Use it to see what's happening on any page,
        debug rendering issues, catch console errors, monitor network requests,
        and interact with the page.

        ─── QUICK START ───

        1. Check Chrome:  chrome_cdp(command="status")
        2. List tabs:     chrome_cdp(command="list")
        3. Snapshot:      chrome_cdp(command="snap", target="1")
        4. Screenshot:    chrome_cdp(command="shot", target="1")
        5. Console:       chrome_cdp(command="console", target="1")
        6. Evaluate JS:   chrome_cdp(command="eval", target="1", expression="document.title")

        ─── FULL CAPABILITY GUIDE ───

        Call `chrome_cdp(command="guide")` at any time to see the complete
        capability catalog with examples. Or read the command breakdown below.

        📄 PAGE INSPECTION
          list / ls       → List all open tabs with numeric prefixes
          shot / screenshot → Save a PNG screenshot; returns file path + DPR
          snap / snapshot → Accessibility tree (how screen readers see the page)
          html            → Get full page HTML or a specific element's outerHTML
          source          → Get JS/CSS source code by URL or fetch-page path

        💻 JAVASCRIPT RUNTIME
          eval            → Execute any JavaScript: read state, call functions,
                             inspect localStorage, cookies, component props, etc.
                             Example: eval "JSON.stringify(window.__INITIAL_STATE__)"
                             Example: eval "document.querySelector('h1').textContent"
          console / logs  → Capture console.log/warn/error/info output from the page.
                             Also catches unhandled JS exceptions. Use AFTER page
                             interactions to see if anything broke.

        🌐 NETWORK
          net / network   → Performance API resource entries (duration, size, type)
          network_start   → Begin REAL-TIME capture of all HTTP requests/responses
          network_captured→ Show captured requests with method, status, URL, size, errors
          network_stop    → Stop network capture

        🖱️ PAGE INTERACTION
          nav / navigate  → Navigate to a URL and wait for page load
          click           → Click an element by CSS selector
          clickxy         → Click at CSS pixel coordinates (x, y)
          type            → Type text into the focused element (works in cross-origin iframes!)

        🔧 DEBUGGING
          status          → Check if Chrome remote debugging is available
          guide           → Show this complete capability guide with examples

        ─── ADVANCED WORKFLOWS ───

        Debug a dev server:
          chrome_cdp(command="nav", target="1", url="http://localhost:5173")
          chrome_cdp(command="shot", target="1")
          chrome_cdp(command="console", target="1")

        Debug a failed API call:
          chrome_cdp(command="network_start", target="1")
          chrome_cdp(command="click", target="1", selector="button[type=submit]")
          chrome_cdp(command="network_captured", target="1")
          chrome_cdp(command="network_stop", target="1")

        Check page state:
          chrome_cdp(command="eval", target="1", expression="navigator.userAgent")
          chrome_cdp(command="eval", target="1", expression="JSON.stringify(localStorage)")
          chrome_cdp(command="eval", target="1", expression="document.cookie")

        Args:
            command: What to do — see guide above for full list.
            target: Tab prefix from `list` output (e.g. "1", "2").
            expression: JavaScript expression for `eval`.
            selector: CSS selector for `click` or scoped `html`.
            url: URL for `navigate` or `source`.
            x: X coordinate in CSS pixels for `clickxy`.
            y: Y coordinate in CSS pixels for `clickxy`.
            text: Text to type for `type`.

        Returns:
            ChromeCdpResult with success/error status and output.
        """
        cmd = command.lower().strip()

        # --- status ---
        if cmd in ("status",):
            try:
                ws_url = _discover_browser_ws()
                import urllib.request

                port = _get_devtools_port()
                version_url = f"http://localhost:{port}/json/version"
                with urllib.request.urlopen(version_url, timeout=3) as resp:  # noqa: S310
                    data = json.loads(resp.read().decode("utf-8"))
                version = data.get("Browser", "")
                emit_info(f"chrome_cdp: Chrome available — {version}")
                return ChromeCdpInfo(available=True, ws_url=ws_url, version=version)
            except Exception as exc:
                logger.exception("chrome_cdp status check failed")
                return ChromeCdpInfo(
                    available=False, ws_url="", version=f"Not available: {exc}"
                )

        # --- guide ---
        if cmd in ("guide", "help", "commands"):
            guide_text = (
                "╔══════════════════════════════════════════════════════════╗\n"
                "║         chrome_cdp — Complete Capability Guide          ║\n"
                "╚══════════════════════════════════════════════════════════╝\n"
                "\n"
                "📄 PAGE INSPECTION\n"
                '  chrome_cdp(command="list")               — List open tabs\n'
                '  chrome_cdp(command="shot", target="1")  — Screenshot (temp file)\n'
                '  chrome_cdp(command="snap", target="1")  — Accessibility tree\n'
                '  chrome_cdp(command="html", target="1")  — Full page HTML\n'
                '  chrome_cdp(command="html", target="1", selector="#main")  — Element HTML\n'
                '  chrome_cdp(command="source", target="1", url="https://...")  — JS/CSS source\n'
                "\n"
                "💻 JAVASCRIPT RUNTIME\n"
                '  chrome_cdp(command="eval", target="1", expression="document.title")\n'
                '  chrome_cdp(command="eval", target="1", expression="JSON.stringify(localStorage)")\n'
                '  chrome_cdp(command="eval", target="1", expression="document.cookie")\n'
                '  chrome_cdp(command="eval", target="1", expression="navigator.userAgent")\n'
                '  chrome_cdp(command="eval", target="1", expression="window.innerWidth")  — viewport size\n'
                '  chrome_cdp(command="console", target="1")  — Capture console logs/errors\n'
                "\n"
                "🌐 NETWORK DIAGNOSTICS\n"
                '  chrome_cdp(command="net", target="1")         — Resource timing entries\n'
                '  chrome_cdp(command="network_start", target="1")  — Begin HTTP monitoring\n'
                '  chrome_cdp(command="network_captured", target="1")  — View captured requests\n'
                '  chrome_cdp(command="network_stop", target="1")     — Stop monitoring\n'
                "\n"
                "🖱️ PAGE INTERACTION\n"
                '  chrome_cdp(command="nav", target="1", url="https://...")   — Navigate\n'
                '  chrome_cdp(command="click", target="1", selector="button")  — Click element\n'
                '  chrome_cdp(command="clickxy", target="1", x=100, y=200)     — Click at coords\n'
                '  chrome_cdp(command="type", target="1", text="hello")         — Type text\n'
                "\n"
                "🔧 SYSTEM\n"
                '  chrome_cdp(command="status")        — Check Chrome availability\n'
                '  chrome_cdp(command="guide")         — Show this guide\n'
                "\n"
                "─── TYPICAL DEBUGGING WORKFLOW ───\n"
                "  # After starting a dev server:\n"
                '  1. chrome_cdp(command="status")\n'
                '  2. chrome_cdp(command="list")\n'
                '  3. chrome_cdp(command="nav", target="1", url="http://localhost:3000")\n'
                '  4. chrome_cdp(command="shot", target="1")\n'
                '  5. chrome_cdp(command="console", target="1")\n'
                '  6. chrome_cdp(command="snap", target="1")\n'
                "\n"
                "  ─ or debug a failing API call ─\n"
                '  1. chrome_cdp(command="network_start", target="1")\n'
                "  2. [interact with the page]\n"
                '  3. chrome_cdp(command="network_captured", target="1")\n'
                '  4. chrome_cdp(command="network_stop", target="1")\n'
                "\n"
                "─── TIPS ───\n"
                "  • The first connection to a tab may show 'Allow debugging?' — approve it once.\n"
                "  • Screenshots are saved to temp files; the path is returned in output.\n"
                "  • DPR (device pixel ratio) affects coordinates: CSS px = screenshot px / DPR.\n"
                "  • Use `console` AFTER interactions to catch post-action errors.\n"
                "  • Network capture starts fresh when you call network_start.\n"
            )
            return ChromeCdpResult(success=True, output=guide_text)

        # --- list / ls ---
        if cmd in ("list", "ls"):
            try:
                pages = _refresh_page_cache()
                page_list: list[dict[str, Any]] = []
                for idx, page in enumerate(pages, start=1):
                    title = page.get("title", "")
                    url = page.get("url", "")
                    target_id = page.get("id", "")
                    page_list.append(
                        {
                            "prefix": str(idx),
                            "title": title,
                            "url": url,
                            "target_id": target_id,
                        }
                    )
                return ChromeCdpResult(
                    success=True,
                    output=f"{len(page_list)} tab(s) open",
                    page_list=page_list,
                )
            except Exception as exc:
                logger.exception("chrome_cdp list failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # All remaining commands need a target
        if not target:
            return ChromeCdpResult(
                success=False,
                error="Missing 'target' parameter. Run list first to get a prefix.",
            )

        try:
            target_id = _resolve_target(target)
            session = _get_or_create_session(target_id)
            await session.ensure_connected()
        except Exception as exc:
            logger.exception("chrome_cdp connect failed for target=%s", target)
            return ChromeCdpResult(success=False, error=str(exc))

        # --- shot / screenshot ---
        if cmd in ("shot", "screenshot"):
            try:
                screenshot_bytes, dpr = await session.get_screenshot()
                fd, path = tempfile.mkstemp(prefix="chrome_cdp_shot_", suffix=".png")
                with open(fd, "wb") as f:
                    f.write(screenshot_bytes)
                emit_success(f"chrome_cdp screenshot saved: {path}")
                return ChromeCdpResult(
                    success=True,
                    output=f"Screenshot saved to {path} (DPR={dpr})",
                    screenshot_file=path,
                    dpr=dpr,
                )
            except Exception as exc:
                logger.exception("chrome_cdp screenshot failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- snap / snapshot ---
        if cmd in ("snap", "snapshot"):
            try:
                tree = await session.get_snapshot()
                return ChromeCdpResult(success=True, output=tree)
            except Exception as exc:
                logger.exception("chrome_cdp snapshot failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- eval ---
        if cmd in ("eval",):
            if not expression:
                return ChromeCdpResult(
                    success=False, error="Missing 'expression' for eval command."
                )
            try:
                result = await session.eval(expression)
                return ChromeCdpResult(success=True, output=result)
            except Exception as exc:
                logger.exception("chrome_cdp eval failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- html ---
        if cmd in ("html",):
            try:
                html = await session.get_html(selector if selector else None)
                # Truncate very large HTML
                if len(html) > 100_000:
                    html = html[:100_000] + "\n... (truncated)"
                return ChromeCdpResult(success=True, output=html)
            except Exception as exc:
                logger.exception("chrome_cdp html failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- nav / navigate ---
        if cmd in ("nav", "navigate"):
            if not url:
                return ChromeCdpResult(
                    success=False, error="Missing 'url' for navigate command."
                )
            try:
                await session.navigate(url)
                return ChromeCdpResult(success=True, output=f"Navigated to {url}")
            except Exception as exc:
                logger.exception("chrome_cdp navigate failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- net / network ---
        if cmd in ("net", "network"):
            try:
                entries = await session.get_network_entries()
                lines = [
                    f"{e.get('name', '')} [{e.get('initiatorType', '')}]"
                    f" {e.get('duration', 0):.1f}ms"
                    for e in entries
                ]
                return ChromeCdpResult(
                    success=True,
                    output=f"{len(entries)} resource(s)\n" + "\n".join(lines[:200]),
                )
            except Exception as exc:
                logger.exception("chrome_cdp network failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- console ---
        if cmd in ("console", "logs"):
            try:
                await session.enable_console_capture()
                # Wait a moment for any existing console events
                await asyncio.sleep(0.5)
                logs = await session.get_console_logs()
                if not logs:
                    return ChromeCdpResult(
                        success=True, output="(no console output captured)"
                    )
                lines = []
                for entry in logs:
                    level = entry.get("level", "log")
                    text = entry.get("text", "")
                    lines.append(f"[{level}] {text}")
                return ChromeCdpResult(success=True, output="\n".join(lines))
            except Exception as exc:
                logger.exception("chrome_cdp console failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- network_start ---
        if cmd in ("network_start",):
            try:
                await session.enable_network_capture()
                return ChromeCdpResult(success=True, output="Network capture started")
            except Exception as exc:
                logger.exception("chrome_cdp network_start failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- network_stop ---
        if cmd in ("network_stop",):
            try:
                await session.disable_network_capture()
                return ChromeCdpResult(success=True, output="Network capture stopped")
            except Exception as exc:
                return ChromeCdpResult(success=False, error=str(exc))

        # --- network_captured ---
        if cmd in ("network_captured",):
            try:
                activity = await session.get_network_activity()
                if not activity:
                    return ChromeCdpResult(
                        success=True, output="(no network activity captured)"
                    )
                lines = []
                for entry in activity[:100]:  # cap at 100 entries
                    url = entry.get("url", "")[:80]
                    method = entry.get("method", "?")
                    status = entry.get("status", "?")
                    size = entry.get("size", "?")
                    error = entry.get("error", "")
                    if error:
                        lines.append(f"{method} {status} {size}B FAIL:{error} {url}")
                    else:
                        lines.append(f"{method} {status} {size}B {url}")
                return ChromeCdpResult(success=True, output="\n".join(lines))
            except Exception as exc:
                logger.exception("chrome_cdp network_captured failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- source ---
        if cmd in ("source",):
            if not url:
                return ChromeCdpResult(
                    success=False,
                    error="Missing 'url' for source command. "
                    "Pass the script URL or src path.",
                )
            try:
                src = await session.get_source(url)
                return ChromeCdpResult(success=True, output=src)
            except Exception as exc:
                logger.exception("chrome_cdp source failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- click ---
        if cmd in ("click",):
            if not selector:
                return ChromeCdpResult(
                    success=False, error="Missing 'selector' for click command."
                )
            try:
                await session.click_selector(selector)
                return ChromeCdpResult(
                    success=True, output=f"Clicked element: {selector}"
                )
            except Exception as exc:
                logger.exception("chrome_cdp click failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- clickxy ---
        if cmd in ("clickxy",):
            try:
                await session.click_xy(x, y)
                return ChromeCdpResult(success=True, output=f"Clicked at ({x}, {y})")
            except Exception as exc:
                logger.exception("chrome_cdp clickxy failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # --- type ---
        if cmd in ("type",):
            if not text:
                return ChromeCdpResult(
                    success=False, error="Missing 'text' for type command."
                )
            try:
                await session.type_text(text)
                return ChromeCdpResult(
                    success=True, output=f"Typed text ({len(text)} chars)"
                )
            except Exception as exc:
                logger.exception("chrome_cdp type failed")
                return ChromeCdpResult(success=False, error=str(exc))

        # Unknown command
        return ChromeCdpResult(
            success=False,
            error=(
                f"Unknown command '{command}'. "
                "Use: status, list, shot, snap, eval, "
                "html, nav, net, console, network_start, network_captured, "
                "network_stop, source, click, clickxy, type."
            ),
        )

    return chrome_cdp


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def cleanup_all_sessions() -> None:
    """Disconnect all persistent CDP sessions. Called on shutdown."""
    global _CHROME_WS
    for session in list(_PERSISTENT_SESSIONS.values()):
        await session.disconnect()
    _PERSISTENT_SESSIONS.clear()
    _ACTIVE_TABS_CACHE.clear()
    _PAGES_CACHE.clear()
    _CHROME_WS = None


def _sync_cleanup() -> None:
    """Synchronous cleanup wrapper for atexit/shutdown."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(cleanup_all_sessions())
    except RuntimeError:
        pass  # No running loop, connections will be cleaned on process exit


# Register startup callback for availability check
from code_muse.callbacks import register_callback  # noqa: E402
from code_muse.tools.chrome_cdp.register_callbacks import (  # noqa: E402
    register as _register_chrome_cdp_callbacks,
)

_register_chrome_cdp_callbacks()

# Register shutdown cleanup
register_callback("shutdown", _sync_cleanup)
