"""Callback registration for the Blackboard plugin.

Registers:
    - Tools: ``post_blackboard_artifact``, ``query_blackboard``,
      ``get_blackboard_artifact``, ``clear_blackboard_scope``
    - ``custom_command``: ``/blackboard status``, ``/blackboard list``,
      ``/blackboard clear``, ``/blackboard durable on|off``
    - ``custom_command_help``: help entries
    - ``load_prompt``: guidance for multi-agent blackboard handoffs
    - ``startup``: load durable artifacts if enabled
    - ``shutdown``: log final stats
    - ``invoke_agent``: record invocation provenance artifact
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning
from code_muse.plugins.blackboard.config import (
    is_durable_enabled,
    set_durable_enabled,
)
from code_muse.plugins.blackboard.durable import (
    durable_clear_scope,
    durable_load,
    durable_post,
    durable_rebuild_clean,
)
from code_muse.plugins.blackboard.models import (
    ArtifactKind,
    BlackboardArtifact,
    BlackboardScopeType,
)
from code_muse.plugins.blackboard.store import get_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------


def _get_current_session_id() -> str:
    """Best-effort retrieval of current session id."""
    try:
        from code_muse.messaging import get_session_context

        sid = get_session_context()
        if sid:
            return sid
    except Exception:
        pass
    return "default"


def _get_current_agent_name() -> str:
    """Best-effort retrieval of current agent name."""
    try:
        from code_muse.tools.subagent_context import get_subagent_name

        name = get_subagent_name()
        if name:
            return name
    except Exception:
        pass
    return "main"


def _resolve_scope_id(scope_id: str | None, scope_type: BlackboardScopeType) -> str:
    """Resolve scope_id: if None, use session id for session scope, else 'default'."""
    if scope_id is not None:
        return scope_id
    if scope_type == BlackboardScopeType.session:
        return _get_current_session_id()
    return "default"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def _register_blackboard_tools() -> list[dict[str, Any]]:
    """Return tool definitions for the blackboard plugin."""

    def register_post_blackboard_artifact(agent) -> None:
        @agent.tool
        def post_blackboard_artifact(
            context,
            kind: str,
            title: str,
            content: str,
            summary: str = "",
            tags: list[str] | None = None,
            scope_type: str = "session",
            scope_id: str | None = None,
            parent_artifact_id: str | None = None,
        ) -> dict[str, Any]:
            """Post a typed artifact to the blackboard for inter-agent communication.

            Use this to share structured information (designs, test plans,
            bug analyses, etc.) with other agents in the same scope without
            bloating prompt history.

            Args:
                kind: Artifact category — one of: design_doc, test_plan,
                    bug_analysis, implementation_note, review_verdict, generic.
                title: Short human-readable title.
                content: Full artifact content.
                summary: Compact summary for token-efficient queries.
                tags: Optional searchable tags.
                scope_type: Scope visibility — 'session', 'swarm', or 'global'.
                scope_id: Scope identifier (defaults to current session id).
                parent_artifact_id: Optional parent artifact for threading.
            """
            store = get_store()

            # Validate kind
            try:
                artifact_kind = ArtifactKind(kind)
            except ValueError:
                valid = ", ".join(k.value for k in ArtifactKind)
                return {"error": f"Invalid kind '{kind}'. Valid: {valid}"}

            # Validate scope_type
            try:
                stype = BlackboardScopeType(scope_type)
            except ValueError:
                valid = ", ".join(s.value for s in BlackboardScopeType)
                return {"error": f"Invalid scope_type '{scope_type}'. Valid: {valid}"}

            resolved_scope_id = _resolve_scope_id(scope_id, stype)
            agent_name = _get_current_agent_name()
            session_id = _get_current_session_id()

            artifact = BlackboardArtifact(
                kind=artifact_kind,
                title=title,
                content=content,
                summary=summary,
                tags=tags or [],
                scope_type=stype,
                scope_id=resolved_scope_id,
                author_agent=agent_name,
                session_id=session_id,
                parent_artifact_id=parent_artifact_id,
                provenance={"agent": agent_name, "session": session_id},
            )

            store.post(artifact)

            # Persist if durable is enabled
            if is_durable_enabled():
                durable_post(artifact)

            return artifact.compact()

    def register_query_blackboard(agent) -> None:
        @agent.tool
        def query_blackboard(
            context,
            kind: str | None = None,
            tags: list[str] | None = None,
            text: str | None = None,
            scope_type: str = "session",
            scope_id: str | None = None,
            limit: int = 5,
        ) -> list[dict[str, Any]]:
            """Query the blackboard for artifacts matching filters within a scope.

            Returns compact artifact summaries (id, kind, title, summary, tags)
            instead of full content — saving tokens for the calling agent.
            Use ``get_blackboard_artifact`` to retrieve full content by id.

            Args:
                kind: Filter by artifact kind (e.g. 'design_doc', 'test_plan').
                tags: Filter by tags (all must match).
                text: Full-text search in title, content, and summary.
                scope_type: Scope visibility — 'session', 'swarm', or 'global'.
                scope_id: Scope identifier (defaults to current session id).
                limit: Max artifacts to return (default 5).
            """
            store = get_store()

            try:
                stype = BlackboardScopeType(scope_type)
            except ValueError:
                valid = ", ".join(s.value for s in BlackboardScopeType)
                return [{"error": f"Invalid scope_type '{scope_type}'. Valid: {valid}"}]

            resolved_scope_id = _resolve_scope_id(scope_id, stype)

            artifact_kind = None
            if kind:
                try:
                    artifact_kind = ArtifactKind(kind)
                except ValueError:
                    valid = ", ".join(k.value for k in ArtifactKind)
                    return [{"error": f"Invalid kind '{kind}'. Valid: {valid}"}]

            results = store.query(
                kind=artifact_kind,
                tags=tags,
                text=text,
                scope_type=stype,
                scope_id=resolved_scope_id,
                limit=limit,
            )
            return [a.compact() for a in results]

    def register_get_blackboard_artifact(agent) -> None:
        @agent.tool
        def get_blackboard_artifact(
            context,
            artifact_id: str,
            scope_type: str = "session",
            scope_id: str | None = None,
        ) -> dict[str, Any]:
            """Retrieve a single artifact by id within a scope.

            Returns the full artifact content. Use this after querying
            to get details for a specific artifact.

            Args:
                artifact_id: The artifact id (from query results).
                scope_type: Scope visibility — 'session', 'swarm', or 'global'.
                scope_id: Scope identifier (defaults to current session id).
            """
            store = get_store()

            try:
                stype = BlackboardScopeType(scope_type)
            except ValueError:
                valid = ", ".join(s.value for s in BlackboardScopeType)
                return {"error": f"Invalid scope_type '{scope_type}'. Valid: {valid}"}

            resolved_scope_id = _resolve_scope_id(scope_id, stype)
            artifact = store.get(
                artifact_id=artifact_id,
                scope_type=stype,
                scope_id=resolved_scope_id,
            )
            if artifact is None:
                return {
                    "error": (
                        f"Artifact '{artifact_id}' not found in "
                        f"scope {stype.value}:{resolved_scope_id}"
                    )
                }
            return artifact.model_dump(mode="json")

    def register_clear_blackboard_scope(agent) -> None:
        @agent.tool
        def clear_blackboard_scope(
            context,
            scope_type: str = "session",
            scope_id: str | None = None,
        ) -> dict[str, Any]:
            """Clear all artifacts in a specific scope.

            Use with care — this is destructive within the scope.
            Only clears the scope you specify; other scopes are unaffected.

            Args:
                scope_type: Scope visibility — 'session', 'swarm', or 'global'.
                scope_id: Scope identifier (defaults to current session id).
            """
            store = get_store()

            try:
                stype = BlackboardScopeType(scope_type)
            except ValueError:
                valid = ", ".join(s.value for s in BlackboardScopeType)
                return {"error": f"Invalid scope_type '{scope_type}'. Valid: {valid}"}

            resolved_scope_id = _resolve_scope_id(scope_id, stype)

            from code_muse.plugins.blackboard.models import BlackboardScope

            scope_key = BlackboardScope(
                scope_type=stype, scope_id=resolved_scope_id
            ).key

            count = store.clear(scope_type=stype, scope_id=resolved_scope_id)

            if is_durable_enabled():
                durable_clear_scope(scope_key)

            return {"scope_key": scope_key, "artifacts_removed": count}

    return [
        {
            "name": "post_blackboard_artifact",
            "register_func": register_post_blackboard_artifact,
        },
        {"name": "query_blackboard", "register_func": register_query_blackboard},
        {
            "name": "get_blackboard_artifact",
            "register_func": register_get_blackboard_artifact,
        },
        {
            "name": "clear_blackboard_scope",
            "register_func": register_clear_blackboard_scope,
        },
    ]


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Load durable artifacts on startup if persistence is enabled."""
    store = get_store()
    if is_durable_enabled():
        artifacts, deleted, cleared = durable_load()
        for artifact in artifacts:
            store.post(artifact)
        if artifacts or deleted or cleared:
            durable_rebuild_clean(artifacts)
        logger.debug(
            "Blackboard loaded %d durable artifacts "
            "(skipped %d deleted, %d cleared scopes)",
            len(artifacts),
            len(deleted),
            len(cleared),
        )
    else:
        logger.debug("Blackboard plugin initialised (durable OFF)")


def _on_shutdown() -> None:
    """Log final stats on graceful exit."""
    store = get_store()
    keys = store.all_scope_keys()
    if keys:
        logger.info("Blackboard shutdown: %d active scopes", len(keys))


# ---------------------------------------------------------------------------
# invoke_agent hook — record invocation provenance
# ---------------------------------------------------------------------------


def _on_invoke_agent(*args: Any, **kwargs: Any) -> None:
    """Record an implementation_note artifact when a sub-agent is invoked.

    This provides lightweight provenance tracking: when agent A invokes
    agent B, a compact artifact is posted in the same session scope.
    No-op if the blackboard store is empty or unavailable.
    """
    try:
        agent_name = kwargs.get("agent_name") or (args[0] if args else "unknown")
        store = get_store()
        session_id = _get_current_session_id()
        store.post(
            BlackboardArtifact(
                kind=ArtifactKind.implementation_note,
                title=f"Invoked agent: {agent_name}",
                content=f"Agent '{agent_name}' was invoked with args",
                summary=f"invoke_agent -> {agent_name}",
                scope_type=BlackboardScopeType.session,
                scope_id=session_id,
                author_agent=_get_current_agent_name(),
                session_id=session_id,
                provenance={"hook": "invoke_agent", "agent_name": str(agent_name)},
            )
        )
    except Exception:
        # Must never crash the app
        pass


# ---------------------------------------------------------------------------
# load_prompt hook — agent guidance for blackboard handoffs
# ---------------------------------------------------------------------------

_BLACKBOARD_PROMPT = """\

## Blackboard: Structured Inter-Agent Communication

You have access to a **blackboard** — a shared space for posting and
querying typed artifacts across agents.  Use it for multi-agent handoffs
instead of restating full context in prompts:

- **Planner**: Post a `design_doc` or `test_plan` artifact with your
  full reasoning, then invoke specialist agents with a brief instruction
  like *"See the design_doc on the blackboard (scope: swarm:XYZ)"*.

- **Specialist**: Query the blackboard for artifacts in your scope, then
  `get_blackboard_artifact` by id for full details. This avoids receiving
  the planner's entire reasoning history.

Tools:
- `post_blackboard_artifact(kind, title, content, summary, tags, scope_type, scope_id)`
- `query_blackboard(kind, tags, text, scope_type, scope_id, limit)`
- `get_blackboard_artifact(artifact_id, scope_type, scope_id)`
- `clear_blackboard_scope(scope_type, scope_id)`

Scopes: `session` (default, isolated by session id), `swarm` (shared by
swarm id), `global` (shared across all). Always match scope_type and
scope_id when reading/writing.
"""


def _on_load_prompt() -> str | None:
    """Inject blackboard guidance into the system prompt."""
    return _BLACKBOARD_PROMPT


# ---------------------------------------------------------------------------
# Slash commands: /blackboard status|list|clear|durable on|off
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/blackboard`` slash commands."""
    if name != "blackboard":
        return None

    parts = command.split(maxsplit=2)
    sub = parts[1].strip().lower() if len(parts) > 1 else "status"
    sub_arg = parts[2].strip() if len(parts) > 2 else ""

    store = get_store()
    session_id = _get_current_session_id()

    # --- Status ---
    if sub == "status":
        scope_keys = store.all_scope_keys()
        if not scope_keys:
            emit_info("📋 Blackboard is empty (no artifacts posted)")
            return True

        lines = ["📋 Blackboard Status", ""]
        for sk in scope_keys:
            stype, sid = _parse_scope_key(sk)
            s = store.stats(scope_type=stype, scope_id=sid)
            lines.append(
                f"  {sk}: {s['artifact_count']} artifacts, "
                f"~{s['estimated_tokens_saved']} tokens saved by summaries"
            )
        emit_info("\n".join(lines))
        return True

    # --- List ---
    if sub == "list":
        stype = BlackboardScopeType.session
        sid = session_id
        limit = 10
        # Optional: parse "list swarm:ABC 20"
        if sub_arg:
            parsed = _parse_scope_arg(sub_arg)
            stype = parsed[0]
            sid = parsed[1]
            if len(parsed) > 2:
                limit = parsed[2]

        results = store.query(scope_type=stype, scope_id=sid, limit=limit)
        if not results:
            emit_info(f"📋 No artifacts in scope {stype.value}:{sid}")
            return True

        lines = [f"📋 Artifacts in {stype.value}:{sid}:", ""]
        for a in results:
            c = a.compact()
            lines.append(f"  [{c['kind']}] {c['title']} (id={c['id']})")
            lines.append(f"    {c['summary'][:100]}")
        emit_info("\n".join(lines))
        return True

    # --- Clear ---
    if sub == "clear":
        stype = BlackboardScopeType.session
        sid = session_id
        if sub_arg:
            parsed = _parse_scope_arg(sub_arg)
            stype = parsed[0]
            sid = parsed[1]

        count = store.clear(scope_type=stype, scope_id=sid)
        if is_durable_enabled():
            from code_muse.plugins.blackboard.models import BlackboardScope

            scope_key = BlackboardScope(scope_type=stype, scope_id=sid).key
            durable_clear_scope(scope_key)

        emit_success(f"📋 Cleared {count} artifacts from {stype.value}:{sid}")
        return True

    # --- Durable on/off ---
    if sub == "durable":
        if sub_arg.lower() in ("on", "true", "1", "yes"):
            set_durable_enabled(True)
            emit_success("📋 Blackboard durable persistence: ON")
            return True
        if sub_arg.lower() in ("off", "false", "0", "no"):
            set_durable_enabled(False)
            emit_warning("📋 Blackboard durable persistence: OFF")
            return True
        state = "ON" if is_durable_enabled() else "OFF"
        emit_info(f"📋 Blackboard durable persistence: {state}")
        return True

    emit_info("Usage: /blackboard status|list|clear|durable on|off")
    return True


def _parse_scope_key(scope_key: str) -> tuple[BlackboardScopeType, str]:
    """Parse 'session:abc' or 'swarm:xyz' or 'global' into (type, id)."""
    if scope_key == "global":
        return BlackboardScopeType.global_, "global"
    if ":" in scope_key:
        stype_str, sid = scope_key.split(":", 1)
        try:
            return BlackboardScopeType(stype_str), sid
        except ValueError:
            return BlackboardScopeType.session, sid
    return BlackboardScopeType.session, scope_key


def _parse_scope_arg(arg: str) -> tuple[BlackboardScopeType, str, int]:
    """Parse 'swarm:ABC 20' into (scope_type, scope_id, limit)."""
    limit = 10
    parts = arg.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].isdigit():
        limit = int(parts[1])
        scope_str = parts[0]
    else:
        scope_str = arg

    if ":" in scope_str:
        stype_str, sid = scope_str.split(":", 1)
        try:
            return BlackboardScopeType(stype_str), sid, limit
        except ValueError:
            return BlackboardScopeType.session, scope_str, limit
    return BlackboardScopeType.session, scope_str, limit


# ---------------------------------------------------------------------------
# Help entries
# ---------------------------------------------------------------------------


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Return help entries for the ``/blackboard`` command family."""
    return [
        ("blackboard status", "Show artifact counts and token savings per scope"),
        ("blackboard list", "List artifacts in current scope"),
        ("blackboard clear", "Clear artifacts in a scope"),
        ("blackboard durable on|off", "Toggle durable JSONL persistence"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("shutdown", _on_shutdown)
register_callback("register_tools", _register_blackboard_tools)
register_callback("load_prompt", _on_load_prompt)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("invoke_agent", _on_invoke_agent)

logger.debug("Blackboard plugin callbacks registered")
