"""Strategy registry for the filter engine.

Maps command categories to compression strategy functions.  Handles
registration, duplicate detection, and priority-based overrides.
"""

import logging
import re
from collections.abc import Callable
from typing import Any

import orjson as json

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Registry mapping category names to compression strategy functions."""

    def __init__(self) -> None:
        """Initialize the registry with the built-in ``unknown`` passthrough."""
        self._strategies: dict[str, tuple[Callable, int]] = {}
        self._register_passthrough()

    def _register_passthrough(self) -> None:
        """Register the built-in passthrough strategy for ``unknown``."""

        def _passthrough(
            command: str,
            stdout: str,
            stderr: str,
            exit_code: int,
            verbosity: Any,  # noqa: ANN401
        ) -> Any:  # noqa: ANN401
            """Return None to signal that normal execution should proceed."""
            return None

        self._strategies["unknown"] = (_passthrough, -1)

    def register(
        self,
        category: str,
        strategy_fn: Callable,
        priority: int = 0,
    ) -> None:
        """Register a strategy function for a category.

        If a strategy is already registered for the category, the new one
        wins only when *priority* is greater than the existing priority.
        A warning is logged on collision regardless.

        Args:
            category: The command category (e.g. ``"git"``).
            strategy_fn: Callable that accepts
                ``(command, stdout, stderr, exit_code, verbosity)`` and returns
                a ``ShellCommandOutput`` or ``None``.
            priority: Higher values win on collision.  Defaults to ``0``.
        """
        existing = self._strategies.get(category)
        if existing is not None:
            _, existing_priority = existing
            if priority > existing_priority:
                logger.debug(
                    "StrategyRegistry: overriding '%s' strategy (priority %d > %d)",
                    category,
                    priority,
                    existing_priority,
                )
                self._strategies[category] = (strategy_fn, priority)
            elif priority == existing_priority:
                logger.warning(
                    "StrategyRegistry: equal-priority collision for '%s' "
                    "(priority %d == %d)",
                    category,
                    priority,
                    existing_priority,
                )
            else:
                logger.debug(
                    "StrategyRegistry: ignoring '%s' strategy registration "
                    "(priority %d < %d)",
                    category,
                    priority,
                    existing_priority,
                )
        else:
            self._strategies[category] = (strategy_fn, priority)

    def get_strategy(self, category: str) -> Callable | None:
        """Return the strategy function for *category*, or ``None``.

        The built-in ``unknown`` passthrough always returns a callable that
        itself returns ``None``.
        """
        entry = self._strategies.get(category)
        if entry is None:
            return None
        return entry[0]

    def list_categories(self) -> list[str]:
        """Return a sorted list of all registered category names."""
        return sorted(self._strategies.keys())


# Module-level singleton instance
_registry_instance: StrategyRegistry | None = None


def get_registry() -> StrategyRegistry:
    """Return the module-level singleton registry."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = StrategyRegistry()
    return _registry_instance


# ---------------------------------------------------------------------------
# Content-type stub strategies (filled by Epics 020–021)
# ---------------------------------------------------------------------------


def _register_content_stubs() -> None:
    """Register passthrough stubs for content-type strategies."""
    registry = get_registry()

    def _json_smartcrusher(
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        verbosity: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """SmartCrusher JSON compression strategy."""
        if not stdout or not stdout.strip():
            return None
        try:
            data = json.loads(stdout)
        except ValueError:
            # Not valid JSON — let passthrough handle it
            return None

        from code_muse.plugins.filter_engine.strategies.json_compressor import (
            compress_json,
        )

        compressed = compress_json(data, verbosity)

        from code_muse.tools.command_runner import ShellCommandOutput

        return ShellCommandOutput(
            success=True,
            command=command,
            stdout=compressed,
            stderr=stderr,
            exit_code=exit_code,
            execution_time=0.0,
        )

    def _diff_stub(
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        verbosity: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Stub — basic diff compaction, keeps headers only."""
        lines = stdout.splitlines()
        header_lines = [
            line
            for line in lines
            if line.startswith("@@")
            or line.startswith("diff ")
            or line.startswith("---")
            or line.startswith("+++")
        ]
        if not header_lines:
            return None
        from code_muse.tools.command_runner import ShellCommandOutput

        return ShellCommandOutput(
            success=True,
            command=command,
            stdout="\n".join(header_lines) + f"\n[{len(lines)} lines in full diff]",
            stderr=stderr,
            exit_code=exit_code,
            execution_time=0.0,
        )

    def _log_stub(
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        verbosity: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Stub — basic log dedup, groups repeated lines."""
        lines = stdout.splitlines()
        if len(lines) < 10:
            return None
        # Simple: just count unique patterns
        from collections import Counter

        # Keep first 3 and last 3 lines, dedup middle
        if len(lines) <= 6:
            return None
        head = lines[:3]
        tail = lines[-3:]
        middle_patterns = Counter(re.sub(r"\d+", "<N>", line) for line in lines[3:-3])
        compact = (
            head
            + [f"[{len(lines) - 6} lines, {len(middle_patterns)} unique patterns]"]
            + tail
        )
        from code_muse.tools.command_runner import ShellCommandOutput

        return ShellCommandOutput(
            success=True,
            command=command,
            stdout="\n".join(compact),
            stderr=stderr,
            exit_code=exit_code,
            execution_time=0.0,
        )

    def _html_stub(
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        verbosity: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Stub — basic HTML tag strip."""
        # Strip all tags, keep text content
        text = re.sub(r"<[^>]+>", " ", stdout)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) < 10:
            return None
        from code_muse.tools.command_runner import ShellCommandOutput

        return ShellCommandOutput(
            success=True,
            command=command,
            stdout=text[:2000] + ("..." if len(text) > 2000 else ""),
            stderr=stderr,
            exit_code=exit_code,
            execution_time=0.0,
        )

    def _search_stub(
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        verbosity: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Stub — basic search result compaction."""
        # Keep only filename:line:match lines, drop context
        lines = stdout.splitlines()
        match_lines = [
            line
            for line in lines
            if re.match(r"^\S+\.\w+:\d+:", line) or line.startswith("Found ")
        ]
        if not match_lines and lines:
            match_lines = lines[:10]  # keep first 10 if no matches identified
        from code_muse.tools.command_runner import ShellCommandOutput

        return ShellCommandOutput(
            success=True,
            command=command,
            stdout="\n".join(match_lines)
            + (
                f"\n[{len(lines)} total lines]" if len(lines) > len(match_lines) else ""
            ),
            stderr=stderr,
            exit_code=exit_code,
            execution_time=0.0,
        )

    registry.register("json", _json_smartcrusher, priority=10)
    registry.register("diff", _diff_stub, priority=10)
    registry.register("log", _log_stub, priority=10)
    registry.register("html", _html_stub, priority=10)
    registry.register("search", _search_stub, priority=10)


# Call at module load time
_register_content_stubs()
