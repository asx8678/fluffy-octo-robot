"""Filter dispatcher for the filter engine.

Orchestrates classification → strategy lookup → execution → compression.
"""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_muse.plugins.filter_engine.classifier import CommandClassifier
from code_muse.plugins.filter_engine.registry import get_registry
from code_muse.plugins.filter_engine.verbosity import get_verbosity
from code_muse.tools.command_runner import ShellCommandOutput, _execute_shell_command

logger = logging.getLogger(__name__)


class FilterDispatcher:
    """Singleton dispatcher that handles the full filter pipeline."""

    _instance: FilterDispatcher | None = None

    def __init__(self) -> None:
        """Initialise the dispatcher with its classifier."""
        self.classifier = CommandClassifier()

    @classmethod
    def get_instance(cls) -> FilterDispatcher:
        """Return the module-level singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _normalize_command(command: str) -> str:
        """Rewrite plain ``git status`` to force porcelain format.

        Appends ``--porcelain -b`` when the command is ``git status`` (or
        variants like ``git -C <dir> status``) and does not already request
        porcelain or short output.

        Args:
            command: The raw shell command.

        Returns:
            The original command, or a rewritten version with porcelain flags.
        """
        stripped = command.strip()
        # Must contain git + status as separate words
        if not re.search(r"\bgit\b.*\bstatus\b", stripped):
            return command

        tokens = stripped.split()
        # Already porcelain/short — leave alone
        if any(t in {"--porcelain", "--short", "-s"} for t in tokens):
            return command

        return f"{stripped} --porcelain -b"

    async def handle(
        self,
        context: Any,
        command: str,
        cwd: str | None,
        timeout: int,
    ) -> dict[str, Any] | None:
        """Run the full filter pipeline for a shell command.

        Steps:

        1. Classify the command.
        2. Look up the strategy for the category.
        3. If the strategy is ``None`` or the ``unknown`` passthrough,
           return ``None`` so normal execution proceeds.
        4. Execute the command via :func:`_execute_shell_command`.
        5. Apply the strategy to the resulting :class:`ShellCommandOutput`.
        6. Return ``{"pre_executed": True, "output": filtered_output}``.

        On any strategy exception the error is logged and ``None`` is returned
        so the raw output is preserved as a fallback.

        Args:
            context: pydantic-ai RunContext (unused).
            command: The shell command to execute.
            cwd: Working directory.
            timeout: Timeout in seconds.

        Returns:
            A pre-executed result dict or ``None`` for passthrough.
        """
        category = self.classifier.classify(command)
        registry = get_registry()

        # Passthrough strategies return None
        if category == "unknown":
            return None

        verbosity = get_verbosity()

        # If verbosity is RAW, skip filtering entirely
        if verbosity.value >= 4:
            return None

        try:
            # Execute the command (sub-agents run silently)
            from code_muse.tools.subagent_context import is_subagent

            silent = is_subagent()
            group_id = f"filter_engine_{id(command)}"

            # Force porcelain for plain git status commands so the strategy
            # parser always receives machine-readable output.
            effective_command = self._normalize_command(command)
            if effective_command != command:
                logger.debug(
                    "FilterDispatcher: rewritten %r → %r", command, effective_command
                )

            # _execute_shell_command is async, but we are already in async context
            output = await _execute_shell_command(
                command=effective_command,
                cwd=cwd,
                timeout=timeout,
                group_id=group_id,
                silent=silent,
            )

            # -----------------------------------------------------------------
            # Content-type routing (Epic 019)
            # -----------------------------------------------------------------
            from code_muse.plugins.filter_engine.content_detector import (
                ContentType,
                ContentTypeDetector,
            )

            # Sniff only the first ~8KB for content-type detection so
            # strategy selection can begin before the full output is received.
            _SNIFF_WINDOW = 8192
            content_type = ContentTypeDetector.detect(
                (output.stdout or "")[:_SNIFF_WINDOW]
            )
            logger.debug(
                "Detected content type: %s for command: %s", content_type.value, command
            )

            content_strategy_map = {
                ContentType.JSON: "json",
                ContentType.DIFF: "diff",
                ContentType.LOG: "log",
                ContentType.HTML: "html",
                ContentType.SEARCH: "search",
                ContentType.CODE: "code",  # route directly to code strategy
                ContentType.UNKNOWN: category,
            }

            effective_category = content_strategy_map.get(content_type, category)

            strategy = registry.get_strategy(effective_category)
            if strategy is None and effective_category != category:
                logger.debug(
                    "No strategy for %s, falling back to command category %s",
                    effective_category,
                    category,
                )
                effective_category = category
                strategy = registry.get_strategy(effective_category)

            if strategy is None:
                return None

            # Apply strategy
            filtered = strategy(
                command,
                output.stdout or "",
                output.stderr or "",
                output.exit_code or 0,
                verbosity,
            )

            if filtered is None:
                return None

            # Track execution metrics (best-effort, never blocks)
            try:
                from code_muse.plugins.token_tracking.record import record_command

                record_command(
                    command=command,
                    raw_stdout=output.stdout or "",
                    raw_stderr=output.stderr or "",
                    compressed_stdout=filtered.stdout or "",
                    compressed_stderr=filtered.stderr or "",
                    category=effective_category,
                    strategy=strategy.__name__
                    if hasattr(strategy, "__name__")
                    else str(strategy),
                    exit_code=output.exit_code or 0,
                )
            except Exception:
                pass

            return {"pre_executed": True, "output": filtered}
        except Exception:
            logger.exception("FilterDispatcher: strategy failed for %r", command)
            # Tee recovery: save raw output so user can recover
            try:
                import tempfile

                raw_stdout = (
                    getattr(locals().get("output"), "stdout", "(unavailable)")
                    or "(empty)"
                )
                raw_stderr = (
                    getattr(locals().get("output"), "stderr", "(unavailable)")
                    or "(empty)"
                )

                tee_dir = Path(tempfile.gettempdir()) / "muse_tee"
                tee_dir.mkdir(exist_ok=True)
                ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                cmd_hash = hash(command) & 0xFFFF
                tee_path = tee_dir / f"tee_{ts}_{cmd_hash:04x}.txt"
                tee_path.write_text(
                    f"# Raw output saved after filter error\n"
                    f"# Command: {command}\n"
                    f"# Timestamp: {datetime.now(UTC).isoformat()}\n\n"
                    f"STDOUT:\n{raw_stdout}\n\n"
                    f"STDERR:\n{raw_stderr}\n"
                )
                tee_path.chmod(0o600)  # user-only readable
                logger.warning(
                    "⚠ FilterDispatcher: tee recovery wrote raw output to %s", tee_path
                )
                # Return hint that includes the tee path
                return {
                    "pre_executed": True,
                    "output": ShellCommandOutput(
                        success=False,
                        command=command,
                        stdout=f"⚠ Filter error — raw output saved to {tee_path}",
                        stderr="",
                        exit_code=-1,
                        execution_time=0.0,
                    ),
                }
            except Exception as tee_exc:
                logger.error("Tee recovery itself failed: %s", tee_exc)
            return None
