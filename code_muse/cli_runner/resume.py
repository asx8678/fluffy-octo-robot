"""Resume session logic for Muse."""

import sys
from pathlib import Path

from code_muse.agents import get_current_agent
from code_muse.messaging import emit_error, emit_success, emit_warning
from code_muse.session_storage import load_session


def _resume_session_from_path(raw_path: str, *, allow_legacy: bool = False) -> None:
    """Restore agent message history from a saved session file.

    Accepts any path (autosaves, contexts, somewhere weird on disk). We don't
    care where it lives — we just decompose into (parent_dir, stem) and reuse
    ``session_storage.load_session`` so we stay DRY.
    """

    session_path = Path(raw_path).expanduser().resolve()

    if not session_path.exists():
        emit_error(f"--resume: session file not found: {session_path}")
        sys.exit(1)

    if session_path.suffix == ".json":
        pass  # preferred format
    elif session_path.suffix == ".pkl":
        if not allow_legacy:
            emit_error(
                f"--resume: legacy pickle sessions are blocked by default. "
                f"Use --import-legacy-pickle-session if you "
                f"really need to load {session_path}"
            )
            sys.exit(1)
        emit_warning(
            "DANGER: loading legacy pickle session — this can execute arbitrary code!"
        )
    else:
        emit_error(
            f"--resume: expected a .json session file, "
            f"got '{session_path.suffix}': {session_path}"
        )
        sys.exit(1)

    try:
        history = load_session(
            session_path.stem, session_path.parent, allow_legacy=allow_legacy
        )
    except Exception as exc:
        emit_error(f"--resume: failed to load session: {exc}")
        sys.exit(1)

    try:
        agent = get_current_agent()
        agent.set_message_history(history)
    except Exception as exc:
        emit_error(f"--resume: failed to attach history to agent: {exc}")
        sys.exit(1)

    # Rotate autosave id so we don't clobber the original file we just resumed.
    try:
        from code_muse.config import rotate_autosave_id

        rotate_autosave_id()
    except Exception:
        pass  # autosave rotation is best-effort

    total_tokens = sum(agent.estimate_tokens_for_message(m) for m in history)
    emit_success(
        f"✅ Resumed session: {len(history)} messages ({total_tokens} tokens)\n"
        f"📁 From: {session_path}"
    )
