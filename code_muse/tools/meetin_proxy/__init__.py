"""mitmproxy — MITM proxy for provider traffic capture and analysis."""

import orjson as json
from typing import Any

from pydantic import BaseModel
from pydantic_ai import RunContext

from code_muse.messaging import emit_error, emit_info, emit_success
from code_muse.tools.meetin_proxy.proxy_manager import get_manager


class MitmproxyConfig(BaseModel):
    """Configuration for mitmproxy capture session."""

    target_domain: str = ""
    listen_port: int | None = None
    max_req_body: int = 10000
    max_res_body: int = 100000


class MitmproxyResult(BaseModel):
    """Result of a mitmproxy capture session."""

    proxy_port: int
    flow_count: int
    output_path: str
    captured_at: str


class MitmproxyStatus(BaseModel):
    """Current status of the mitmproxy instance."""

    running: bool
    port: int | None = None
    target: str = ""
    flow_count: int = 0


def register_mitmproxy(agent):
    """Register the mitmproxy tool."""

    @agent.tool
    async def mitmproxy(
        context: RunContext,
        command: str,
        target_domain: str = "",
        listen_port: int | None = None,
        max_req_body: int = 10000,
        max_res_body: int = 100000,
        duration_seconds: int | None = None,
    ) -> MitmproxyResult | MitmproxyStatus | dict[str, Any]:
        """Control the mitmproxy MITM capture proxy.

        Commands:
            start   — Spawn mitmdump, set proxy env vars, begin capture.
            stop    — Stop mitmdump, read flows, unset env vars, return results.
            status  — Return current proxy status.
            capture — Convenience: start, optionally wait, then stop and return data.

        Args:
            command: Action to perform — "start", "stop", "status", or "capture".
            target_domain: Only capture traffic matching this domain.
            listen_port: Port to listen on (auto-selected if omitted).
            max_req_body: Maximum request body bytes to record.
            max_res_body: Maximum response body bytes to record.
            duration_seconds: For "capture", seconds to wait before auto-stopping.

        Returns:
            MitmproxyResult on stop/capture, MitmproxyStatus on status/start.
        """
        manager = get_manager()
        config = MitmproxyConfig(
            target_domain=target_domain,
            listen_port=listen_port,
            max_req_body=max_req_body,
            max_res_body=max_res_body,
        )

        if command == "start":
            try:
                port = manager.start(
                    target=config.target_domain,
                    port=config.listen_port,
                    max_req_body=config.max_req_body,
                    max_res_body=config.max_res_body,
                )
                return MitmproxyStatus(
                    running=True,
                    port=port,
                    target=config.target_domain,
                    flow_count=0,
                )
            except Exception as exc:
                emit_error(f"Failed to start mitmproxy: {exc}")
                return {
                    "success": False,
                    "error": str(exc),
                    "command": command,
                }

        elif command == "stop":
            data = manager.stop()
            status = manager.status()
            # After stop, status will show not running
            flow_count = 0
            output_path = ""
            captured_at = ""
            if data and isinstance(data, dict):
                meta = data.get("meta", {})
                flow_count = meta.get("total_flows", 0)
                captured_at = meta.get("captured_at", "")
                # Write a safe temp copy so caller can inspect flows
                import tempfile

                fd, output_path = tempfile.mkstemp(
                    prefix="mitmproxy_result_", suffix=".json"
                )
                with open(fd, "w", encoding="utf-8") as f:
                    f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str).decode())

            if data:
                emit_success(
                    f"mitmproxy stopped. Captured {flow_count} flow(s). "
                    f"Data written to {output_path}"
                )
                return MitmproxyResult(
                    proxy_port=status.get("port") or 0,
                    flow_count=flow_count,
                    output_path=output_path,
                    captured_at=captured_at,
                )
            else:
                emit_info("mitmproxy stopped. No capture data found.")
                return MitmproxyResult(
                    proxy_port=status.get("port") or 0,
                    flow_count=0,
                    output_path="",
                    captured_at="",
                )

        elif command == "status":
            st = manager.status()
            return MitmproxyStatus(
                running=st["running"],
                port=st["port"],
                target=st["target"],
                flow_count=st["flow_count"],
            )

        elif command == "capture":
            try:
                port = manager.start(
                    target=config.target_domain,
                    port=config.listen_port,
                    max_req_body=config.max_req_body,
                    max_res_body=config.max_res_body,
                )
            except Exception as exc:
                emit_error(f"Failed to start mitmproxy: {exc}")
                return {
                    "success": False,
                    "error": str(exc),
                    "command": command,
                }

            if duration_seconds and duration_seconds > 0:
                emit_info(
                    f"mitmproxy capturing for {duration_seconds}s on port {port}..."
                )
                await _async_sleep(duration_seconds)
            else:
                emit_info(
                    f"mitmproxy capturing on port {port}. "
                    "Call mitmproxy with command='stop' when finished."
                )
                return MitmproxyStatus(
                    running=True,
                    port=port,
                    target=config.target_domain,
                    flow_count=0,
                )

            data = manager.stop()
            flow_count = 0
            output_path = ""
            captured_at = ""
            if data and isinstance(data, dict):
                meta = data.get("meta", {})
                flow_count = meta.get("total_flows", 0)
                captured_at = meta.get("captured_at", "")
                import tempfile

                fd, output_path = tempfile.mkstemp(
                    prefix="mitmproxy_result_", suffix=".json"
                )
                with open(fd, "w", encoding="utf-8") as f:
                    f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str).decode())

            if data:
                emit_success(
                    f"mitmproxy capture complete. {flow_count} flow(s). "
                    f"Data: {output_path}"
                )
                return MitmproxyResult(
                    proxy_port=port,
                    flow_count=flow_count,
                    output_path=output_path,
                    captured_at=captured_at,
                )
            else:
                emit_info("mitmproxy capture complete. No data captured.")
                return MitmproxyResult(
                    proxy_port=port,
                    flow_count=0,
                    output_path="",
                    captured_at="",
                )

        else:
            return {
                "success": False,
                "error": (
                    f"Unknown command: {command}. Use start, stop, status, or capture."
                ),
            }

    return mitmproxy


async def _async_sleep(seconds: float) -> None:
    """Async sleep helper."""
    import asyncio

    await asyncio.sleep(seconds)


# Register startup callback for mitmproxy availability check
from code_muse.tools.meetin_proxy.register_callbacks import (  # noqa: E402
    register as _register_mitmproxy_callbacks,
)

_register_mitmproxy_callbacks()
