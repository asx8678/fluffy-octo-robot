# agent_tools.py
import asyncio
import hashlib
import json
import re
import threading
import traceback
from contextlib import AsyncExitStack, suppress
from contextvars import ContextVar
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Import Agent from pydantic_ai to create temporary agents for invocation
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from code_muse.callbacks import (
    on_agent_run_cancel,
    on_agent_run_context,
    on_invoke_agent,
)
from code_muse.config import (
    DATA_DIR,
    get_message_limit,
)
from code_muse.messaging import (
    SubAgentInvocationMessage,
    SubAgentResponseMessage,
    emit_error,
    emit_info,
    emit_success,
    get_message_bus,
    get_session_context,
    set_session_context,
)
from code_muse.secret_storage import atomic_write_private_json
from code_muse.tools.common import generate_group_id
from code_muse.tools.subagent_context import subagent_context

# ContextVar to track active subagent invocation tasks per-parent agent.
# Using a ContextVar ensures cancellation walks only the local subtree
# instead of every sub-agent task in the process.
_active_subagent_tasks_var: ContextVar[set[asyncio.Task]] = ContextVar(
    "_active_subagent_tasks"
)

# PERF-08: Cache model instances by name to avoid rebuilding AsyncAnthropic
# clients, ClaudeCacheAsyncClient, etc. on every invoke_agent call.
_model_instance_cache: dict[str, Any] = {}
# FREE-THREADED: _model_instance_cache_lock guards a cache accessed from async
# invoke_agent and potentially sync paths. Keep threading.Lock for safety.
_model_instance_cache_lock = threading.Lock()


def _generate_session_hash_suffix() -> str:
    """Generate a short SHA1 hash suffix based on current timestamp for uniqueness.

    Returns:
        A 6-character hex string, e.g., "a3f2b1"
    """
    timestamp = str(datetime.now().timestamp())
    return hashlib.sha1(timestamp.encode()).hexdigest()[:6]


def _sanitize_for_session_id(value: str) -> str:
    """Coerce an arbitrary string into kebab-case suitable for a session_id.

    Lowercases everything, replaces any non ``[a-z0-9]`` runs with a single
    hyphen, and strips leading/trailing hyphens.  This lets us safely embed
    agent names like ``"LPZ-Main-Coder"`` or ``"My_Agent"`` into auto-
    generated session IDs without tripping the kebab-case validator.
    """
    lowered = value.lower()
    # Replace any run of disallowed chars with a single hyphen
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    # Strip leading/trailing hyphens
    return cleaned.strip("-")


# Regex pattern for kebab-case session IDs
SESSION_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SESSION_ID_MAX_LENGTH = 128


def _validate_session_id(session_id: str) -> None:
    """Validate that a session ID follows kebab-case naming conventions.

    Args:
        session_id: The session identifier to validate

    Raises:
        ValueError: If the session_id is invalid

    Valid format:
        - Lowercase letters (a-z)
        - Numbers (0-9)
        - Hyphens (-) to separate words
        - No uppercase, no underscores, no special characters
        - Length between 1 and 128 characters

    Examples:
        Valid: "my-session", "agent-session-1", "discussion-about-code"
        Invalid: "MySession", "my_session", "my session", "my--session"
    """
    if not session_id:
        raise ValueError("session_id cannot be empty")

    if len(session_id) > SESSION_ID_MAX_LENGTH:
        raise ValueError(
            f"Invalid session_id '{session_id}': must be {SESSION_ID_MAX_LENGTH} characters or less"
        )

    if not SESSION_ID_PATTERN.match(session_id):
        raise ValueError(
            f"Invalid session_id '{session_id}': must be kebab-case "
            "(lowercase letters, numbers, and hyphens only). "
            "Examples: 'my-session', 'agent-session-1', 'discussion-about-code'"
        )


def _get_subagent_sessions_dir() -> Path:
    """Get the directory for storing subagent session data.

    Returns:
        Path to XDG data directory/subagent_sessions/
    """
    sessions_dir = Path(DATA_DIR) / "subagent_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return sessions_dir


def _save_session_history(
    session_id: str,
    message_history: list[ModelMessage],
    agent_name: str,
    initial_prompt: str | None = None,
) -> None:
    """Save session history to filesystem as JSON with atomic private writes.

    Writes a canonical ``.json`` file with the session message history.

    Args:
        session_id: The session identifier (must be kebab-case)
        message_history: List of messages to save
        agent_name: Name of the agent being invoked
        initial_prompt: The first prompt that started this session (for .txt metadata)

    Raises:
        ValueError: If session_id is not valid kebab-case format
    """
    # Validate session_id format before saving
    _validate_session_id(session_id)

    sessions_dir = _get_subagent_sessions_dir()

    # Build the JSON payload
    session_data = {
        "schema": "muse.subagent.session.v1",
        "format": "pydantic-ai-model-messages-json",
        "messages": ModelMessagesTypeAdapter.dump_python(message_history, mode="json"),
    }

    # Save canonical .json file
    json_path = sessions_dir / f"{session_id}.json"
    atomic_write_private_json(json_path, session_data)

    # Save or update txt file with metadata
    txt_path = sessions_dir / f"{session_id}.txt"
    if not txt_path.exists() and initial_prompt:
        # Only write initial metadata on first save
        metadata = {
            "session_id": session_id,
            "agent_name": agent_name,
            "initial_prompt": initial_prompt,
            "created_at": datetime.now().isoformat(),
            "message_count": len(message_history),
        }
        with open(txt_path, "w") as f:
            json.dump(metadata, f, indent=2)
    elif txt_path.exists():
        # Update message count on subsequent saves
        try:
            with open(txt_path) as f:
                metadata = json.load(f)
            metadata["message_count"] = len(message_history)
            metadata["last_updated"] = datetime.now().isoformat()
            with open(txt_path, "w") as f:
                json.dump(metadata, f, indent=2)
        except Exception:
            pass  # If we can't update metadata, no big deal


def _load_session_history(session_id: str) -> list[ModelMessage]:
    """Load session history from filesystem.

    Prefers the canonical ``.json`` file; falls back to ``.pkl``
    (which contains the same JSON payload for backward compat).

    Args:
        session_id: The session identifier (must be kebab-case)

    Returns:
        List of ModelMessage objects, or empty list if session doesn't exist

    Raises:
        ValueError: If session_id is not valid kebab-case format
    """
    # Validate session_id format before loading
    _validate_session_id(session_id)

    sessions_dir = _get_subagent_sessions_dir()

    # Try canonical .json first
    json_path = sessions_dir / f"{session_id}.json"
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                session_data = json.load(f)
            raw_messages = session_data.get("messages", [])
            if isinstance(raw_messages, list):
                try:
                    return ModelMessagesTypeAdapter.validate_python(raw_messages)
                except Exception:
                    # Validation may fail due to pydantic-ai version
                    # differences; return raw messages as best effort
                    return raw_messages
        except Exception:
            pass

    # Try compat .pkl (contains JSON written by current save)
    pkl_path = sessions_dir / f"{session_id}.pkl"
    if pkl_path.exists():
        try:
            with open(pkl_path, encoding="utf-8") as f:
                session_data = json.load(f)
            raw_messages = session_data.get("messages", [])
            if isinstance(raw_messages, list):
                try:
                    return ModelMessagesTypeAdapter.validate_python(raw_messages)
                except Exception:
                    return raw_messages
        except (UnicodeDecodeError, ValueError):
            pass

    return []


class AgentInfo(BaseModel):
    """Information about an available agent."""

    name: str
    display_name: str
    description: str


class ListAgentsOutput(BaseModel):
    """Output for the list_agents tool."""

    agents: list[AgentInfo]
    error: str | None = None


class AgentInvokeOutput(BaseModel):
    """Output for the invoke_agent tool."""

    response: str | None
    agent_name: str
    session_id: str | None = None
    error: str | None = None


def register_list_agents(agent):
    """Register the list_agents tool with the provided agent.

    Args:
        agent: The agent to register the tool with
    """

    @agent.tool
    def list_agents(context: RunContext) -> ListAgentsOutput:
        """List all available sub-agents that can be invoked."""
        # Generate a group ID for this tool execution
        group_id = generate_group_id("list_agents")

        from rich.text import Text

        from code_muse.config import get_banner_color

        list_agents_color = get_banner_color("list_agents")

        try:
            from code_muse.agents import get_agent_descriptions, get_available_agents

            # Get available agents and their descriptions from the agent manager
            agents_dict = get_available_agents()
            descriptions_dict = get_agent_descriptions()

            # Convert to list of AgentInfo objects
            agents = [
                AgentInfo(
                    name=name,
                    display_name=display_name,
                    description=descriptions_dict.get(name, "No description available"),
                )
                for name, display_name in agents_dict.items()
            ]

            # Quiet output - banner and count on same line
            agent_count = len(agents)
            emit_info(
                Text.from_markup(
                    f"[bold white on {list_agents_color}] LIST AGENTS [/bold white on {list_agents_color}] "
                    f"[dim]Found {agent_count} agent(s).[/dim]"
                ),
                message_group=group_id,
            )

            return ListAgentsOutput(agents=agents)

        except Exception as e:
            error_msg = f"Error listing agents: {str(e)}"
            emit_error(error_msg, message_group=group_id)
            return ListAgentsOutput(agents=[], error=error_msg)

    return list_agents


def register_invoke_agent(agent):
    """Register the invoke_agent tool with the provided agent.

    Args:
        agent: The agent to register the tool with
    """

    @agent.tool
    async def invoke_agent(
        context: RunContext, agent_name: str, prompt: str, session_id: str | None = None
    ) -> AgentInvokeOutput:
        """Invoke a specific sub-agent with a given prompt.

        Returns:
            AgentInvokeOutput: Contains response, agent_name, session_id, and error fields.
        """
        from code_muse.agents.agent_manager import load_agent

        # Validate user-provided session_id if given
        if session_id is not None:
            try:
                _validate_session_id(session_id)
            except ValueError as e:
                # Return error immediately if session_id is invalid
                group_id = generate_group_id("invoke_agent", agent_name)
                emit_error(str(e), message_group=group_id)
                return AgentInvokeOutput(
                    response=None, agent_name=agent_name, error=str(e)
                )

        # Generate a group ID for this tool execution
        group_id = generate_group_id("invoke_agent", agent_name)

        # Check if this is an existing session or a new one
        # For user-provided session_id, check if it exists
        # For None, we'll generate a new one below
        if session_id is not None:
            message_history = _load_session_history(session_id)
            is_new_session = len(message_history) == 0
        else:
            message_history = []
            is_new_session = True

        # Generate or finalize session_id
        if session_id is None:
            # Auto-generate a session ID with hash suffix for uniqueness
            # Example: "qa-expert-session-a3f2b1"
            # Sanitize agent_name to kebab-case so capitalised names like
            # "LPZ-Main-Coder" don't produce invalid session IDs.
            hash_suffix = _generate_session_hash_suffix()
            safe_agent_name = _sanitize_for_session_id(agent_name) or "agent"
            session_id = f"{safe_agent_name}-session-{hash_suffix}"
        elif is_new_session:
            # User provided a base name for a NEW session - append hash suffix
            # Example: "review-auth" -> "review-auth-a3f2b1"
            # Sanitize the user-provided base to be forgiving of casing/
            # underscores while still producing a valid kebab-case ID.
            hash_suffix = _generate_session_hash_suffix()
            safe_base = _sanitize_for_session_id(session_id) or "session"
            session_id = f"{safe_base}-{hash_suffix}"
        # else: continuing existing session, use session_id as-is

        # Lazy imports to avoid circular dependency
        from code_muse.agents.subagent_stream_handler import subagent_stream_handler

        # Fire plugin hook so plugins can observe/log agent invocations
        with suppress(Exception):
            await on_invoke_agent(
                agent_name, prompt, session_id=session_id, context=context
            )

        # Emit structured invocation message via MessageBus
        bus = get_message_bus()
        bus.emit(
            SubAgentInvocationMessage(
                agent_name=agent_name,
                session_id=session_id,
                prompt=prompt,
                is_new_session=is_new_session,
                message_count=len(message_history),
            )
        )

        # Save current session context and set the new one for this sub-agent
        previous_session_id = get_session_context()
        set_session_context(session_id)

        # Set browser session for browser tools (qa-iris, etc.)
        # This allows parallel agent invocations to each have their own browser
        from code_muse.tools.browser.browser_manager import (
            set_browser_session,
        )

        browser_session_token = set_browser_session(f"browser-{session_id}")

        # Bound up-front so the ``except`` block can always reach for it even
        # if load_agent() itself fails before assignment.
        agent_config = None

        try:
            # Lazy import to break circular dependency with messaging module
            from code_muse.model_factory import ModelFactory, make_model_settings

            # Load the specified agent config
            agent_config = load_agent(agent_name)

            # Seed the wrapper's message history with the loaded session so that
            # ``make_history_processor(agent_config)`` — wired into the temp
            # agent's ``history_processors`` — mutates ``agent_config._message_history``
            # in place as the run progresses. That means on a mid-run crash we
            # can read partial progress straight off the wrapper below.
            agent_config.set_message_history(list(message_history))

            # Get the current model for creating a temporary agent
            model_name = agent_config.get_model_name()
            models_config = ModelFactory.load_config()

            # Only proceed if we have a valid model configuration
            if model_name not in models_config:
                raise ValueError(f"Model '{model_name}' not found in configuration")

            # PERF-08: Reuse cached model instance for the same model name
            with _model_instance_cache_lock:
                model = _model_instance_cache.get(model_name)
            if model is None:
                model = ModelFactory.get_model(model_name, models_config)
                with _model_instance_cache_lock:
                    _model_instance_cache[model_name] = model

            # Create a temporary agent instance to avoid interfering with current agent state
            instructions = agent_config.get_full_system_prompt()

            # Add AGENTS.md content to subagents.
            # ``load_muse_rules`` lives on the builder module since the
            # base_agent split in 79dfc3c8; it's not a method on the agent.
            from code_muse.agents._builder import load_muse_rules

            agent_rules = load_muse_rules()
            if agent_rules:
                instructions += f"\n\n{agent_rules}"

            # Apply prompt additions (like file permission handling) to temporary agents
            from code_muse import callbacks
            from code_muse.model_utils import prepare_prompt_for_model

            prompt_additions = callbacks.on_load_prompt()
            if len(prompt_additions):
                instructions += "\n" + "\n".join(
                    str(p) for p in prompt_additions if p is not None
                )

            # Handle claude-code models: swap instructions, and prepend system prompt only on first message
            prepared = prepare_prompt_for_model(
                model_name,
                instructions,
                prompt,
                prepend_system_to_user=is_new_session,  # Only prepend on first message
            )
            instructions = prepared.instructions
            prompt = prepared.user_prompt

            model_settings = make_model_settings(model_name)

            external_servers = []

            from code_muse.agents._compaction import make_history_processor

            # Build the pydantic-ai agent. external servers are always included in
            # the constructor; plugins may swap them out at run
            # time via the ``agent_run_context`` hook if their wrapper can't
            # handle them directly.
            temp_agent = Agent(
                model=model,
                instructions=instructions,
                output_type=str,
                retries=3,
                toolsets=external_servers,
                history_processors=[make_history_processor(agent_config)],
                model_settings=model_settings,
            )

            # Register the tools that the agent needs
            from code_muse.tools import register_tools_for_agent

            agent_tools = agent_config.get_available_tools()
            register_tools_for_agent(temp_agent, agent_tools, model_name=model_name)

            # Always use subagent_stream_handler to silence output and update console manager
            # This ensures all sub-agent output goes through the aggregated dashboard
            stream_handler = partial(subagent_stream_handler, session_id=session_id)

            # Wrap the agent run in subagent context for tracking
            with subagent_context(agent_name):
                run_ctxs = on_agent_run_context(agent_config, temp_agent, group_id)
                async with AsyncExitStack() as stack:
                    for cm in run_ctxs:
                        await stack.enter_async_context(cm)
                    task = asyncio.create_task(
                        temp_agent.run(
                            prompt,
                            message_history=message_history,
                            usage_limits=UsageLimits(request_limit=get_message_limit()),
                            event_stream_handler=stream_handler,
                        )
                    )
                    try:
                        tasks = _active_subagent_tasks_var.get()
                    except LookupError:
                        tasks = set()
                        _active_subagent_tasks_var.set(tasks)
                    tasks.add(task)

                    try:
                        result = await task
                    finally:
                        tasks.discard(task)
                        if task.cancelled():
                            await on_agent_run_cancel(group_id)

            # Extract the response from the result
            response = result.output

            # Update the session history with the new messages from this interaction
            # The result contains all_messages which includes the full conversation
            updated_history = result.all_messages()

            # Save to filesystem (include initial prompt only for new sessions)
            _save_session_history(
                session_id=session_id,
                message_history=updated_history,
                agent_name=agent_name,
                initial_prompt=prompt if is_new_session else None,
            )

            # Emit structured response message via MessageBus
            bus.emit(
                SubAgentResponseMessage(
                    agent_name=agent_name,
                    session_id=session_id,
                    response=response,
                    message_count=len(updated_history),
                )
            )

            # Emit clean completion summary
            emit_success(
                f"✓ {agent_name} completed successfully", message_group=group_id
            )

            return AgentInvokeOutput(
                response=response, agent_name=agent_name, session_id=session_id
            )

        except Exception as e:
            # Emit clean failure summary
            emit_error(f"✗ {agent_name} failed: {str(e)}", message_group=group_id)

            # Full traceback for debugging
            error_msg = f"Error invoking agent '{agent_name}': {traceback.format_exc()}"
            emit_error(error_msg, message_group=group_id)

            # Save whatever progress the agent made before crashing. The history
            # processor keeps ``agent_config._message_history`` in sync with each
            # completed turn, so this captures every committed turn up to the
            # failure point. Best-effort: a save failure must not mask the
            # original error, so we swallow anything the save itself raises.
            try:
                partial_history = (
                    agent_config.get_message_history() if agent_config else []
                )
                if partial_history and len(partial_history) > len(message_history):
                    _save_session_history(
                        session_id=session_id,
                        message_history=partial_history,
                        agent_name=agent_name,
                        initial_prompt=prompt if is_new_session else None,
                    )
                    emit_info(
                        f"💾 Saved partial session '{session_id}' "
                        f"({len(partial_history)} message(s)) before error",
                        message_group=group_id,
                    )
            except Exception:
                pass

            return AgentInvokeOutput(
                response=None,
                agent_name=agent_name,
                session_id=session_id,
                error=error_msg,
            )

        finally:
            # Restore the previous session context
            set_session_context(previous_session_id)
            # Reset browser session context
            from code_muse.tools.browser.browser_manager import (
                _browser_session_var,
            )

            _browser_session_var.reset(browser_session_token)

    return invoke_agent
