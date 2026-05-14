"""Universal Constructor tool runner using isolated subprocess workers.

Replaces thread-only timeout with a killable subprocess/multiprocessing
worker. Enforces wall-clock timeout, uses JSON-only serialization for
args and results, and caps stdout/stderr.

FREE-THREADED (PEP 734/779): This module now supports
concurrent.interpreters.InterpreterPoolExecutor as an alternative to
multiprocessing.Process for CPU-bound isolation in Python 3.14+ free-threaded
builds. The interpreter pool path shares memory and avoids serialization
overhead for simple types.
"""

import contextlib
import orjson as json
import logging
import multiprocessing
import os
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# FREE-THREADED: Try to import InterpreterPoolExecutor (PEP 734, Python 3.14+)
# Falls back to None on older interpreters where it is not available.
try:
    from concurrent.interpreters import InterpreterPoolExecutor

    _INTERPRETER_POOL_AVAILABLE = True
except Exception:
    InterpreterPoolExecutor = None  # type: ignore[misc, assignment]
    _INTERPRETER_POOL_AVAILABLE = False

# Cap output to prevent model context blowup
_MAX_STDOUT_LINES = 256
_MAX_STDERR_LINES = 128
_MAX_STDOUT_CHARS = 4096
_MAX_STDERR_CHARS = 2048


def _cap_output(text: str, max_chars: int, max_lines: int) -> str:
    """Cap output string to prevent unbounded growth."""
    if not text:
        return text
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    else:
        truncated = False
    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars]
        truncated = True
    if truncated:
        result += "\n... [output truncated]"
    return result


def _run_in_subprocess(
    module_path: str,
    function_name: str,
    args_json: str,
    result_path: str,
    stdout_path: str,
    stderr_path: str,
) -> None:
    """Worker function executed in a subprocess.

    Loads the module, calls the function with deserialized JSON args,
    and writes the JSON result to result_path.
    """
    stdout_buf = []
    stderr_buf = []

    class _CapStream:
        def __init__(self, buf, max_lines):
            self.buf = buf
            self.max_lines = max_lines

        def write(self, text: str) -> None:
            self.buf.append(text)
            if len(self.buf) > self.max_lines * 2:
                self.buf = self.buf[-self.max_lines * 2 :]

        def flush(self) -> None:
            pass

    # Redirect stdout/stderr to capped buffers
    cap_stdout = _CapStream(stdout_buf, _MAX_STDOUT_LINES)
    cap_stderr = _CapStream(stderr_buf, _MAX_STDERR_LINES)
    sys.stdout = cap_stdout  # type: ignore[assignment]
    sys.stderr = cap_stderr  # type: ignore[assignment]

    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("uc_worker_module", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        func = getattr(module, function_name, None)
        if func is None:
            raise NameError(f"Function '{function_name}' not found in module")
        if not callable(func):
            raise TypeError(f"'{function_name}' is not callable")

        args: dict[str, Any] = orjson.loads(args_json) if args_json else {}
        if not isinstance(args, dict):
            raise TypeError("tool_args must deserialize to a dict")

        raw_result = func(**args)

        # JSON-only serialization: reject non-serializable results
        try:
            result_json = orjson.dumps({"success": True, "result": raw_result})
        except (TypeError, ValueError) as e:
            raise TypeError(f"Tool result is not JSON-serializable: {e}") from e

        with open(result_path, "w", encoding="utf-8") as f:
            f.write(result_json)

    except Exception as e:
        error_info = {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(orjson.dumps(error_info).decode())

    finally:
        # Write captured stdout/stderr
        with open(stdout_path, "w", encoding="utf-8") as f:
            f.write("".join(stdout_buf))
        with open(stderr_path, "w", encoding="utf-8") as f:
            f.write("".join(stderr_buf))


def _run_in_interpreter(
    module_path: str,
    function_name: str,
    args: dict[str, Any],
    result_path: str,
    stdout_path: str,
    stderr_path: str,
) -> None:
    """Worker function executed in a sub-interpreter via InterpreterPoolExecutor.

    Mirrors _run_in_subprocess but is designed for PEP 734 interpreter pools.
    Serializes args to JSON and writes JSON result to result_path.
    """
    # Reuse the same subprocess worker logic — interpreter pools still
    # need file-based I/O for stdout/stderr capture because sub-interpreters
    # do not share sys.stdout with the main interpreter.
    args_json = orjson.dumps(args) if args else "{}"
    _run_in_subprocess(
        module_path, function_name, args_json, result_path, stdout_path, stderr_path
    )


def _verify_file_integrity(
    path: str, expected_inode: int, expected_dev: int
) -> str | None:
    """Verify a temp file hasn't been swapped (TOCTOU detection).

    Returns None if OK, or an error string if the file was tampered with.
    """
    try:
        st = os.stat(path)
    except OSError as e:
        return f"Temp file vanished: {e}"
    if st.st_ino != expected_inode or st.st_dev != expected_dev:
        return f"Temp file inode changed — possible TOCTOU attack on {path}"
    return None


def _should_use_interpreter_pool() -> bool:
    """Return True if the InterpreterPoolExecutor path should be used.

    Controlled by the environment variable ``MUSE_USE_INTERPRETER_POOL``.
    Default is False until PEP 734 is stable in production CPython builds.
    """
    if not _INTERPRETER_POOL_AVAILABLE:
        return False
    return os.environ.get("MUSE_USE_INTERPRETER_POOL", "").lower() in (
        "1",
        "true",
        "yes",
    )


def run_tool_subprocess(
    module_path: str,
    function_name: str,
    args: dict[str, Any | None] = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Run a UC tool function in an isolated subprocess with a hard timeout.

    Args:
        module_path: Absolute path to the Python module file.
        function_name: Name of the callable function in the module.
        args: Dictionary of arguments to pass to the function.
        timeout: Maximum wall-clock seconds to allow.

    Returns:
        Dict with keys:
            - success: bool
            - result: the JSON-deserialized return value (if success)
            - error: error message string (if not success)
            - stdout: capped stdout from the tool
            - stderr: capped stderr from the tool
            - execution_time: float seconds
    """
    args = args or {}
    args_json = orjson.dumps(args)

    with (
        tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as result_file,
        tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as stdout_file,
        tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as stderr_file,
    ):
        result_path = result_file.name
        stdout_path = stdout_file.name
        stderr_path = stderr_file.name

    # Record inode/device for TOCTOU detection
    _temp_inodes: dict[str, tuple[int, int]] = {}
    try:
        _temp_inodes["result"] = (
            os.stat(result_path).st_ino,
            os.stat(result_path).st_dev,
        )
        _temp_inodes["stdout"] = (
            os.stat(stdout_path).st_ino,
            os.stat(stdout_path).st_dev,
        )
        _temp_inodes["stderr"] = (
            os.stat(stderr_path).st_ino,
            os.stat(stderr_path).st_dev,
        )
    except OSError:
        pass  # Will fail below if file missing

    start_time = time.time()
    process: multiprocessing.Process | None = None

    # FREE-THREADED: Use InterpreterPoolExecutor when available and opted-in.
    # This path avoids fork/spawn overhead and shares memory for simple types.
    if _should_use_interpreter_pool() and InterpreterPoolExecutor is not None:
        try:
            with InterpreterPoolExecutor() as executor:
                future = executor.submit(
                    _run_in_interpreter,
                    str(module_path),
                    function_name,
                    args,
                    result_path,
                    stdout_path,
                    stderr_path,
                )
                future.result(timeout=timeout)

            # Read results BEFORE cleanup
            execution_time = time.time() - start_time

            # TOCTOU check: verify temp files haven't been swapped
            for _key, _path in [
                ("result", result_path),
                ("stdout", stdout_path),
                ("stderr", stderr_path),
            ]:
                if _key in _temp_inodes:
                    ino, dev = _temp_inodes[_key]
                    err = _verify_file_integrity(_path, ino, dev)
                    if err:
                        return {
                            "success": False,
                            "error": err,
                            "stdout": "",
                            "stderr": "",
                            "execution_time": time.time() - start_time,
                        }

            try:
                with open(result_path, encoding="utf-8") as f:
                    result_data = orjson.loads(f.read())
            except (json.JSONDecodeError, OSError) as e:
                return {
                    "success": False,
                    "error": f"Failed to read tool result: {e}",
                    "stdout": "",
                    "stderr": "",
                    "execution_time": execution_time,
                }
            try:
                with open(stdout_path, encoding="utf-8") as f:
                    stdout_text = _cap_output(
                        f.read(), _MAX_STDOUT_CHARS, _MAX_STDOUT_LINES
                    )
            except OSError:
                stdout_text = ""
            try:
                with open(stderr_path, encoding="utf-8") as f:
                    stderr_text = _cap_output(
                        f.read(), _MAX_STDERR_CHARS, _MAX_STDERR_LINES
                    )
            except OSError:
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
            return {
                "success": False,
                "error": f"Interpreter pool execution failed: {type(exc).__name__}: {exc}",
                "stdout": "",
                "stderr": "",
                "execution_time": time.time() - start_time,
            }
        finally:
            for p in (result_path, stdout_path, stderr_path):
                with contextlib.suppress(OSError):
                    os.unlink(p)

    # TODO: PEP 734 — replace multiprocessing with InterpreterPoolExecutor when stable
    try:
        ctx = multiprocessing.get_context("spawn")
        process = ctx.Process(
            target=_run_in_subprocess,
            args=(
                str(module_path),
                function_name,
                args_json,
                result_path,
                stdout_path,
                stderr_path,
            ),
        )
        process.start()
        process.join(timeout=timeout)

        if process.is_alive():
            # Timeout: kill the worker
            process.terminate()
            process.join(timeout=2.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
            return {
                "success": False,
                "error": f"Tool timed out after {timeout}s",
                "stdout": "",
                "stderr": "",
                "execution_time": time.time() - start_time,
            }

        # TOCTOU check: verify temp files haven't been swapped
        for _key, _path in [
            ("result", result_path),
            ("stdout", stdout_path),
            ("stderr", stderr_path),
        ]:
            if _key in _temp_inodes:
                ino, dev = _temp_inodes[_key]
                err = _verify_file_integrity(_path, ino, dev)
                if err:
                    return {
                        "success": False,
                        "error": err,
                        "stdout": "",
                        "stderr": "",
                        "execution_time": time.time() - start_time,
                    }

        # Read result
        try:
            with open(result_path, encoding="utf-8") as f:
                result_data = orjson.loads(f.read())
        except (json.JSONDecodeError, OSError) as e:
            return {
                "success": False,
                "error": f"Failed to read tool result: {e}",
                "stdout": "",
                "stderr": "",
                "execution_time": time.time() - start_time,
            }

        # Read and cap stdout/stderr
        try:
            with open(stdout_path, encoding="utf-8") as f:
                stdout_text = _cap_output(
                    f.read(), _MAX_STDOUT_CHARS, _MAX_STDOUT_LINES
                )
        except OSError:
            stdout_text = ""

        try:
            with open(stderr_path, encoding="utf-8") as f:
                stderr_text = _cap_output(
                    f.read(), _MAX_STDERR_CHARS, _MAX_STDERR_LINES
                )
        except OSError:
            stderr_text = ""

        execution_time = time.time() - start_time

        return {
            "success": result_data.get("success", False),
            "result": result_data.get("result") if result_data.get("success") else None,
            "error": result_data.get("error")
            if not result_data.get("success")
            else None,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "execution_time": execution_time,
        }

    finally:
        # Cleanup temp files
        for p in (result_path, stdout_path, stderr_path):
            with contextlib.suppress(OSError):
                os.unlink(p)
        if process is not None and process.is_alive():
            try:
                process.kill()
                process.join(timeout=1.0)
            except Exception:
                pass


def run_tool_callable(
    func: Callable,
    args: dict[str, Any | None] = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Run a callable in an isolated subprocess by writing a temp module.

    This is a fallback for when we only have a callable object (not a
    file path). The callable must be picklable or the caller should
    prefer run_tool_subprocess with a module_path.

    Args:
        func: The callable to execute.
        args: Dictionary of arguments.
        timeout: Maximum seconds.

    Returns:
        Dict with success/result/error/stdout/stderr/execution_time.
    """
    import inspect

    try:
        module = inspect.getmodule(func)
        if module is not None and hasattr(module, "__file__") and module.__file__:
            module_path = module.__file__
            function_name = func.__name__
            return run_tool_subprocess(module_path, function_name, args, timeout)
    except Exception:
        pass

    # Fallback: can't determine module path — must use JSON-only serialization
    return {
        "success": False,
        "error": (
            f"Cannot serialize callable '{func.__name__}' for subprocess execution. "
            "Only module-level functions with a known __file__ are supported."
        ),
        "stdout": "",
        "stderr": "",
        "execution_time": 0.0,
    }
