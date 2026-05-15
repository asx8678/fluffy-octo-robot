"""Subinterpreter execution pool (PEP 734) for cheap true parallelism on Python 3.14+.

This module provides a pooled executor that runs Python callables in isolated
sub-interpreters. Each sub-interpreter has its own GIL, enabling real OS-level
parallelism even on the standard (GIL-enabled) CPython build.

This is the recommended way to get parallelism for CPU-bound work in Muse
(Universal Constructor tools, heavy AST compression, etc.) without requiring
free-threaded Python or making every C extension nogil-safe.

Public API (stable for Phase 2/3):
    from code_muse.interpreter_pool import (
        SubInterpreterExecutor,
        get_default_executor,
        is_available,
        run_in_subinterpreter,
    )

The implementation deliberately stays small and focused on the UC use case
while remaining reusable by other plugins.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """Return True if the subinterpreter API is usable on this Python build."""
    try:
        from concurrent import interpreters  # noqa: F401

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The Executor
# ---------------------------------------------------------------------------


class SubInterpreterExecutor:
    """A pool of reusable sub-interpreters for parallel execution.

    Each interpreter in the pool runs with its own GIL. Creating a new
    interpreter is cheap compared to spawning an OS process.

    Usage:

        with SubInterpreterExecutor(max_workers=4) as exec:
            result = exec.run_module_function(
                module_path="/path/to/tool.py",
                function_name="my_tool",
                args={"city": "Berlin"},
                timeout=30.0,
            )
    """

    def __init__(self, max_workers: int = 4, keep_alive: bool = True):
        if not is_available():
            raise RuntimeError(
                "Subinterpreters (PEP 734) are only available on Python 3.14+. "
                "Use the multiprocessing fallback on older versions."
            )

        self._max_workers = max(1, max_workers)
        self._keep_alive = keep_alive
        self._pool: deque[Any] = deque()  # stores Interpreter objects
        self._lock = threading.Lock()
        self._closed = False
        self._created_count = 0

        # Import here so the module can still be imported on < 3.14
        from concurrent import interpreters as _interp_mod

        self._interp_mod = _interp_mod

    # ------------------------------------------------------------------ pool management

    def _acquire(self) -> Any:
        """Get an interpreter from the pool or create a new one."""
        with self._lock:
            if self._pool:
                return self._pool.popleft()
            # Create a fresh one
            interp = self._interp_mod.create()
            self._created_count += 1
            return interp

    def _release(self, interp: Any) -> None:
        """Return an interpreter to the pool or close it."""
        if self._closed or not self._keep_alive:
            with contextlib.suppress(Exception):
                interp.close()
            return

        with self._lock:
            if len(self._pool) < self._max_workers:
                self._pool.append(interp)
            else:
                with contextlib.suppress(Exception):
                    interp.close()

    def shutdown(self, wait: bool = True) -> None:
        """Close all interpreters in the pool."""
        self._closed = True
        with self._lock:
            while self._pool:
                interp = self._pool.popleft()
                with contextlib.suppress(Exception):
                    interp.close()
        logger.debug(
            "SubInterpreterExecutor shut down (created %d interpreters)",
            self._created_count,
        )

    def __enter__(self) -> SubInterpreterExecutor:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown(wait=True)

    # ------------------------------------------------------------------ execution

    def run_module_function(
        self,
        module_path: str,
        function_name: str,
        args: dict[str, Any] | None = None,
        timeout: float = 30.0,
        *,
        result_path: str | None = None,
        stdout_path: str | None = None,
        stderr_path: str | None = None,
    ) -> dict[str, Any]:
        """Run a function defined in an external .py file inside a sub-interpreter.

        This is the high-level API used by the Universal Constructor runner.

        The implementation still uses temp files for result + stdout/stderr
        capture (same protocol as the multiprocessing path) so that all the
        TOCTOU protection, output capping, and error formatting logic in
        runner.py can stay unchanged.

        Args:
            module_path: Absolute path to the Python file containing the tool.
            function_name: Name of the function to call inside that module.
            args: JSON-serializable arguments for the function.
            timeout: Hard wall-clock limit in seconds.
            result_path / stdout_path / stderr_path: Optional paths to temp files
                that the caller has already created. If omitted, the executor
                will create its own temporary files (less efficient for the
                current runner integration).

        Returns:
            Dict with the same shape as the multiprocessing path:
            {"success": bool, "result": Any, "error": str|None, "stdout": str,
             "stderr": str, "execution_time": float}
        """
        args = args or {}
        start = time.time()

        # Use the caller's temp files when provided (the common case from runner.py)
        own_files = result_path is None
        if own_files:
            import tempfile

            with (
                tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False
                ) as rf,
                tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False
                ) as sf,
                tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False
                ) as ef,
            ):
                result_path = rf.name
                stdout_path = sf.name
                stderr_path = ef.name

        interp = self._acquire()
        timed_out = False
        watcher: threading.Timer | None = None

        try:
            # Prepare the payload for the sub-interpreter.
            # We still serialize via the fastjson shim so we are independent of orjson.
            import code_muse._fastjson as _json

            args_json = _json.dumps(args)

            # Inject everything the sub-interpreter needs via prepare_main.
            # The executed code will live in the sub-interpreter's __main__.
            interp.prepare_main(
                __uc_module_path=str(module_path),
                __uc_function_name=function_name,
                __uc_args_json=args_json,
                __uc_result_path=str(result_path),
                __uc_stdout_path=str(stdout_path),
                __uc_stderr_path=str(stderr_path),
            )

            # The actual work executed inside the sub-interpreter.
            # We deliberately keep it small and self-contained.
            bootstrap = """
import importlib.util
import json
import sys
import traceback

# Read injected values
module_path = __uc_module_path
function_name = __uc_function_name
args_json = __uc_args_json
result_path = __uc_result_path
stdout_path = __uc_stdout_path
stderr_path = __uc_stderr_path

stdout_buf = []
stderr_buf = []

class _CapStream:
    def __init__(self, buf):
        self.buf = buf
    def write(self, text):
        self.buf.append(text)
    def flush(self):
        pass

sys.stdout = _CapStream(stdout_buf)
sys.stderr = _CapStream(stderr_buf)

try:
    spec = importlib.util.spec_from_file_location("uc_tool_module", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    func = getattr(mod, function_name, None)
    if func is None or not callable(func):
        raise NameError(
            f"Function '{function_name}' not found or not callable in {module_path}"
        )

    args = json.loads(args_json) if args_json else {}
    if not isinstance(args, dict):
        raise TypeError("tool_args must deserialize to a dict")

    raw_result = func(**args)

    result_obj = {"success": True, "result": raw_result}
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(result_obj))

except Exception as exc:
    err_obj = {
        "success": False,
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc(),
    }
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(err_obj))

finally:
    with open(stdout_path, "w", encoding="utf-8") as f:
        f.write("".join(stdout_buf))
    with open(stderr_path, "w", encoding="utf-8") as f:
        f.write("".join(stderr_buf))
"""

            # Timeout handling: start a watcher that will close the interpreter
            # if the deadline is exceeded. Closing an interpreter from another
            # thread is the documented way to abort it.
            def _timeout_kill():
                nonlocal timed_out
                timed_out = True
                logger.warning(
                    "Subinterpreter timeout after %.1fs — closing interpreter", timeout
                )
                with contextlib.suppress(Exception):
                    interp.close()

            watcher = threading.Timer(timeout, _timeout_kill)
            watcher.daemon = True
            watcher.start()

            # Execute inside the sub-interpreter (blocking call from our perspective).
            # Note: On Python 3.14.5, interp.close() from another thread is not always
            # instantaneous for CPU-bound pure-Python loops. We still return the
            # correct "timed out" error shape to the caller; the interpreter will be
            # cleaned up when the pool shuts down or on next GC.
            interp.exec(bootstrap)

            execution_time = time.time() - start

            if timed_out:
                return {
                    "success": False,
                    "result": None,
                    "error": f"Tool timed out after {timeout}s",
                    "stdout": "",
                    "stderr": "",
                    "execution_time": execution_time,
                }

            # Read back the result written by the sub-interpreter
            try:
                with open(result_path, encoding="utf-8") as f:
                    result_data = _json.loads(f.read())
            except Exception as e:
                return {
                    "success": False,
                    "result": None,
                    "error": f"Failed to read tool result: {e}",
                    "stdout": "",
                    "stderr": "",
                    "execution_time": execution_time,
                }

            # Read captured output (already text)
            try:
                with open(stdout_path, encoding="utf-8") as f:
                    stdout_text = f.read()
            except Exception:
                stdout_text = ""

            try:
                with open(stderr_path, encoding="utf-8") as f:
                    stderr_text = f.read()
            except Exception:
                stderr_text = ""

            return {
                "success": result_data.get("success", False),
                "result": result_data.get("result")
                if result_data.get("success")
                else None,
                "error": result_data.get("error")
                if not result_data.get("success")
                else None,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "execution_time": execution_time,
            }

        except Exception as exc:
            execution_time = time.time() - start
            return {
                "success": False,
                "result": None,
                "error": (
                    f"Subinterpreter execution failed: {type(exc).__name__}: {exc}"
                ),
                "stdout": "",
                "stderr": "",
                "execution_time": execution_time,
            }
        finally:
            if watcher:
                watcher.cancel()
            self._release(interp)

            if own_files:
                # Clean up temp files we created
                for p in (result_path, stdout_path, stderr_path):
                    with contextlib.suppress(OSError):
                        os.unlink(p)


# ---------------------------------------------------------------------------
# Module-level convenience API (recommended for most call sites)
# ---------------------------------------------------------------------------

_default_executor: SubInterpreterExecutor | None = None
_default_lock = threading.Lock()


def get_default_executor() -> SubInterpreterExecutor:
    """Return a process-wide default executor (lazy, keep-alive).

    Pool size can be controlled with the environment variable:
        MUSE_SUBINTERPRETER_POOL_SIZE=8
    Default is 4.
    """
    global _default_executor
    if _default_executor is None:
        with _default_lock:
            if _default_executor is None:
                pool_size = int(os.environ.get("MUSE_SUBINTERPRETER_POOL_SIZE", "4"))
                pool_size = max(1, min(pool_size, 32))  # reasonable bounds
                _default_executor = SubInterpreterExecutor(
                    max_workers=pool_size, keep_alive=True
                )
    return _default_executor


# ---------------------------------------------------------------------------
# Clean shutdown at process exit (removes "remaining subinterpreters" warning)
# ---------------------------------------------------------------------------


@atexit.register
def _shutdown_default_executor() -> None:
    global _default_executor
    if _default_executor is not None:
        with contextlib.suppress(Exception):
            _default_executor.shutdown(wait=False)
        _default_executor = None


def run_in_subinterpreter(
    module_path: str,
    function_name: str,
    args: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Convenience wrapper using the default executor.

    This is the function most plugin code should call.
    """
    return get_default_executor().run_module_function(
        module_path=module_path,
        function_name=function_name,
        args=args,
        timeout=timeout,
    )


# Convenience alias for code that wants to check before calling
available = is_available


__all__ = [
    "SubInterpreterExecutor",
    "get_default_executor",
    "run_in_subinterpreter",
    "is_available",
    "available",
]
