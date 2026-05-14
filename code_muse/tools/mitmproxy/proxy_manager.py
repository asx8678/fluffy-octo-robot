"""Manage mitmdump subprocess for traffic capture."""

import logging
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import orjson as json

from code_muse.http_utils import find_available_port
from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)

# Global singleton manager instance
_manager: MitmProxyManager | None = None


def get_manager() -> MitmProxyManager:
    global _manager
    if _manager is None:
        _manager = MitmProxyManager()
    return _manager


class MitmProxyManager:
    """Lifecycle manager for mitmdump capture process."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._target: str = ""
        self._output_path: str = ""
        self._addon_path: str = ""
        self._flow_count: int = 0
        self._saved_proxy_env: dict[str, str | None] = {}

    def find_mitmdump(self) -> str | None:
        """Locate mitmdump binary across common locations."""
        # 1. PATH
        path_mitmdump = shutil.which("mitmdump")
        if path_mitmdump:
            return path_mitmdump

        # 2. Local mitmproxy checkout (uv run)
        local_checkout = Path("/Users/adam2/projects/mitmproxy")
        if (local_checkout / "pyproject.toml").exists():
            # Prefer uv run if uv is available
            if shutil.which("uv"):
                return f"cd {local_checkout} && uv run mitmdump"
            # Fallback: direct python module invocation
            python = sys.executable
            return f"{python} -m mitmproxy.tools.main mitmdump"

        # 3. pip location — mitmdump is usually on PATH, but check module invocation
        try:
            import mitmproxy

            return f"{sys.executable} -m mitmproxy.tools.main mitmdump"
        except ImportError:
            pass

        return None

    def _resolve_addon_path(self) -> str:
        """Resolve path to the capture addon script."""
        if self._addon_path and Path(self._addon_path).exists():
            return self._addon_path

        # Relative to this module
        module_dir = Path(__file__).parent
        addon = module_dir / "capture_addon.py"
        if addon.exists():
            return str(addon)

        # Package data fallback
        try:
            import importlib.resources as resources

            with resources.path("code_muse.tools.mitmproxy", "capture_addon.py") as p:
                return str(p)
        except Exception:
            pass

        raise FileNotFoundError("Could not resolve capture_addon.py path")

    def start(
        self,
        target: str = "",
        port: int | None = None,
        max_req_body: int = 10000,
        max_res_body: int = 100000,
    ) -> int:
        """Start mitmdump with capture addon.

        Args:
            target: Domain filter (empty captures everything).
            port: Listen port (auto-selected if None).
            max_req_body: Max request body bytes to capture.
            max_res_body: Max response body bytes to capture.

        Returns:
            The listening port number.
        """
        if self._process is not None and self._process.poll() is None:
            emit_warning("mitmproxy already running — stopping previous instance first")
            self.stop()

        mitmdump = self.find_mitmdump()
        if not mitmdump:
            raise RuntimeError(
                "mitmdump not found. Install mitmproxy: pip install mitmproxy"
            )

        listen_port = port or find_available_port(start_port=8090, end_port=9010)
        if listen_port is None:
            raise RuntimeError("No available port found in range 8090-9010")

        addon_path = self._resolve_addon_path()

        # Secure temp file for capture output
        fd, output_path = tempfile.mkstemp(prefix="mitmproxy_", suffix=".json")
        os.close(fd)

        env = os.environ.copy()
        env["MITMPROXY_TARGET"] = target
        env["MITMPROXY_OUTPUT"] = output_path
        env["MITMPROXY_MAX_REQ_BODY"] = str(max_req_body)
        env["MITMPROXY_MAX_RES_BODY"] = str(max_res_body)

        cmd_parts = [
            mitmdump,
            "-p",
            str(listen_port),
            "-s",
            addon_path,
            "--set",
            "block_global=false",
            "--ssl-insecure",
            "--quiet",
        ]

        # If mitmdump path is a shell expression (cd ... && uv run ...), use shell
        use_shell = "&&" in mitmdump or ";" in mitmdump
        if use_shell:
            # First element is the shell prefix; remaining args are quoted individually
            prefix = str(cmd_parts[0])
            rest = " ".join(shlex.quote(str(p)) for p in cmd_parts[1:])
            cmd = f"{prefix} {rest}"
        else:
            cmd = cmd_parts

        emit_info(
            f"🛡️ Starting mitmproxy on port {listen_port} (target: {target or 'all'})"
        )

        try:
            if sys.platform.startswith("win"):
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
                self._process = subprocess.Popen(
                    cmd,
                    shell=use_shell,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    creationflags=creationflags,
                )
            else:
                self._process = subprocess.Popen(
                    cmd,
                    shell=use_shell,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    start_new_session=True,
                )
        except Exception as exc:
            # Clean up temp file on failure
            Path(output_path).unlink(missing_ok=True)
            raise RuntimeError(f"Failed to start mitmdump: {exc}") from exc

        self._port = listen_port
        self._target = target
        self._output_path = output_path
        self._flow_count = 0

        # Set proxy env vars so muse traffic routes through
        proxy_url = f"http://127.0.0.1:{listen_port}"
        self._saved_proxy_env = {
            "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
            "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
        }
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ["HTTP_PROXY"] = proxy_url

        # Give mitmdump a moment to bind
        time.sleep(0.5)

        if self._process.poll() is not None:
            # Process exited immediately
            exit_code = self._process.returncode
            Path(output_path).unlink(missing_ok=True)
            raise RuntimeError(f"mitmdump exited immediately (code {exit_code})")

        emit_success(f"✅ mitmproxy running on port {listen_port}")
        emit_info(
            "⚠️ SSL verification is disabled (--ssl-insecure). "
            "For production use, install and trust the mitmproxy CA certificate."
        )

        return listen_port

    def stop(self) -> dict | None:
        """Stop mitmdump and read captured flows.

        Returns:
            Dict with capture metadata and flows, or None if nothing captured.
        """
        if self._process is None:
            return None

        # Send SIGTERM gracefully
        self._terminate_process()

        # Read capture file
        data = self._read_capture_file()
        if data:
            self._flow_count = data.get("meta", {}).get("total_flows", 0)

        # Restore or clear proxy env vars
        for key, value in self._saved_proxy_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._saved_proxy_env = {}

        # Clean up temp file
        if self._output_path:
            Path(self._output_path).unlink(missing_ok=True)
            self._output_path = ""

        self._process = None
        self._port = None

        return data

    def status(self) -> dict:
        """Return current proxy status."""
        running = self._process is not None and self._process.poll() is None
        return {
            "running": running,
            "port": self._port,
            "target": self._target,
            "flow_count": self._flow_count,
        }

    def cleanup(self) -> None:
        """Ensure process is killed and temp files removed."""
        if self._process is not None and self._process.poll() is None:
            self._terminate_process()
        if self._output_path:
            Path(self._output_path).unlink(missing_ok=True)
            self._output_path = ""
        self._process = None
        self._port = None
        for key, value in self._saved_proxy_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._saved_proxy_env = {}

    def _terminate_process(self) -> None:
        """Best-effort graceful termination of the mitmdump process."""
        proc = self._process
        if proc is None:
            return

        try:
            if sys.platform.startswith("win"):
                proc.terminate()
                proc.wait(timeout=3)
                return

            # POSIX: start_new_session created a new process group
            pid = proc.pid
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
                time.sleep(1.0)
                if proc.poll() is None:
                    os.killpg(pgid, signal.SIGINT)
                    time.sleep(0.5)
                if proc.poll() is None:
                    os.killpg(pgid, signal.SIGKILL)
                    proc.wait(timeout=2)
            except OSError:
                # Process may already be gone
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Error terminating mitmdump: %s", exc)

    def _read_capture_file(self) -> dict | None:
        """Read and return the JSON capture file contents."""
        if not self._output_path or not Path(self._output_path).exists():
            return None
        try:
            with open(self._output_path, encoding="utf-8") as f:
                return json.loads(f.read())
        except Exception as exc:
            logger.warning("Failed to read capture file: %s", exc)
            return None
