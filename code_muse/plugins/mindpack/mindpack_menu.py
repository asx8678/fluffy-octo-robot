"""Interactive terminal UI for configuring MindPack experts.

Provides a split-panel interface for browsing, adding, editing,
and deleting MindPack expert descriptors — following the same
UI patterns as agent_menu.py.
"""

import asyncio
import logging
import re
import sys
import unicodedata

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame

from code_muse.command_line.model_picker_completion import load_model_names
from code_muse.command_line.pagination import (
    ensure_visible_page,
    get_page_bounds,
    get_page_for_index,
    get_total_pages,
)
from code_muse.messaging import emit_info, emit_success, emit_warning
from code_muse.plugins.mindpack.schemas import ExpertDescriptor, ProfileDescriptor
from code_muse.plugins.mindpack.tools import orchestrator
from code_muse.tools.command_runner import set_awaiting_user_input
from code_muse.tools.common import arrow_select_async

logger = logging.getLogger(__name__)

PAGE_SIZE = 10  # Experts per page

# ---------------------------------------------------------------------------
# Preset expert templates
# ---------------------------------------------------------------------------

PRESET_EXPERTS = [
    ExpertDescriptor(
        name="SecurityReviewer",
        speciality="security analysis & vulnerability assessment",
        system_prompt_fragment=(
            "You are SecurityReviewer, the security specialist. "
            "Your job is to identify security vulnerabilities, "
            "check for OWASP Top 10 issues, validate authentication/authorization "
            "flows, and ensure secure coding practices are followed. "
            "Focus on: input validation, SQL injection, XSS, CSRF, "
            "authentication bypasses, and data exposure risks."
        ),
        model="strong",
    ),
    ExpertDescriptor(
        name="PerfReviewer",
        speciality="performance analysis & optimization",
        system_prompt_fragment=(
            "You are PerfReviewer, the performance specialist. "
            "Your job is to identify performance bottlenecks, "
            "analyze algorithmic complexity, review database query efficiency, "
            "and suggest optimization strategies. "
            "Focus on: time complexity, memory usage, N+1 queries, "
            "caching opportunities, and scalability concerns."
        ),
        model="medium",
    ),
    ExpertDescriptor(
        name="UXReviewer",
        speciality="user experience & accessibility review",
        system_prompt_fragment=(
            "You are UXReviewer, the user experience specialist. "
            "Your job is to review code changes from a user-centric perspective, "
            "check accessibility compliance (WCAG), validate error handling UX, "
            "and ensure intuitive interfaces. "
            "Focus on: accessibility (a11y), error messages, loading states, "
            "responsive design, and user flow clarity."
        ),
        model="medium",
    ),
    ExpertDescriptor(
        name="APReviewer",
        speciality="API design & REST conventions",
        system_prompt_fragment=(
            "You are APIReviewer, the API design specialist. "
            "Your job is to review API endpoints for REST compliance, "
            "validate request/response schemas, check HTTP status codes, "
            "and ensure consistent API conventions. "
            "Focus on: RESTful design, OpenAPI schema validation, "
            "versioning strategy, error response format, and idempotency."
        ),
        model="strong",
    ),
    ExpertDescriptor(
        name="DBReviewer",
        speciality="database schema & query optimization",
        system_prompt_fragment=(
            "You are DBReviewer, the database specialist. "
            "Your job is to review schema migrations, analyze query performance, "
            "check indexing strategy, and validate data integrity constraints. "
            "Focus on: migration safety, index usage, N+1 queries, "
            "transaction boundaries, and normalization vs. performance tradeoffs."
        ),
        model="medium",
    ),
]

# ---------------------------------------------------------------------------
# MindPack default settings (used by settings panel)
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    "spawn_mode": "fixed",
    "default_expert_count": "5",
}


def _sanitize_display_text(text: str) -> str:
    """Remove or replace characters that cause terminal rendering issues.

    Args:
        text: Text that may contain emojis or wide characters

    Returns:
        Sanitized text safe for prompt_toolkit rendering
    """
    result = []
    for char in text:
        cat = unicodedata.category(char)
        safe_categories = (
            "Lu",
            "Ll",
            "Lt",
            "Lm",
            "Lo",
            "Nd",
            "Nl",
            "No",
            "Pc",
            "Pd",
            "Ps",
            "Pe",
            "Pi",
            "Pf",
            "Po",
            "Zs",
            "Sm",
            "Sc",
            "Sk",
        )
        if cat in safe_categories:
            result.append(char)

    cleaned = " ".join("".join(result).split())
    return cleaned


# ---------------------------------------------------------------------------
# Expert list helpers
# ---------------------------------------------------------------------------


def _get_expert_entries() -> list[ExpertDescriptor]:
    """Return the current expert registry, sorted by name."""
    return sorted(orchestrator.expert_registry, key=lambda e: e.name.lower())


def _get_profile_entries() -> list[ProfileDescriptor]:
    """Return the current profile registry, sorted by name
    with 'Default' always last."""
    profiles = orchestrator.profile_registry
    default = [p for p in profiles if p.name == "Default"]
    others = sorted(
        [p for p in profiles if p.name != "Default"],
        key=lambda p: p.name.lower(),
    )
    return others + default


def _get_expert_entries_for_profile(profile_name: str) -> list[ExpertDescriptor]:
    """Return experts belonging to a specific profile, sorted by name."""
    return sorted(
        orchestrator.get_experts_for_profile(profile_name),
        key=lambda e: e.name.lower(),
    )


# ---------------------------------------------------------------------------
# Menu panel rendering
# ---------------------------------------------------------------------------


def _render_menu_panel(
    entries: list[ExpertDescriptor],
    page: int,
    selected_idx: int,
) -> list:
    """Render the left menu panel with pagination.

    Args:
        entries: list of ExpertDescriptor
        page: Current page number (0-indexed)
        selected_idx: Currently selected index (global)

    Returns:
        list of (style, text) tuples for FormattedTextControl
    """
    lines: list[tuple[str, str]] = []
    total_pages = get_total_pages(len(entries), PAGE_SIZE)
    start_idx, end_idx = get_page_bounds(page, len(entries), PAGE_SIZE)

    lines.append(("bold", "Experts"))
    lines.append(("fg:ansibrightblack", f" (Page {page + 1}/{total_pages})"))
    lines.append(("", "\n\n"))

    if not entries:
        lines.append(("fg:yellow", "  No experts configured."))
        lines.append(("", "\n\n"))
    else:
        for i in range(start_idx, end_idx):
            expert = entries[i]
            is_selected = i == selected_idx

            safe_name = _sanitize_display_text(expert.name)
            safe_speciality = _sanitize_display_text(expert.speciality)

            if is_selected:
                lines.append(("fg:ansigreen", "> "))
                lines.append(("fg:ansigreen bold", safe_name))
            else:
                lines.append(("", "  "))
                lines.append(("", safe_name))

            # Show model indicator if set
            if expert.model:
                safe_model = _sanitize_display_text(expert.model)
                lines.append(("fg:ansiyellow", f" -> {safe_model}"))

            lines.append(("", "\n"))

            # Second line: speciality (dimmed)
            if is_selected:
                lines.append(("fg:ansibrightgreen", "    "))
            else:
                lines.append(("fg:ansibrightblack", "    "))
            lines.append(("fg:ansibrightblack", safe_speciality))
            lines.append(("", "\n"))

    # Navigation hints
    lines.append(("", "\n"))
    lines.append(("fg:ansibrightblack", "  Up/Dn "))
    lines.append(("", "Navigate\n"))
    lines.append(("fg:ansibrightblack", "  Lt/Rt "))
    lines.append(("", "Page\n"))
    lines.append(("fg:green", "  Enter  "))
    lines.append(("", "Edit expert\n"))
    lines.append(("fg:ansibrightblack", "  A "))
    lines.append(("", "Add expert\n"))
    lines.append(("fg:ansibrightblack", "  D "))
    lines.append(("", "Delete expert\n"))
    lines.append(("fg:ansibrightblack", "  C "))
    lines.append(("", "Settings\n"))
    lines.append(("fg:ansibrightred", "  Ctrl+C "))
    lines.append(("", "Exit"))

    return lines


def _render_profile_menu_panel(
    profiles: list[ProfileDescriptor],
    page: int,
    selected_idx: int,
) -> list:
    """Render the left menu panel for profile selection.

    Args:
        profiles: list of ProfileDescriptor
        page: Current page number (0-indexed)
        selected_idx: Currently selected index (global)

    Returns:
        list of (style, text) tuples for FormattedTextControl
    """
    lines: list[tuple[str, str]] = []
    total_pages = get_total_pages(len(profiles), PAGE_SIZE)
    start_idx, end_idx = get_page_bounds(page, len(profiles), PAGE_SIZE)

    lines.append(("bold", "Profiles"))
    lines.append(("fg:ansibrightblack", f" (Page {page + 1}/{total_pages})"))
    lines.append(("", "\n\n"))

    if not profiles:
        lines.append(("fg:yellow", "  No profiles configured."))
        lines.append(("", "\n\n"))
    else:
        for i in range(start_idx, end_idx):
            profile = profiles[i]
            is_selected = i == selected_idx

            safe_name = _sanitize_display_text(profile.name)

            if is_selected:
                lines.append(("fg:ansigreen", "> "))
                lines.append(("fg:ansigreen bold", safe_name))
            else:
                lines.append(("", "  "))
                lines.append(("", safe_name))

            # Expert count badge
            count = len(profile.expert_names)
            lines.append(("fg:ansiyellow", f" ({count} experts)"))
            lines.append(("", "\n"))

            # Description line (dimmed)
            safe_desc = (
                _sanitize_display_text(profile.description)
                if profile.description
                else "(no description)"
            )
            if is_selected:
                lines.append(("fg:ansibrightgreen", "    "))
            else:
                lines.append(("fg:ansibrightblack", "    "))
            lines.append(("fg:ansibrightblack", safe_desc))
            lines.append(("", "\n"))

    # Navigation hints
    lines.append(("", "\n"))
    lines.append(("fg:ansibrightblack", "  Up/Dn "))
    lines.append(("", "Navigate\n"))
    lines.append(("fg:ansibrightblack", "  Lt/Rt "))
    lines.append(("", "Page\n"))
    lines.append(("fg:green", "  Enter  "))
    lines.append(("", "Open experts\n"))
    lines.append(("fg:green", "  A     "))
    lines.append(("", "Activate & exit\n"))
    lines.append(("fg:ansibrightblack", "  N "))
    lines.append(("", "Add profile\n"))
    lines.append(("fg:ansibrightblack", "  D "))
    lines.append(("", "Delete profile\n"))
    lines.append(("fg:ansibrightblack", "  E "))
    lines.append(("", "Edit profile\n"))
    lines.append(("fg:ansibrightred", "  Ctrl+C "))
    lines.append(("", "Exit"))

    return lines


# ---------------------------------------------------------------------------
# Preview panel rendering
# ---------------------------------------------------------------------------


def _render_profile_preview_panel(profile: ProfileDescriptor | None) -> list:
    """Render the right preview panel showing experts in the selected profile.

    Args:
        profile: ProfileDescriptor or None

    Returns:
        list of (style, text) tuples for FormattedTextControl
    """
    lines: list[tuple[str, str]] = []

    lines.append(("dim cyan", " PROFILE PREVIEW"))
    lines.append(("", "\n\n"))

    if not profile:
        lines.append(("fg:yellow", "  No profile selected."))
        lines.append(("", "\n"))
        return lines

    safe_name = _sanitize_display_text(profile.name)
    safe_desc = (
        _sanitize_display_text(profile.description)
        if profile.description
        else "(no description)"
    )

    # Profile name
    lines.append(("bold", "Profile: "))
    lines.append(("fg:ansigreen", safe_name))
    lines.append(("", "\n\n"))

    # Description
    lines.append(("bold", "Description: "))
    lines.append(("fg:ansicyan", safe_desc))
    lines.append(("", "\n\n"))

    # Experts
    lines.append(("bold", f"Experts ({len(profile.expert_names)}):"))
    lines.append(("", "\n"))

    if not profile.expert_names:
        lines.append(("fg:ansibrightblack", "  (no experts — add some via Edit)"))
        lines.append(("", "\n"))
    else:
        experts = orchestrator.get_experts_for_profile(profile.name)
        for expert in experts:
            safe_en = _sanitize_display_text(expert.name)
            safe_es = _sanitize_display_text(expert.speciality)
            lines.append(("fg:ansiyellow", f"  • {safe_en}"))
            lines.append(("fg:ansibrightblack", f" — {safe_es}"))
            lines.append(("", "\n"))

    return lines


def _render_preview_panel(expert: ExpertDescriptor | None) -> list:
    """Render the right preview panel with expert details.

    Args:
        expert: ExpertDescriptor or None

    Returns:
        list of (style, text) tuples for FormattedTextControl
    """
    lines: list[tuple[str, str]] = []

    lines.append(("dim cyan", " EXPERT DETAILS"))
    lines.append(("", "\n\n"))

    if not expert:
        lines.append(("fg:yellow", "  No expert selected."))
        lines.append(("", "\n"))
        return lines

    safe_name = _sanitize_display_text(expert.name)
    safe_speciality = _sanitize_display_text(expert.speciality)

    # Name
    lines.append(("bold", "Name: "))
    lines.append(("", safe_name))
    lines.append(("", "\n\n"))

    # Speciality
    lines.append(("bold", "Speciality: "))
    lines.append(("fg:ansicyan", safe_speciality))
    lines.append(("", "\n\n"))

    # Model
    lines.append(("bold", "Model: "))
    if expert.model:
        safe_model = _sanitize_display_text(expert.model)
        lines.append(("fg:ansiyellow", safe_model))
    else:
        lines.append(("fg:ansibrightblack", "default"))
    lines.append(("", "\n\n"))

    # Max experts override
    lines.append(("bold", "Max Experts Override: "))
    if expert.max_experts_override is not None:
        lines.append(("", str(expert.max_experts_override)))
    else:
        lines.append(("fg:ansibrightblack", "none"))
    lines.append(("", "\n\n"))

    # System prompt fragment
    lines.append(("bold", "System Prompt Fragment:"))
    lines.append(("", "\n"))

    safe_fragment = _sanitize_display_text(expert.system_prompt_fragment)
    # Word-wrap the fragment
    words = safe_fragment.split()
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 > 55:
            lines.append(("fg:ansibrightblack", current_line))
            lines.append(("", "\n"))
            current_line = word
        else:
            if current_line == "":
                current_line = word
            else:
                current_line += " " + word
    if current_line.strip():
        lines.append(("fg:ansibrightblack", current_line))
        lines.append(("", "\n"))

    lines.append(("", "\n"))
    return lines


# ---------------------------------------------------------------------------
# Expert add / edit prompts
# ---------------------------------------------------------------------------


async def _prompt_text(label: str, default: str = "") -> str | None:
    """Prompt the user for a text input using prompt_toolkit.

    Returns None if the user cancels (Ctrl+C / Ctrl+D).
    """
    from prompt_toolkit import PromptSession

    session: PromptSession = PromptSession()
    try:
        result = await session.prompt_async(f"{label}: ", default=default)
        return result.strip() if result else None
    except (KeyboardInterrupt, EOFError):
        return None


async def _prompt_model(current_model: str | None = None) -> str | None:
    """Prompt the user to select a model, or clear the model override.

    Returns the model name, "(clear)" to remove the override, or None on cancel.
    """
    try:
        model_names = load_model_names() or []
    except Exception as exc:
        emit_warning(f"Failed to load models: {exc}")
        return None

    choices = ["(clear model override)"] + model_names

    try:
        choice = await arrow_select_async("Select model (or clear override)", choices)
    except KeyboardInterrupt:
        emit_info("Model selection cancelled")
        return None

    if choice == "(clear model override)":
        return "(clear)"
    return choice


# ---------------------------------------------------------------------------
# Final prompt extraction
# ---------------------------------------------------------------------------

_FINAL_PROMPT_RE = re.compile(r"\[FINAL_PROMPT\](.*?)\[/FINAL_PROMPT\]", re.DOTALL)


def _try_extract_final_prompt(text: str) -> str | None:
    """Extract the content between [FINAL_PROMPT]...[/FINAL_PROMPT] tags.

    Returns the stripped content if found, otherwise None.
    """
    match = _FINAL_PROMPT_RE.search(text)
    if match:
        return match.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Interactive agent chat loop
# ---------------------------------------------------------------------------

_MAX_CHAT_TURNS = 20  # Safety cap to prevent infinite loops


async def _interactive_agent_chat(
    agent_name: str,
    initial_prompt: str,
) -> str:
    """Run an interactive multi-turn chat with a named agent.

    Uses the standard ``_runtime.run`` path so streaming, tool calls,
    and cancellation all work identically to the main CLI.

    Args:
        agent_name: The agent to load (e.g. "agent-creator").
        initial_prompt: The first user message to send.

    Returns:
        The extracted final prompt text, or empty string on cancel/failure.
    """
    from prompt_toolkit import PromptSession

    from code_muse.agents._runtime import run as agent_run
    from code_muse.agents.agent_manager import load_agent

    # Load the agent through the standard path
    try:
        agent = load_agent(agent_name)
    except ValueError as exc:
        emit_warning(f"Could not load agent '{agent_name}': {exc}")
        return ""

    session: PromptSession = PromptSession()
    last_response_text = ""

    # --- Turn 0: the initial prompt ---
    emit_info(f"🤖 Chatting with {agent.display_name} (type 'done' to finish)\n")

    try:
        result = await agent_run(agent, initial_prompt)
    except KeyboardInterrupt, asyncio.CancelledError:
        emit_info("Chat cancelled.")
        return ""
    except Exception as exc:
        emit_warning(f"Agent error: {exc}")
        return ""

    if result is not None:
        last_response_text = getattr(result, "output", None) or str(result)
        extracted = _try_extract_final_prompt(last_response_text)
        if extracted is not None:
            return extracted

    # --- Subsequent turns ---
    for _ in range(_MAX_CHAT_TURNS - 1):
        try:
            user_input = await session.prompt_async("agent-creator > ")
        except (KeyboardInterrupt, EOFError):
            emit_info("Chat ended.")
            return ""

        if user_input is None or user_input.strip().lower() in ("exit", "quit", "done"):
            # Return whatever we last extracted, or empty
            extracted = _try_extract_final_prompt(last_response_text)
            return extracted if extracted is not None else last_response_text.strip()

        if not user_input.strip():
            continue

        try:
            result = await agent_run(agent, user_input.strip())
        except KeyboardInterrupt, asyncio.CancelledError:
            emit_info("Chat cancelled.")
            return ""
        except Exception as exc:
            emit_warning(f"Agent error: {exc}")
            continue

        if result is not None:
            last_response_text = getattr(result, "output", None) or str(result)
            extracted = _try_extract_final_prompt(last_response_text)
            if extracted is not None:
                return extracted

    emit_warning("Reached maximum chat turns; exiting.")
    extracted = _try_extract_final_prompt(last_response_text)
    return extracted if extracted is not None else last_response_text.strip()


async def _generate_system_prompt_with_agent_creator(name: str, speciality: str) -> str:
    """Interactively generate a system prompt for a MindPack expert.

    Starts a multi-turn chat with Agent Creator so the user can
    iterate on the system prompt.  When the agent wraps its final
    output in ``[FINAL_PROMPT]...[/FINAL_PROMPT]`` tags the chat
    exits automatically and the enclosed text is returned.

    Args:
        name: The expert's name (e.g., "SecurityReviewer")
        speciality: The expert's speciality (e.g., "security analysis")

    Returns:
        The generated system prompt text, or empty string on failure/cancel.
    """
    initial_prompt = (
        f"Create a system prompt for a MindPack expert named '{name}' "
        f"that specializes in: {speciality}.\n\n"
        f"This expert will be part of a multi-expert advisory panel in Muse. "
        f"The system prompt should define the expert's role, perspective, "
        f"and how they should analyze problems and provide recommendations.\n\n"
        f"Ask me any clarifying questions about the expert's behavior, "
        f"tone, constraints, or specific focus areas. Iterate with me until "
        f"we're both satisfied. When we agree on the final version, output "
        f"the complete system prompt wrapped in [FINAL_PROMPT]...[/FINAL_PROMPT] "
        f'tags. The system prompt should be in second person ("You are...") '
        f"and should be comprehensive but concise."
    )

    # Exit alternate-screen so the chat renders in the normal terminal
    sys.stdout.write("\033[?1049l")
    sys.stdout.flush()
    await asyncio.sleep(0.05)

    try:
        result_text = await _interactive_agent_chat("agent-creator", initial_prompt)
    finally:
        # Re-enter alternate-screen for the MindPack menu
        sys.stdout.write("\033[?1049h")
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
        await asyncio.sleep(0.05)

    if result_text:
        emit_success(f"System prompt generated for '{name}'")
        return result_text

    emit_info("Agent Creator chat ended without a final prompt.")
    return ""


async def _add_expert_flow() -> ExpertDescriptor | None:
    """Interactive flow to add a new expert.

    Offers preset templates or custom creation.
    Returns a new ExpertDescriptor, or None if cancelled.
    """
    # Ask: preset or custom?
    try:
        choice = await arrow_select_async(
            "Add expert: choose template or custom",
            ["Custom expert (manual input)", "Use preset template"],
        )
    except KeyboardInterrupt:
        emit_info("Add expert cancelled.")
        return None

    if choice == "Use preset template":
        # Show preset selector
        preset_choices = [
            f"{e.name} — {e.speciality} (model: {e.model or 'default'})"
            for e in PRESET_EXPERTS
        ]
        try:
            preset_choice = await arrow_select_async(
                "Select preset expert", preset_choices
            )
        except KeyboardInterrupt:
            emit_info("Add expert cancelled.")
            return None

        # Find selected preset
        idx = preset_choices.index(preset_choice)
        preset = PRESET_EXPERTS[idx]

        # Check for duplicate names
        existing_names = [e.name for e in orchestrator.expert_registry]
        if preset.name in existing_names:
            emit_warning(f"Expert '{preset.name}' already exists. Edit it instead.")
            return None

        emit_success(f"Added preset expert: {preset.name}")
        return preset

    # Custom expert creation
    name = await _prompt_text("Expert name")
    if name is None or not name:
        emit_info("Add expert cancelled.")
        return None

    existing_names = [e.name for e in orchestrator.expert_registry]
    if name in existing_names:
        emit_warning(f"Expert '{name}' already exists. Edit it instead.")
        return None

    speciality = await _prompt_text("Speciality")
    if speciality is None or not speciality:
        emit_info("Add expert cancelled.")
        return None

    model_choice = await _prompt_model()
    model = None
    if model_choice and model_choice != "(clear)":
        model = model_choice

    # System prompt: manual entry or Agent Creator
    try:
        prompt_choice = await arrow_select_async(
            "System prompt fragment",
            [
                "Enter manually",
                "Generate with Agent Creator 🏗️",
                "Skip (leave empty)",
            ],
        )
    except KeyboardInterrupt:
        emit_info("Add expert cancelled.")
        return None

    if prompt_choice == "Generate with Agent Creator 🏗️":
        system_prompt_fragment = await _generate_system_prompt_with_agent_creator(
            name=name, speciality=speciality
        )
    elif prompt_choice == "Enter manually":
        system_prompt_fragment = await _prompt_text("System prompt fragment") or ""
    else:
        system_prompt_fragment = ""

    return ExpertDescriptor(
        name=name,
        speciality=speciality,
        system_prompt_fragment=system_prompt_fragment,
        model=model,
    )


async def _edit_expert_flow(expert: ExpertDescriptor) -> ExpertDescriptor | None:
    """Interactive flow to edit an existing expert.

    Returns the updated ExpertDescriptor, or None if cancelled.
    """
    new_name = await _prompt_text("Name", default=expert.name)
    if new_name is None:
        emit_info("Edit cancelled.")
        return None

    # Check for duplicate names (if name changed)
    if new_name != expert.name:
        existing_names = [e.name for e in orchestrator.expert_registry]
        if new_name in existing_names:
            emit_warning(f"Expert name '{new_name}' already exists.")
            return None

    new_speciality = await _prompt_text("Speciality", default=expert.speciality)
    if new_speciality is None:
        emit_info("Edit cancelled.")
        return None

    model_choice = await _prompt_model(current_model=expert.model)
    model = expert.model
    if model_choice is not None:
        model = None if model_choice == "(clear)" else model_choice

    # System prompt: manual entry or Agent Creator
    try:
        prompt_choice = await arrow_select_async(
            "System prompt fragment",
            [
                "Keep existing",
                "Edit manually",
                "Generate with Agent Creator 🏗️",
            ],
        )
    except KeyboardInterrupt:
        emit_info("Edit cancelled.")
        return None

    if prompt_choice == "Generate with Agent Creator 🏗️":
        new_fragment = await _generate_system_prompt_with_agent_creator(
            name=new_name, speciality=new_speciality
        )
    elif prompt_choice == "Edit manually":
        new_fragment = await _prompt_text(
            "System prompt fragment", default=expert.system_prompt_fragment
        )
        if new_fragment is None:
            emit_info("Edit cancelled.")
            return None
    else:
        # Keep existing
        new_fragment = expert.system_prompt_fragment

    max_override_str = await _prompt_text(
        "Max experts override (empty = none)",
        default=str(expert.max_experts_override)
        if expert.max_experts_override is not None
        else "",
    )
    max_experts_override = expert.max_experts_override
    if max_override_str is not None:
        if max_override_str.strip() == "":
            max_experts_override = None
        else:
            try:
                max_experts_override = int(max_override_str)
            except ValueError:
                emit_warning(
                    "Invalid number for max_experts_override, keeping previous value."
                )

    return ExpertDescriptor(
        name=new_name,
        speciality=new_speciality,
        system_prompt_fragment=new_fragment,
        model=model,
        max_experts_override=max_experts_override,
    )


async def _add_profile_flow() -> ProfileDescriptor | None:
    """Interactive flow to add a new profile.

    Returns a new ProfileDescriptor, or None if cancelled.
    """
    name = await _prompt_text("Profile name")
    if name is None or not name:
        emit_info("Add profile cancelled.")
        return None

    existing_names = [p.name for p in orchestrator.profile_registry]
    if name in existing_names:
        emit_warning(f"Profile '{name}' already exists.")
        return None

    description = await _prompt_text("Description (optional)") or ""

    # Multi-select experts from the full registry
    all_experts = sorted(orchestrator.expert_registry, key=lambda e: e.name.lower())
    expert_choices = [f"{e.name} — {e.speciality}" for e in all_experts]

    if not expert_choices:
        emit_warning("No experts available. Add experts first.")
        return None

    selected_expert_names: list[str] = []
    try:
        # Use arrow_select_async for each expert (simple pick-one-at-a-time with Done)
        while True:
            remaining = [
                f"{e.name} — {e.speciality}"
                for e in all_experts
                if e.name not in selected_expert_names
            ]
            if not remaining:
                emit_info("All experts selected.")
                break

            choice = await arrow_select_async(
                f"Select experts for '{name}' ({len(selected_expert_names)} selected) — choose 'Done' to finish",
                ["✅ Done"] + remaining,
            )
            if choice == "✅ Done" or choice is None:
                break

            # Extract expert name from the choice string
            expert_name = choice.split(" — ")[0]
            if expert_name not in selected_expert_names:
                selected_expert_names.append(expert_name)
                emit_info(f"Added '{expert_name}' to profile.")
    except KeyboardInterrupt:
        if not selected_expert_names:
            emit_info("Add profile cancelled.")
            return None

    if not selected_expert_names:
        emit_warning("Profile must have at least one expert.")
        return None

    return ProfileDescriptor(
        name=name,
        description=description,
        expert_names=selected_expert_names,
    )


async def _edit_profile_flow(profile: ProfileDescriptor) -> ProfileDescriptor | None:
    """Interactive flow to edit an existing profile.

    Returns the updated ProfileDescriptor, or None if cancelled.
    """
    new_name = await _prompt_text("Name", default=profile.name)
    if new_name is None:
        emit_info("Edit cancelled.")
        return None

    if new_name != profile.name:
        existing_names = [
            p.name for p in orchestrator.profile_registry if p.name != profile.name
        ]
        if new_name in existing_names:
            emit_warning(f"Profile name '{new_name}' already exists.")
            return None

    new_description = (
        await _prompt_text("Description (optional)", default=profile.description) or ""
    )

    # Multi-select experts (current selection pre-populated)
    all_experts = sorted(orchestrator.expert_registry, key=lambda e: e.name.lower())
    selected_expert_names = list(profile.expert_names)

    try:
        while True:
            remaining = [
                f"{e.name} — {e.speciality}"
                for e in all_experts
                if e.name not in selected_expert_names
            ]
            # Build display showing current selection status
            status = (
                ", ".join(selected_expert_names) if selected_expert_names else "(none)"
            )
            options = ["✅ Done"]
            if selected_expert_names:
                options.append("🗑️ Remove an expert")
            options.extend(remaining)

            choice = await arrow_select_async(
                f"Experts for '{new_name}' — current: {status}",
                options,
            )
            if choice == "✅ Done" or choice is None:
                break
            elif choice == "🗑️ Remove an expert":
                # Pick which expert to remove
                remove_choices = selected_expert_names[:]
                to_remove = await arrow_select_async(
                    "Remove which expert?", remove_choices
                )
                if to_remove:
                    selected_expert_names.remove(to_remove)
                    emit_info(f"Removed '{to_remove}' from profile.")
            else:
                expert_name = choice.split(" — ")[0]
                if expert_name not in selected_expert_names:
                    selected_expert_names.append(expert_name)
                    emit_info(f"Added '{expert_name}' to profile.")
    except KeyboardInterrupt:
        emit_info("Edit cancelled (changes discarded).")
        return None

    return ProfileDescriptor(
        name=new_name,
        description=new_description,
        expert_names=selected_expert_names,
    )


# ---------------------------------------------------------------------------
# Settings configuration
# ---------------------------------------------------------------------------


async def _configure_settings() -> None:
    """Show settings configuration for MindPack."""
    choices = [
        f"Spawn mode: {_DEFAULT_SETTINGS['spawn_mode']}",
        f"Default expert count: {_DEFAULT_SETTINGS['default_expert_count']}",
        "Done",
    ]

    try:
        choice = await arrow_select_async("MindPack Settings", choices)
    except KeyboardInterrupt:
        return

    if choice.startswith("Spawn mode"):
        mode_options = [
            "fixed",
            "adaptive",
            "same_agent_replicas",
            "multi_model_replicas",
            "multi_agent",
            "hybrid",
        ]
        try:
            mode = await arrow_select_async("Select spawn mode", mode_options)
            _DEFAULT_SETTINGS["spawn_mode"] = mode
            emit_success(f"Spawn mode set to '{mode}'")
        except KeyboardInterrupt:
            pass
    elif choice.startswith("Default expert count"):
        count_str = await _prompt_text(
            "Default expert count",
            default=_DEFAULT_SETTINGS["default_expert_count"],
        )
        if count_str is not None:
            try:
                int(count_str)
                _DEFAULT_SETTINGS["default_expert_count"] = count_str
                emit_success(f"Default expert count set to {count_str}")
            except ValueError:
                emit_warning("Invalid number.")
    # "Done" — just return


# ---------------------------------------------------------------------------
# Main interactive menu
# ---------------------------------------------------------------------------


async def interactive_profile_selector_menu() -> str | None | bool:
    """Show profile selector as the first screen when entering /mindpack.

    Returns:
        The name of the selected profile to open, or None to exit.
        - True if a profile was activated and the caller should exit.

    Supports browsing, selecting, adding, editing, and deleting profiles.
    """
    profiles = _get_profile_entries()

    # State
    selected_idx = [0]
    current_page = [0]
    pending_action = [None]  # 'open', 'add', 'edit', 'delete', or None

    total_pages = [get_total_pages(len(profiles), PAGE_SIZE)]

    def get_current_profile() -> ProfileDescriptor | None:
        if 0 <= selected_idx[0] < len(profiles):
            return profiles[selected_idx[0]]
        return None

    def refresh_profiles(selected_name: str | None = None) -> None:
        nonlocal profiles
        profiles = _get_profile_entries()
        total_pages[0] = get_total_pages(len(profiles), PAGE_SIZE)

        if not profiles:
            selected_idx[0] = 0
            current_page[0] = 0
            return

        if selected_name:
            for idx, p in enumerate(profiles):
                if p.name == selected_name:
                    selected_idx[0] = idx
                    break
            else:
                selected_idx[0] = min(selected_idx[0], len(profiles) - 1)
        else:
            selected_idx[0] = min(selected_idx[0], len(profiles) - 1)

        current_page[0] = get_page_for_index(selected_idx[0], PAGE_SIZE)

    # Build UI
    menu_control = FormattedTextControl(text="")
    preview_control = FormattedTextControl(text="")

    def update_display():
        menu_control.text = _render_profile_menu_panel(
            profiles, current_page[0], selected_idx[0]
        )
        preview_control.text = _render_profile_preview_panel(get_current_profile())

    menu_window = Window(
        content=menu_control, wrap_lines=False, width=Dimension(weight=35)
    )
    preview_window = Window(
        content=preview_control, wrap_lines=False, width=Dimension(weight=65)
    )

    menu_frame = Frame(
        menu_window, width=Dimension(weight=35), title="MindPack Profiles"
    )
    preview_frame = Frame(preview_window, width=Dimension(weight=65), title="Preview")

    root_container = VSplit([menu_frame, preview_frame])

    # Key bindings
    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        if selected_idx[0] > 0:
            selected_idx[0] -= 1
            current_page[0] = ensure_visible_page(
                selected_idx[0], current_page[0], len(profiles), PAGE_SIZE
            )
            update_display()

    @kb.add("down")
    def _(event):
        if selected_idx[0] < len(profiles) - 1:
            selected_idx[0] += 1
            current_page[0] = ensure_visible_page(
                selected_idx[0], current_page[0], len(profiles), PAGE_SIZE
            )
            update_display()

    @kb.add("left")
    def _(event):
        if current_page[0] > 0:
            current_page[0] -= 1
            selected_idx[0] = current_page[0] * PAGE_SIZE
            update_display()

    @kb.add("right")
    def _(event):
        if current_page[0] < total_pages[0] - 1:
            current_page[0] += 1
            selected_idx[0] = current_page[0] * PAGE_SIZE
            update_display()

    @kb.add("a")
    def _(event):
        if get_current_profile():
            pending_action[0] = "activate"
            event.app.exit()

    @kb.add("n")
    def _(event):
        pending_action[0] = "add"
        event.app.exit()

    @kb.add("d")
    def _(event):
        if get_current_profile():
            pending_action[0] = "delete"
            event.app.exit()

    @kb.add("e")
    def _(event):
        if get_current_profile():
            pending_action[0] = "edit"
            event.app.exit()

    @kb.add("enter")
    def _(event):
        if get_current_profile():
            pending_action[0] = "open"
            event.app.exit()

    @kb.add("c-c")
    def _(event):
        pending_action[0] = None
        event.app.exit()

    layout = Layout(root_container)
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        mouse_support=False,
    )

    set_awaiting_user_input(True)

    # Enter alternate screen buffer
    sys.stdout.write("\033[?1049h")
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    await asyncio.sleep(0.05)

    try:
        while True:
            pending_action[0] = None
            update_display()

            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

            await app.run_async()

            if pending_action[0] == "activate":
                profile = get_current_profile()
                if profile:
                    orchestrator.set_active_profile(profile.name)
                    emit_success(f"Profile '{profile.name}' activated. Exiting.")
                    return True
                continue

            if pending_action[0] == "open":
                profile = get_current_profile()
                if profile:
                    orchestrator.set_active_profile(profile.name)
                    emit_success(f"Active profile set to '{profile.name}'")
                    return profile.name
                continue

            if pending_action[0] == "add":
                new_profile = await _add_profile_flow()
                if new_profile is not None:
                    orchestrator.register_profile(new_profile)
                    orchestrator.save_profiles()
                    emit_success(f"Profile '{new_profile.name}' added.")
                refresh_profiles(
                    selected_name=new_profile.name if new_profile else None
                )
                continue

            if pending_action[0] == "edit":
                profile = get_current_profile()
                if profile:
                    updated = await _edit_profile_flow(profile)
                    if updated is not None:
                        orchestrator.remove_profile(profile.name)
                        orchestrator.register_profile(updated)
                        orchestrator.save_profiles()
                        emit_success(f"Profile '{updated.name}' updated.")
                    refresh_profiles(
                        selected_name=updated.name if updated else profile.name
                    )
                continue

            if pending_action[0] == "delete":
                profile = get_current_profile()
                if profile:
                    try:
                        confirm = await arrow_select_async(
                            f"Delete profile '{profile.name}'?",
                            ["No, cancel", "Yes, delete"],
                        )
                    except KeyboardInterrupt:
                        confirm = "No, cancel"

                    if confirm == "Yes, delete":
                        orchestrator.remove_profile(profile.name)
                        orchestrator.save_profiles()
                        emit_success(f"Profile '{profile.name}' deleted.")
                    else:
                        emit_info("Delete cancelled.")
                refresh_profiles()
                continue

            # Ctrl+C — exit
            return None

    finally:
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()
        set_awaiting_user_input(False)


async def interactive_mindpack_menu(profile_name: str | None = None) -> None:
    """Show interactive terminal UI for managing MindPack experts.

    Supports browsing, adding, editing, and deleting experts with
    a split-panel layout and live preview.

    Args:
        profile_name: If set, filters experts to only those in this profile.
    """
    if profile_name:
        entries = _get_expert_entries_for_profile(profile_name)
    else:
        entries = _get_expert_entries()

    # State
    selected_idx = [0]
    current_page = [0]
    pending_action = [None]  # 'add', 'edit', 'delete', 'settings', or None

    total_pages = [get_total_pages(len(entries), PAGE_SIZE)]

    def get_current_expert() -> ExpertDescriptor | None:
        if 0 <= selected_idx[0] < len(entries):
            return entries[selected_idx[0]]
        return None

    def refresh_entries(selected_name: str | None = None) -> None:
        nonlocal entries
        if profile_name:
            entries = _get_expert_entries_for_profile(profile_name)
        else:
            entries = _get_expert_entries()
        total_pages[0] = get_total_pages(len(entries), PAGE_SIZE)

        if not entries:
            selected_idx[0] = 0
            current_page[0] = 0
            return

        if selected_name:
            for idx, expert in enumerate(entries):
                if expert.name == selected_name:
                    selected_idx[0] = idx
                    break
            else:
                selected_idx[0] = min(selected_idx[0], len(entries) - 1)
        else:
            selected_idx[0] = min(selected_idx[0], len(entries) - 1)

        current_page[0] = get_page_for_index(selected_idx[0], PAGE_SIZE)

    # Build UI
    menu_control = FormattedTextControl(text="")
    preview_control = FormattedTextControl(text="")

    def update_display():
        """Update both panels."""
        menu_control.text = _render_menu_panel(
            entries, current_page[0], selected_idx[0]
        )
        preview_control.text = _render_preview_panel(get_current_expert())

    menu_window = Window(
        content=menu_control, wrap_lines=False, width=Dimension(weight=35)
    )
    preview_window = Window(
        content=preview_control, wrap_lines=False, width=Dimension(weight=65)
    )

    title = f"MindPack Experts — {profile_name}" if profile_name else "MindPack Experts"
    menu_frame = Frame(menu_window, width=Dimension(weight=35), title=title)
    preview_frame = Frame(preview_window, width=Dimension(weight=65), title="Preview")

    root_container = VSplit(
        [
            menu_frame,
            preview_frame,
        ]
    )

    # Key bindings
    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        if selected_idx[0] > 0:
            selected_idx[0] -= 1
            current_page[0] = ensure_visible_page(
                selected_idx[0],
                current_page[0],
                len(entries),
                PAGE_SIZE,
            )
            update_display()

    @kb.add("down")
    def _(event):
        if selected_idx[0] < len(entries) - 1:
            selected_idx[0] += 1
            current_page[0] = ensure_visible_page(
                selected_idx[0],
                current_page[0],
                len(entries),
                PAGE_SIZE,
            )
            update_display()

    @kb.add("left")
    def _(event):
        if current_page[0] > 0:
            current_page[0] -= 1
            selected_idx[0] = current_page[0] * PAGE_SIZE
            update_display()

    @kb.add("right")
    def _(event):
        if current_page[0] < total_pages[0] - 1:
            current_page[0] += 1
            selected_idx[0] = current_page[0] * PAGE_SIZE
            update_display()

    @kb.add("a")
    def _(event):
        pending_action[0] = "add"
        event.app.exit()

    @kb.add("d")
    def _(event):
        if get_current_expert():
            pending_action[0] = "delete"
            event.app.exit()

    @kb.add("c")
    def _(event):
        pending_action[0] = "settings"
        event.app.exit()

    @kb.add("enter")
    def _(event):
        if get_current_expert():
            pending_action[0] = "edit"
            event.app.exit()

    @kb.add("c-c")
    def _(event):
        pending_action[0] = None
        event.app.exit()

    layout = Layout(root_container)
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        mouse_support=False,
    )

    set_awaiting_user_input(True)

    # Enter alternate screen buffer once for entire session
    sys.stdout.write("\033[?1049h")
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    await asyncio.sleep(0.05)

    try:
        while True:
            pending_action[0] = None
            update_display()

            # Clear the current buffer
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

            # Run application
            await app.run_async()

            if pending_action[0] == "add":
                new_expert = await _add_expert_flow()
                if new_expert is not None:
                    orchestrator.register_expert(new_expert)
                    orchestrator.save_experts()
                    # If inside a profile, auto-add to the current profile
                    if profile_name:
                        for p in orchestrator.profile_registry:
                            if p.name == profile_name:
                                if new_expert.name not in p.expert_names:
                                    p.expert_names.append(new_expert.name)
                                    orchestrator.save_profiles()
                                    emit_info(
                                        f"Expert '{new_expert.name}' added to profile '{profile_name}'."
                                    )
                                break
                    emit_success(f"Expert '{new_expert.name}' added.")
                refresh_entries(selected_name=new_expert.name if new_expert else None)
                continue

            if pending_action[0] == "edit":
                expert = get_current_expert()
                if expert:
                    updated = await _edit_expert_flow(expert)
                    if updated is not None:
                        # Remove old and register new (name may have changed)
                        orchestrator.remove_expert(expert.name)
                        orchestrator.register_expert(updated)
                        orchestrator.save_experts()
                        emit_success(f"Expert '{updated.name}' updated.")
                    refresh_entries(
                        selected_name=updated.name if updated else expert.name
                    )
                continue

            if pending_action[0] == "delete":
                expert = get_current_expert()
                if expert:
                    try:
                        confirm = await arrow_select_async(
                            f"Delete expert '{expert.name}'?",
                            ["No, cancel", "Yes, delete"],
                        )
                    except KeyboardInterrupt:
                        confirm = "No, cancel"

                    if confirm == "Yes, delete":
                        removed = orchestrator.remove_expert(expert.name)
                        if removed:
                            # If inside a profile, remove from profile too
                            if profile_name:
                                for p in orchestrator.profile_registry:
                                    if p.name == profile_name:
                                        if expert.name in p.expert_names:
                                            p.expert_names.remove(expert.name)
                                            orchestrator.save_profiles()
                                        break
                            orchestrator.save_experts()
                            emit_success(f"Expert '{expert.name}' deleted.")
                        else:
                            emit_warning(
                                f"Expert '{expert.name}' not found in registry."
                            )
                    else:
                        emit_info("Delete cancelled.")
                refresh_entries()
                continue

            if pending_action[0] == "settings":
                await _configure_settings()
                continue

            # No pending action (Ctrl+C) — exit loop
            break

    finally:
        # Exit alternate screen buffer once at end
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()
        # Reset awaiting input flag
        set_awaiting_user_input(False)

    # Clear exit message
    emit_info("Exited MindPack expert configuration.")
