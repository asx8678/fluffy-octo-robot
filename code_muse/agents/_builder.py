"""Pydantic-ai agent construction, extracted from ``BaseAgent``.

Collapses the previous duplicated build paths and the parallel
``_create_agent_with_output_type`` method into a single ``build_pydantic_agent``
entry point. Everything else in here (muse rules loading, model fallback,
and related helpers) is a pure free function.
"""

import uuid
from pathlib import Path
from typing import Any

from pydantic_ai import Agent as PydanticAgent

from code_muse.agents._compaction import make_history_processor
from code_muse.config import (
    CONFIG_DIR,
    get_global_model_name,
)
from code_muse.messaging import emit_error, emit_info, emit_warning
from code_muse.model_factory import ModelFactory, make_model_settings

_AGENT_RULE_FILES = ("AGENTS.md", "AGENT.md", "agents.md", "agent.md")
_MUSE_DIR = ".muse"


def load_muse_rules() -> str | None:
    """Load AGENT(S).md from global config dir and/or the current project dir.

    Global rules (``~/.muse/AGENTS.md``) come first; project-local rules
    are appended, allowing projects to override/extend global ones.

    **Search order for project rules:**

    1. ``.muse/AGENTS.md`` (preferred — keeps root clean)
    2. ``./AGENTS.md`` (alternate location)

    Returns ``None`` if neither exists.
    """
    global_rules: str | None = None
    for name in _AGENT_RULE_FILES:
        candidate = Path(CONFIG_DIR) / name
        if candidate.exists():
            global_rules = candidate.read_text(encoding="utf-8-sig")
            break

    project_rules: str | None = None

    # Priority 1: Check .muse/ directory (preferred location)
    muse_dir = Path(_MUSE_DIR)
    if muse_dir.is_dir():
        for name in _AGENT_RULE_FILES:
            candidate = muse_dir / name
            if candidate.exists():
                project_rules = candidate.read_text(encoding="utf-8-sig")
                break

    # Priority 2: Fallback to project root
    if project_rules is None:
        for name in _AGENT_RULE_FILES:
            candidate = Path(name)
            if candidate.exists():
                project_rules = candidate.read_text(encoding="utf-8-sig")
                break

    rules = [r for r in (global_rules, project_rules) if r]
    return "\n\n".join(rules) if rules else None


def load_model_with_fallback(
    requested_model_name: str,
    models_config: dict[str, Any],
    message_group: str,
) -> tuple[Any, str]:
    """Load the requested model, or fall back to a sensible alternative.

    Falls back in order: the globally configured model, then any other
    configured model. Raises ``ValueError`` only if nothing loads.
    """
    try:
        return ModelFactory.get_model(
            requested_model_name, models_config
        ), requested_model_name
    except ValueError as exc:
        available = list(models_config.keys())
        available_str = (
            ", ".join(sorted(available)) if available else "no configured models"
        )
        emit_warning(
            f"Model '{requested_model_name}' not found. Available models: {available_str}",
            message_group=message_group,
        )

        candidates: list[str] = []
        global_candidate = get_global_model_name()
        if global_candidate:
            candidates.append(global_candidate)
        for candidate in available:
            if candidate not in candidates:
                candidates.append(candidate)

        for candidate in candidates:
            if not candidate or candidate == requested_model_name:
                continue
            try:
                model = ModelFactory.get_model(candidate, models_config)
                emit_info(
                    f"Using fallback model: {candidate}", message_group=message_group
                )
                return model, candidate
            except ValueError:
                continue

        friendly = (
            "No valid model could be loaded. Update the model configuration or "
            "set a valid model with `config set`."
        )
        emit_error(friendly, message_group=message_group)
        raise ValueError(friendly) from exc


def _assemble_instructions(agent: Any, resolved_model_name: str) -> str:
    """Compose full system prompt + muse rules + extended-thinking note."""
    from code_muse.model_utils import prepare_prompt_for_model
    from code_muse.tools import (
        EXTENDED_THINKING_PROMPT_NOTE,
        has_extended_thinking_active,
    )

    instructions = agent.get_full_system_prompt()
    agent_rules = load_muse_rules()
    if agent_rules:
        instructions += f"\n{agent_rules}"

    if has_extended_thinking_active(resolved_model_name):
        instructions += EXTENDED_THINKING_PROMPT_NOTE

    # Append plugin prompt additions (file permission rules, skill docs, etc.)
    from code_muse import callbacks as _cb

    prompt_additions = _cb.on_load_prompt()
    if prompt_additions:
        instructions += "\n" + "\n".join(str(p) for p in prompt_additions if p)

    prepared = prepare_prompt_for_model(
        agent.get_model_name(), instructions, "", prepend_system_to_user=False
    )
    return prepared.instructions


def build_pydantic_agent(
    agent: Any,
    output_type: Any = str,
    message_group: str | None = None,
) -> Any:
    """Build (and wire up) the pydantic-ai agent for ``agent``.

    Replaces the old ``reload_code_generation_agent`` + ``_create_agent_with_output_type``
    pair. Side effects on ``agent``:

    - ``agent._muse_rules = None`` (invalidates any cached rules)
    - ``agent.cur_model``             ← resolved pydantic-ai model
    - ``agent._last_model_name``      ← resolved model name
    - ``agent.pydantic_agent``        ← the final pydantic-ai agent
    - ``agent._code_generation_agent`` ← same as ``pydantic_agent``
    The build happens in a single pass with the final toolsets and registered
    tools.
    """
    from code_muse.tools import register_tools_for_agent

    agent._muse_rules = None
    message_group = message_group or str(uuid.uuid4())

    models_config = ModelFactory.load_config()
    model, resolved_model_name = load_model_with_fallback(
        agent.get_model_name(), models_config, message_group
    )
    instructions = _assemble_instructions(agent, resolved_model_name)
    model_settings = make_model_settings(resolved_model_name)
    history_processor = make_history_processor(agent)

    def _new_pydantic_agent(toolsets: list[Any]) -> PydanticAgent:
        return PydanticAgent(
            model=model,
            instructions=instructions,
            output_type=output_type,
            tool_retries=3,
            toolsets=toolsets,
            history_processors=[history_processor],
            model_settings=model_settings,
        )

    agent_tools = agent.get_available_tools()
    final_toolsets = []

    final_pydantic = _new_pydantic_agent(toolsets=final_toolsets)
    register_tools_for_agent(
        final_pydantic, agent_tools, model_name=resolved_model_name
    )

    agent.cur_model = model
    agent._last_model_name = resolved_model_name

    agent.pydantic_agent = final_pydantic
    agent._code_generation_agent = final_pydantic
    return final_pydantic
