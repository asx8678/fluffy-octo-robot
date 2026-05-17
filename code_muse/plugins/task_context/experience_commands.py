"""/experience command family for the Semantic Experience Store.

Handles: status, on, off, backfill, search, list, forget.
"""

import logging

from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)


def handle_experience_command(command: str) -> bool | str | None:
    """Handle ``/experience`` subcommands.

    Returns True for side-effect commands, a string for display commands,
    or None if the command isn't ours.
    """
    from code_muse.plugins.task_context.config import (
        get_experience_config_summary,
        get_experience_global_enabled,
        set_experience_global_enabled,
        set_experience_retrieval_enabled,
    )
    from code_muse.plugins.task_context.experience_store import (
        backfill_experiences_from_archives,
        delete_capsule,
        list_capsules,
        search_experience,
    )

    tokens = command.strip().split(maxsplit=2)
    name = tokens[0].lstrip("/")

    if name != "experience":
        return None

    sub = tokens[1].strip().lower() if len(tokens) > 1 else "status"

    # --- status ---
    if sub == "status":
        return get_experience_config_summary()

    # --- on ---
    if sub == "on":
        set_experience_retrieval_enabled(True)
        emit_success("🔮 Experience retrieval enabled")
        return True

    # --- off ---
    if sub == "off":
        set_experience_retrieval_enabled(False)
        emit_info("Experience retrieval disabled")
        return True

    # --- global on / off ---
    if sub == "global":
        flag = tokens[2].strip().lower() if len(tokens) > 2 else ""
        if flag in ("on", "true", "yes"):
            set_experience_global_enabled(True)
            emit_success("🔮 Global cross-repo experience store enabled")
        elif flag in ("off", "false", "no"):
            set_experience_global_enabled(False)
            emit_info("Global cross-repo experience store disabled")
        else:
            state = "ON" if get_experience_global_enabled() else "OFF"
            emit_info(f"Global cross-repo experience store: {state}")
            emit_info("Use: /experience global on|off")
        return True

    # --- backfill ---
    if sub == "backfill":
        count = backfill_experiences_from_archives()
        emit_success(f"🔮 Backfilled {count} experience capsule(s) from archives")
        return True

    # --- search ---
    if sub == "search":
        query = tokens[2].strip() if len(tokens) > 2 else ""
        if not query:
            emit_warning("Usage: /experience search <query>")
            return True
        results = search_experience(query)
        if not results:
            emit_info("No similar experience capsules found")
            return True
        lines = ["🔮 Similar Experience Capsules:"]
        for capsule, similarity in results:
            lines.append(
                f"  • [{capsule.capsule_id[:8]}] "
                f"{capsule.task_label or '(untitled)'} "
                f"(sim: {similarity:.2f})"
            )
            if capsule.outcome_summary:
                lines.append(f"    Outcome: {capsule.outcome_summary[:100]}")
        return "\n".join(lines)

    # --- list ---
    if sub == "list":
        capsules = list_capsules()
        if not capsules:
            emit_info("No experience capsules stored")
            return True
        lines = [f"🔮 Experience Capsules ({len(capsules)}):"]
        for c in capsules:
            lines.append(
                f"  • [{c.capsule_id[:8]}] "
                f"{c.task_label or '(untitled)'} "
                f"— {c.outcome_summary[:60] or 'no summary'}"
            )
        return "\n".join(lines)

    # --- forget ---
    if sub == "forget":
        capsule_id = tokens[2].strip() if len(tokens) > 2 else ""
        if not capsule_id:
            emit_warning("Usage: /experience forget <capsule_id>")
            return True
        deleted = delete_capsule(capsule_id)
        if deleted:
            emit_success(f"🗑️ Deleted experience capsule {capsule_id[:8]}")
        else:
            emit_warning(f"No capsule found with ID {capsule_id[:8]}")
        return True

    # --- unknown subcommand ---
    emit_info("Usage: /experience status|on|off|backfill|search|list|forget|global")
    return True


def get_experience_help() -> list[tuple[str, str]]:
    """Return help entries for /experience."""
    return [
        ("experience status", "Show experience store config & stats"),
        ("experience on|off", "Enable/disable experience retrieval"),
        ("experience global on|off", "Enable/disable cross-repo global store"),
        ("experience backfill", "Create capsules from existing task archives"),
        ("experience search <query>", "Search for similar past experiences"),
        ("experience list", "List all stored experience capsules"),
        ("experience forget <id>", "Delete an experience capsule"),
    ]
