"""/restore slash command for checkpointing rewind."""

import logging
import subprocess
from pathlib import Path
from typing import Any

from code_muse.tools.common import get_user_approval_async

logger = logging.getLogger(__name__)


def _custom_help() -> list[tuple[str, str]]:
    return [
        (
            "restore",
            "List checkpoints or revert to a previous checkpoint (files and/or conversation)",
        )
    ]


def _handle_restore_command(command: str) -> bool:
    from code_muse.messaging import emit_error, emit_info
    from code_muse.plugins.checkpointing.conversation_snapshots import (
        list_snapshots,
        load_snapshot,
    )

    tokens = command.split()
    if len(tokens) < 2:
        # List all checkpoints
        project_root = Path.cwd()
        project_hash = _hash_project_root(str(project_root))
        repo_path = Path.home() / ".muse" / "history" / project_hash
        snapshots = list_snapshots(repo_path)
        if not snapshots:
            emit_info("No checkpoints available yet.")
            return True

        lines = [":rewind: Available checkpoints:"]
        for idx, snap in enumerate(snapshots, start=1):
            ts = snap.get("timestamp", "")
            tool = snap.get("tool_name", "")
            lines.append(f"  {idx}. [{ts}] {tool}")

        emit_info("\n".join(lines))
        emit_info("Usage: /restore <index> [full|files|conversation]")
        return True

    try:
        index = int(tokens[1])
    except ValueError:
        emit_error("/restore: index must be an integer")
        return True

    project_root = Path.cwd()
    project_hash = _hash_project_root(str(project_root))
    repo_path = Path.home() / ".muse" / "history" / project_hash
    snapshots = list_snapshots(repo_path)
    if not snapshots:
        emit_info("No checkpoints available yet.")
        return True

    if index < 1 or index > len(snapshots):
        emit_error(f"/restore: index {index} out of range (1–{len(snapshots)})")
        return True

    selected = snapshots[index - 1]
    snapshot = load_snapshot(Path(selected["path"]))
    if snapshot is None:
        emit_error("/restore: could not load selected snapshot")
        return True

    scope = "preview"
    if len(tokens) >= 3:
        scope = tokens[2].lower()
        if scope not in ("full", "files", "conversation", "preview"):
            emit_error(
                "/restore: scope must be one of full, files, conversation, preview"
            )
            return True

    if scope == "preview":
        _preview_checkpoint(selected, snapshot, project_root)
        return True

    # Confirmation dialog before destructive restore
    _run_restore(scope, selected, snapshot, project_root)
    return True


def _preview_checkpoint(
    selected: dict[str, Any], snapshot: dict[str, Any], project_root: Path
) -> None:
    from code_muse.messaging import emit_info

    commit_hash = _get_commit_hash_for_snapshot(selected, project_root)
    lines = [":mag: Checkpoint preview:"]
    lines.append(f"  Timestamp: {selected.get('timestamp', '')}")
    lines.append(f"  Tool:      {selected.get('tool_name', '')}")
    lines.append(f"  Messages:  {len(snapshot.get('messages', []))} at checkpoint")

    if commit_hash:
        try:
            diff_result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(project_root),
                    "diff",
                    f"{commit_hash}..HEAD",
                    "--stat",
                ],
                capture_output=True,
                text=True,
            )
            if diff_result.returncode == 0 and diff_result.stdout.strip():
                lines.append("  Diff since checkpoint:")
                for line in diff_result.stdout.strip().splitlines():
                    lines.append(f"    {line}")
            else:
                lines.append("  No file changes since checkpoint.")
        except Exception as exc:
            lines.append(f"  Could not compute diff: {exc}")
    else:
        lines.append("  Commit hash not available.")

    lines.append("")
    lines.append("Usage: /restore <index> [full|files|conversation]")
    emit_info("\n".join(lines))


def _run_restore(
    scope: str,
    selected: dict[str, Any],
    snapshot: dict[str, Any],
    project_root: Path,
) -> None:
    import asyncio

    from code_muse.messaging import emit_error, emit_info, emit_success

    async def _do_restore() -> bool:
        # TODO: PEP 734 async bridge — _get_commit_hash_for_snapshot uses sync subprocess
        commit_hash = await asyncio.to_thread(
            _get_commit_hash_for_snapshot, selected, project_root
        )
        restore_parts: list[str] = []
        if scope in ("full", "files"):
            restore_parts.append("files")
        if scope in ("full", "conversation"):
            restore_parts.append("conversation")

        preview_text = f"Revert {', '.join(restore_parts)} to checkpoint [{selected.get('timestamp', '')}]?"

        confirmed, feedback = await get_user_approval_async(
            title="Restore Checkpoint",
            content=preview_text,
            preview=None,
            border_style="dim white",
            agent_name="Muse",
        )
        if not confirmed:
            emit_info("Restore cancelled.")
            return False

        if scope in ("full", "files") and commit_hash:
            try:
                checkout_proc = await asyncio.create_subprocess_exec(
                    "git",
                    "-C",
                    str(project_root),
                    "checkout",
                    commit_hash,
                    "--",
                    ".",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                checkout_stdout, checkout_stderr = await checkout_proc.communicate()
                if checkout_proc.returncode != 0:
                    emit_error(f"git checkout failed: {checkout_stderr.decode()}")
                    return False
                emit_success(":white_check_mark: Files restored.")
            except Exception as exc:
                emit_error(f"File restore failed: {exc}")
                return False

        if scope in ("full", "conversation"):
            try:
                from code_muse.agents import get_current_agent

                agent = get_current_agent()
                messages = snapshot.get("messages", [])
                if messages:
                    agent.set_message_history(messages)
                    emit_success(":white_check_mark: Conversation restored.")
                else:
                    emit_info("No conversation state in snapshot.")
            except Exception as exc:
                emit_error(f"Conversation restore failed: {exc}")
                return False

        return True

    try:
        asyncio.get_running_loop()
        asyncio.create_task(_do_restore())
    except RuntimeError:
        asyncio.run(_do_restore())


def _get_commit_hash_for_snapshot(
    selected: dict[str, Any], project_root: Path
) -> str | None:
    """Find the commit hash that matches this snapshot's timestamp/tool."""
    try:
        timestamp = selected.get("timestamp", "")
        tool_name = selected.get("tool_name", "")
        log_result = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "log",
                "--oneline",
                "--format=%H %s",
            ],
            capture_output=True,
            text=True,
        )
        if log_result.returncode != 0:
            return None
        for line in log_result.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            commit_hash, message = parts
            if f"checkpoint: {tool_name}" in message and timestamp in message:
                return commit_hash
        # Fallback: return HEAD if no exact match
        head_result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        if head_result.returncode == 0:
            return head_result.stdout.strip()
    except Exception as exc:
        logger.warning(f"Could not resolve commit hash: {exc}")
    return None


def _hash_project_root(project_root: str) -> str:
    import hashlib

    return hashlib.sha256(project_root.encode()).hexdigest()


def _handle_custom_command(command: str, name: str) -> bool | None:
    if name != "restore":
        return None
    return _handle_restore_command(command)
