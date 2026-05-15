# Subinterpreters for Universal Constructor Tools

> **PEP 734** — Subinterpreters for Python (available in Python 3.14+)

Muse uses **isolated sub-interpreters** as the modern, high-performance execution backend for [Universal Constructor](/Users/adam2/projects/fluffy-octo-robot/code_muse/plugins/universal_constructor) tools.

This gives you real OS-level parallelism for user-written tools **without** requiring the experimental free-threaded (no-GIL) Python build.

---

## Why Subinterpreters?

Muse has always run UC tools in isolation for safety. Previously this was done with `multiprocessing.spawn` + temporary files.

While reliable, spawning a full OS process for every small tool call has noticeable overhead (fork + Python startup + import time).

**Subinterpreters** solve this elegantly:

- Each sub-interpreter has its **own GIL**
- Creating one is dramatically cheaper than spawning a process
- You get true parallelism when multiple agents or sub-agents run UC tools concurrently
- Works on **standard** Python 3.14 and 3.15 (no special build required)

This is currently the best path for cheap, safe, parallel execution of dynamic Python code in Muse.

---

## Benefits

| Aspect                    | Old (multiprocessing)      | New (subinterpreters)              |
|---------------------------|----------------------------|------------------------------------|
| Startup latency           | High (process spawn)       | Very low                           |
| Parallelism               | Yes (separate processes)   | Yes (separate GILs)                |
| Memory overhead           | Higher                     | Lower (shared process)             |
| Works on Python 3.14+     | Yes                        | Yes (preferred)                    |
| Requires free-threaded    | No                         | No                                 |
| Timeout killing           | Hard (`terminate()`)       | Best-effort (`Interpreter.close()`) |

For most UC tools (especially short ones), you will see **noticeably snappier** behavior when the subinterpreter backend is enabled.

---

## How to Enable

The subinterpreter backend is currently **opt-in** (see "Current Status" below).

```bash
# Enable the fast subinterpreter path
MUSE_USE_INTERPRETER_POOL=1 muse

# Use a larger pool (default is 4)
MUSE_USE_INTERPRETER_POOL=1 MUSE_SUBINTERPRETER_POOL_SIZE=8 muse
```

---

## Current Status (May 2026)

| Item                              | Status                                      |
|-----------------------------------|---------------------------------------------|
| Implementation                    | Complete and tested                         |
| Default backend                   | Still multiprocessing (opt-in for now)      |
| Hard timeout killing              | Best-effort (see limitations)               |
| All UC security tests             | Passing (49/49)                             |
| Recommended for production use    | Yes, when opted in                          |

### Why is it still opt-in?

On Python 3.14.x, calling `Interpreter.close()` from another thread does not always instantly abort a running `exec()`. This means hard wall-clock timeouts are slightly less precise than with `multiprocessing.terminate()`.

The correct **error shape** is still returned to the caller (`"Tool timed out after X seconds"`), but the actual wall time may exceed the requested timeout in rare cases.

We expect this to improve in Python 3.15+. Once it does, we plan to make subinterpreters the **default** backend on 3.14+.

---

## Limitations

- Only a small set of objects are directly shareable between interpreters (`int`, `str`, `bytes`, `tuple`, `None`, `Queue`, etc.). Muse therefore still serializes arguments and results as JSON (using the fast `_fastjson` shim).
- stdout/stderr are still captured via temporary files (same mechanism as the multiprocessing path) for consistent TOCTOU protection and output capping.
- Some C extensions may behave differently when imported in multiple subinterpreters (rare in practice in 2026).

---

## For Plugin Authors

If you are writing a plugin that wants cheap parallel execution of Python callables, you can use the same infrastructure:

```python
from code_muse.interpreter_pool import (
    SubInterpreterExecutor,
    get_default_executor,
    run_in_subinterpreter,
    is_available,
)

if is_available():
    # Fast path
    result = run_in_subinterpreter(
        module_path="/path/to/my_tool.py",
        function_name="my_function",
        args={"foo": 42},
        timeout=15.0,
    )
else:
    # Fall back to multiprocessing or threads
    ...
```

See [code_muse/interpreter_pool.py](/Users/adam2/projects/fluffy-octo-robot/code_muse/interpreter_pool.py) for the full API.

---

## Relationship to Free-Threaded Python

Muse's original comment in `pyproject.toml` ("Only 3.14+ is supported due to free-threaded Python features") referred to the broader ecosystem direction.

In practice, **subinterpreters (PEP 734) turned out to be the higher-leverage feature** for Muse's workload than free-threading (PEP 703) for the following reasons:

- Subinterpreters give you parallelism **today** on standard CPython.
- Free-threaded Python still has significant C-extension compatibility gaps in mid-2026 (notably `orjson` and some `tree-sitter` packages).
- Muse is heavily I/O and LLM-latency bound — the biggest wins come from avoiding process spawn overhead, not from removing the GIL.

The subinterpreter work gives Muse most of the desired parallelism benefits with far less ecosystem friction.

---

## Future Plans

- Make subinterpreters the **default** backend once Python 3.15 improves timeout responsiveness.
- Explore using subinterpreters for other CPU-heavy tasks (parallel tree-sitter parsing, batch compression, token ratio learning, etc.).
- Potentially expose a clean `@uc_parallel` decorator or context manager for plugin authors.

---

## Related Environment Variables

| Variable                              | Effect                                      | Default |
|---------------------------------------|---------------------------------------------|---------|
| `MUSE_USE_INTERPRETER_POOL=1`          | Use PEP 734 subinterpreter backend          | Off     |
| `MUSE_SUBINTERPRETER_POOL_SIZE=N`     | Number of warm interpreters to keep         | `4`     |

---

This feature represents a significant architectural improvement in how Muse safely and efficiently executes dynamic user code. Feedback is very welcome on the Discord or via GitHub issues.