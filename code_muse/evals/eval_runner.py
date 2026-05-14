"""Core test infrastructure for the Behavioral Eval Framework.

Provides ``TestRig`` for recording tool calls, ``run_eval`` for executing
agent prompts in a temporary directory via headless ``code-muse``, and
``EvalSuite`` for organizing multiple evals.
"""

import importlib.util
import orjson as json
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ToolCall:
    """Record of a single tool invocation observed during an eval run."""

    tool_name: str
    tool_args: dict
    result: Any
    timestamp: float


class TestRig:
    """In-memory log of tool calls observed during an eval run."""

    __test__ = False  # Not a pytest test class

    def __init__(self) -> None:
        self._tool_logs: list[ToolCall] = []

    def record_tool_call(self, tool_name: str, tool_args: dict, result: Any) -> None:
        """Append a tool call to the log."""
        self._tool_logs.append(
            ToolCall(
                tool_name=tool_name,
                tool_args=tool_args,
                result=result,
                timestamp=time.time(),
            )
        )

    def get_tool_logs(self) -> list[ToolCall]:
        """Return a shallow copy of the tool log."""
        return list(self._tool_logs)

    def get_tool_calls_by_name(self, name: str) -> list[ToolCall]:
        """Filter the tool log by tool name."""
        return [tc for tc in self._tool_logs if tc.tool_name == name]


@dataclass
class EvalResult:
    """Structured outcome of a single eval run."""

    name: str
    passed: bool
    message: str
    tool_logs: list[ToolCall] = field(default_factory=list)


def _parse_tool_calls_from_stdout(stdout: str) -> list[ToolCall]:
    """Best-effort extraction of tool calls from agent stdout.

    Looks for JSON objects that contain ``tool_name`` and ``tool_args``
    keys.  Each matched JSON object becomes a :class:`ToolCall`.  Lines
    that fail to parse are silently skipped.
    """
    tool_calls: list[ToolCall] = []
    # Strategy 1: whole-line JSON objects
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = orjson.loads(line)
            if isinstance(obj, dict) and "tool_name" in obj and "tool_args" in obj:
                tool_calls.append(
                    ToolCall(
                        tool_name=obj.get("tool_name", ""),
                        tool_args=obj.get("tool_args", {}),
                        result=obj.get("result"),
                        timestamp=obj.get("timestamp", time.time()),
                    )
                )
        except ValueError:
            pass

    # Strategy 2: embedded JSON objects inside other text (brace-balanced)
    if not tool_calls:
        tool_calls = _extract_json_objects_with_tool_fields(stdout)

    return tool_calls


def _extract_json_objects_with_tool_fields(text: str) -> list[ToolCall]:
    """Brace-balanced JSON object extractor for mixed stdout text."""
    tool_calls: list[ToolCall] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            start = i
            depth = 1
            i += 1
            while i < len(text) and depth > 0:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
            if depth == 0:
                candidate = text[start:i]
                try:
                    obj = orjson.loads(candidate)
                    if (
                        isinstance(obj, dict)
                        and "tool_name" in obj
                        and "tool_args" in obj
                    ):
                        tool_calls.append(
                            ToolCall(
                                tool_name=obj.get("tool_name", ""),
                                tool_args=obj.get("tool_args", {}),
                                result=obj.get("result"),
                                timestamp=obj.get("timestamp", time.time()),
                            )
                        )
                except ValueError:
                    pass
        else:
            i += 1
    return tool_calls


def run_eval(
    name: str,
    prompt: str,
    setup_files: dict[str, str] | None,
    assert_fn: Callable[[TestRig], tuple[bool, str]],
) -> EvalResult:
    """Run a single behavioral eval in an isolated temporary directory.

    Steps:
        1. Create a temp directory.
        2. Write ``setup_files`` into it.
        3. Spawn ``code-muse --headless --cwd <temp_dir>`` via ``subprocess``
           with the prompt piped on stdin.
        4. Parse tool calls from stdout.
        5. Populate a :class:`TestRig`.
        6. Run the user-supplied ``assert_fn``.
        7. Return an :class:`EvalResult`.

    Args:
        name: Human-readable name for this eval.
        prompt: The prompt text to send to the agent.
        setup_files: Optional ``path → content`` dict to materialise
            inside the temp directory before running the agent.
        assert_fn: Callback that receives the populated :class:`TestRig`
            and returns ``(passed, message)``.

    Returns:
        An :class:`EvalResult` describing the outcome.
    """
    temp_dir = tempfile.mkdtemp(prefix=f"eval_{name}_")
    try:
        # 1. Write setup files
        if setup_files:
            for rel_path, content in setup_files.items():
                full_path = Path(temp_dir) / rel_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)

        # 2. Run code-muse headless
        escaped_prompt = prompt.replace('"', '\\"')
        # TODO: PEP 750 t-string — use templatelib when stable
        cmd = f'echo "{escaped_prompt}" | code-muse --headless --cwd {shlex.quote(temp_dir)}'
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=temp_dir,
        )

        # 3. Parse tool calls
        combined_output = proc.stdout + proc.stderr
        tool_calls = _parse_tool_calls_from_stdout(combined_output)

        # 4. Populate TestRig
        rig = TestRig()
        # Inject synthetic output record so assert_output_contains works
        rig.record_tool_call(
            "_eval_output",
            {"stdout": proc.stdout, "stderr": proc.stderr},
            combined_output,
        )
        for tc in tool_calls:
            rig.record_tool_call(tc.tool_name, tc.tool_args, tc.result)

        # 5. Run assertion
        passed, message = assert_fn(rig)

        return EvalResult(
            name=name, passed=passed, message=message, tool_logs=rig.get_tool_logs()
        )
    except Exception as exc:
        return EvalResult(
            name=name, passed=False, message=f"Eval execution failed: {exc}"
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_all_evals(evals_dir: Path) -> list[EvalResult]:
    """Discover and run every ``eval_*.py`` file in *evals_dir*.

    Each file is imported and every callable whose name starts with
    ``eval_`` is invoked.  The callable is expected to return an
    :class:`EvalResult` (usually by calling :func:`run_eval`).

    Args:
        evals_dir: Directory containing ``eval_*.py`` files.

    Returns:
        List of :class:`EvalResult` objects, one per discovered eval
        function.
    """
    results: list[EvalResult] = []
    if not evals_dir.exists():
        return results

    for py_file in sorted(evals_dir.glob("eval_*.py")):
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for attr_name in dir(module):
            if attr_name.startswith("eval_"):
                func = getattr(module, attr_name)
                if callable(func):
                    try:
                        result = func()
                        if isinstance(result, EvalResult):
                            results.append(result)
                    except Exception as exc:
                        results.append(
                            EvalResult(
                                name=f"{py_file.stem}.{attr_name}",
                                passed=False,
                                message=f"Eval function raised: {exc}",
                            )
                        )
    return results


class EvalSuite:
    """Container for organizing and running multiple eval definitions."""

    def __init__(self) -> None:
        self._evals: list[dict[str, Any]] = []

    def add(
        self,
        name: str,
        prompt: str,
        setup: dict[str, str] | None,
        assert_fn: Callable[[TestRig], tuple[bool, str]],
    ) -> None:
        """Register an eval definition without running it yet."""
        self._evals.append(
            {
                "name": name,
                "prompt": prompt,
                "setup": setup,
                "assert_fn": assert_fn,
            }
        )

    def run_all(self) -> list[EvalResult]:
        """Execute every registered eval and return the results."""
        results: list[EvalResult] = []
        for definition in self._evals:
            result = run_eval(
                name=definition["name"],
                prompt=definition["prompt"],
                setup_files=definition["setup"],
                assert_fn=definition["assert_fn"],
            )
            results.append(result)
        return results
