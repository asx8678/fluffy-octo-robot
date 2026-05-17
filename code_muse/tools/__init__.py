try:
    from annotationlib import get_annotations
except ImportError:
    # Python <3.14 fallback
    from inspect import get_annotations

from code_muse.callbacks import on_register_tools
from code_muse.messaging import emit_warning
from code_muse.plugins.tool_registry.registry import ToolMetadata, ToolRegistry
from code_muse.tools.agent_tools import register_invoke_agent, register_list_agents
from code_muse.tools.ask_user_question import register_ask_user_question

# Chrome CDP tools
from code_muse.tools.chrome_cdp import register_chrome_cdp
from code_muse.tools.command_runner import (
    register_agent_run_shell_command,
    register_agent_share_your_reasoning,
)
from code_muse.tools.display import (
    display_non_streamed_result as display_non_streamed_result,
)
from code_muse.tools.file_modifications import (
    register_create_file,
    register_delete_file,
    register_delete_snippet,
    register_edit_file,
    register_replace_in_file,
)
from code_muse.tools.file_operations import (
    register_grep,
    register_list_files,
    register_read_file,
)
from code_muse.tools.image_tools import register_load_image
from code_muse.tools.mitmproxy import register_mitmproxy
from code_muse.tools.skills_tools import (
    register_activate_skill,
    register_list_or_search_skills,
)
from code_muse.tools.universal_constructor import register_universal_constructor

# Map of tool names to their individual registration functions
TOOL_REGISTRY = {
    # Agent Tools
    "list_agents": register_list_agents,
    "invoke_agent": register_invoke_agent,
    # File Operations
    "list_files": register_list_files,
    "read_file": register_read_file,
    "grep": register_grep,
    # File Modifications
    # DEPRECATED: auto-expanded to create_file, replace_in_file, delete_snippet
    "edit_file": register_edit_file,
    "create_file": register_create_file,
    "replace_in_file": register_replace_in_file,
    "delete_snippet": register_delete_snippet,
    "delete_file": register_delete_file,
    # Command Runner
    "agent_run_shell_command": register_agent_run_shell_command,
    "agent_share_your_reasoning": register_agent_share_your_reasoning,
    # User Interaction
    "ask_user_question": register_ask_user_question,
    # Image loading (used by QA agents and friends)
    "load_image_for_analysis": register_load_image,
    # mitmproxy
    "mitmproxy": register_mitmproxy,
    # Chrome CDP
    "chrome_cdp": register_chrome_cdp,
    # Skills Tools
    "activate_skill": register_activate_skill,
    "list_or_search_skills": register_list_or_search_skills,
    # Universal Constructor
    "universal_constructor": register_universal_constructor,
}

# Tools that expand into multiple tools for backward compatibility.
# When an agent requests a tool listed here, all the expansion tools
# are registered instead (the original tool is NOT registered).
TOOL_EXPANSIONS: dict[str, list[str]] = {
    "edit_file": ["create_file", "replace_in_file", "delete_snippet"],
}

# Legacy tool names we silently ignore instead of warning about.
# Keep this for truly removed tools only; backward-compatible tool aliases
# that still work should stay in TOOL_REGISTRY.
REMOVED_LEGACY_TOOLS: set[str] = set()


def _load_plugin_tools() -> None:
    """Load tools registered by plugins via the register_tools callback.

    This merges plugin-provided tools into the TOOL_REGISTRY.
    Called lazily when tools are first accessed.
    """
    try:
        results = on_register_tools()
        for result in results:
            if result is None:
                continue
            # Each result should be a list of tool definitions
            tools_list = result if isinstance(result, list) else [result]
            for tool_def in tools_list:
                if (
                    isinstance(tool_def, dict)
                    and "name" in tool_def
                    and "register_func" in tool_def
                ):
                    tool_name = tool_def["name"]
                    register_func = tool_def["register_func"]
                    if callable(register_func):
                        TOOL_REGISTRY[tool_name] = register_func
    except Exception:
        # Don't let plugin failures break core functionality
        pass


# Appended to the system prompt when extended thinking is active and
# the share_your_reasoning tool is removed.  Encourages the model to
# use its native thinking blocks between tool calls instead.
EXTENDED_THINKING_PROMPT_NOTE = (
    "\n\nIMPORTANT: You have extended thinking enabled. "
    "Always think between tool calls or waves of tool calls "
    "(if running parallel tools). Use your thinking blocks to reason "
    "about the results before deciding on next steps."
)


def has_extended_thinking_active(model_name: str | None = None) -> bool:
    """Check if an Anthropic model has extended thinking enabled or adaptive.

    When extended thinking is active, the model already exposes its reasoning
    via thinking blocks, making the share_your_reasoning tool redundant.

    Args:
        model_name: The model name to check. If None, uses the current global model.

    Returns:
        True if the model is an Anthropic model with extended_thinking set to
        "enabled" or "adaptive".
    """
    from code_muse.config import get_effective_model_settings, get_global_model_name

    if model_name is None:
        model_name = get_global_model_name()

    if model_name is None:
        return False

    # Only applies to Anthropic/Claude models
    if not (model_name.startswith("claude-") or model_name.startswith("anthropic-")):
        return False

    from code_muse.model_utils import get_default_extended_thinking

    settings = get_effective_model_settings(model_name)
    default_thinking = get_default_extended_thinking(model_name)
    extended_thinking = settings.get("extended_thinking", default_thinking)

    # Handle legacy boolean values
    if extended_thinking is True:
        extended_thinking = "enabled"
    elif extended_thinking is False:
        return False

    return extended_thinking in ("enabled", "adaptive")


def register_tools_for_agent(
    agent, tool_names: list[str], model_name: str | None = None
):
    """Register specific tools for an agent based on tool names.

    Args:
        agent: The agent to register tools to.
        tool_names: List of tool names to register. UC tools are prefixed with "uc:".
        model_name: Optional model name. Used to determine if certain tools
            (like agent_share_your_reasoning) should be skipped. If None,
            falls back to the current global model.
    """
    from code_muse.config import get_universal_constructor_enabled

    _load_plugin_tools()

    # Expand compound tools (e.g. "edit_file" → three individual tools)
    expanded_tools: list[str] = []
    seen: set[str] = set()
    for tool_name in tool_names:
        if tool_name in TOOL_EXPANSIONS:
            for expanded in TOOL_EXPANSIONS[tool_name]:
                if expanded not in seen:
                    expanded_tools.append(expanded)
                    seen.add(expanded)
        else:
            if tool_name not in seen:
                expanded_tools.append(tool_name)
                seen.add(tool_name)
    tool_names = expanded_tools

    for tool_name in tool_names:
        # Handle UC tools (prefixed with "uc:")
        if tool_name.startswith("uc:"):
            # Skip UC tools if UC is disabled
            if not get_universal_constructor_enabled():
                continue
            uc_tool_name = tool_name[3:]  # Remove "uc:" prefix
            _register_uc_tool_wrapper(agent, uc_tool_name)
            continue

        if tool_name in REMOVED_LEGACY_TOOLS:
            continue

        if tool_name not in TOOL_REGISTRY:
            # Skip unknown tools with a warning instead of failing
            emit_warning(f"Warning: Unknown tool '{tool_name}' requested, skipping...")
            continue

        # Check if Universal Constructor is disabled
        if (
            tool_name == "universal_constructor"
            and not get_universal_constructor_enabled()
        ):
            continue  # Skip UC if disabled in config

        # Register the individual tool
        register_func = TOOL_REGISTRY[tool_name]
        register_func(agent)


def _register_uc_tool_wrapper(agent, uc_tool_name: str):
    """Register a wrapper for a UC tool that calls it via the UC registry.

    This creates a dynamic tool that wraps the UC tool, preserving its
    parameter signature so pydantic-ai can generate proper JSON schema.

    Args:
        agent: The agent to register the tool wrapper to.
        uc_tool_name: The full name of the UC tool (e.g., "api.weather").
    """
    import inspect
    from typing import Any

    from pydantic_ai import RunContext

    # Get tool info and function from registry
    try:
        from code_muse.plugins.universal_constructor.registry import get_registry

        registry = get_registry()
        tool_info = registry.get_tool(uc_tool_name)
        if not tool_info:
            emit_warning(f"Warning: UC tool '{uc_tool_name}' not found, skipping...")
            return

        func = registry.get_tool_function(uc_tool_name)
        if not func:
            emit_warning(
                f"Warning: UC tool '{uc_tool_name}' function not found, skipping..."
            )
            return

        description = tool_info.meta.description
        docstring = tool_info.docstring or description
    except Exception as e:
        emit_warning(f"Warning: Failed to get UC tool '{uc_tool_name}' info: {e}")
        return

    # Get the original function's signature
    try:
        sig = inspect.signature(func)
        # Get annotations from the original function
        annotations = get_annotations(func).copy()
    except (ValueError, TypeError):
        sig = None
        annotations = {}

    # Create wrapper that preserves the signature
    def make_uc_wrapper(
        tool_name: str, original_func, original_sig, original_annotations
    ):
        # Build the wrapper function
        async def uc_tool_wrapper(context: RunContext, **kwargs: Any) -> Any:
            """Dynamically generated wrapper for a UC tool."""
            try:
                result = original_func(**kwargs)
                # Await async tool implementations
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as e:
                return {"error": f"UC tool '{tool_name}' failed: {e}"}

        # Copy signature info from original function
        uc_tool_wrapper.__name__ = tool_name.replace(".", "_")
        uc_tool_wrapper.__doc__ = (
            f"{docstring}\n\nThis is a Universal Constructor tool."
        )

        # Preserve annotations for pydantic-ai schema generation
        if original_annotations:
            # Add 'context' param and copy original params (excluding 'return')
            new_annotations = {"context": RunContext}
            for param_name, param_type in original_annotations.items():
                if param_name != "return":
                    new_annotations[param_name] = param_type
            if "return" in original_annotations:
                new_annotations["return"] = original_annotations["return"]
            else:
                new_annotations["return"] = Any
            uc_tool_wrapper.__annotations__ = new_annotations

        # Try to set __signature__ for better introspection
        if original_sig:
            try:
                # Build new parameters list: context first, then original params
                new_params = [
                    inspect.Parameter(
                        "context",
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=RunContext,
                    )
                ]
                for param in original_sig.parameters.values():
                    new_params.append(param)

                # Create new signature with return annotation
                return_annotation = original_annotations.get("return", Any)
                new_sig = original_sig.replace(
                    parameters=new_params, return_annotation=return_annotation
                )
                uc_tool_wrapper.__signature__ = new_sig
            except (ValueError, TypeError):
                pass  # Signature manipulation failed, continue without it

        return uc_tool_wrapper

    wrapper = make_uc_wrapper(uc_tool_name, func, sig, annotations)

    # Register the wrapper as a tool
    try:
        agent.tool(wrapper)
    except Exception as e:
        emit_warning(f"Warning: Failed to register UC tool '{uc_tool_name}': {e}")


def register_all_tools(agent, model_name: str | None = None):
    """Register all available tools to the provided agent.

    Args:
        agent: The agent to register tools to.
        model_name: Optional model name for conditional tool filtering.
    """
    all_tools = list(TOOL_REGISTRY.keys())
    register_tools_for_agent(agent, all_tools, model_name=model_name)


def get_available_tool_names() -> list[str]:
    """Get list of all available tool names.

    Returns:
        List of all tool names that can be registered.
    """
    _load_plugin_tools()
    return list(TOOL_REGISTRY.keys())


# Create a rich metadata registry alongside the simple TOOL_REGISTRY
TOOL_METADATA_REGISTRY: ToolRegistry = ToolRegistry()


def register_tool_metadata(
    name: str,
    *,
    destructive: bool = False,
    idempotent: bool = False,
    requires_confirmation: bool = False,
    timeout: int = 60,
    max_retries: int = 2,
    tier: str = "medium",
    category: str = "utility",
    description: str = "",
) -> None:
    """Register rich metadata for a tool."""
    metadata = ToolMetadata(
        name=name,
        tier=tier,  # type: ignore[arg-type]
        category=category,  # type: ignore[arg-type]
        destructive=destructive,
        idempotent=idempotent,
        requires_confirmation=requires_confirmation,
        description=description,
        timeout_seconds=timeout,
        max_retries=max_retries,
    )
    TOOL_METADATA_REGISTRY.register(metadata)


def get_tool_metadata(name: str) -> ToolMetadata | None:
    """Look up tool metadata by name."""
    return TOOL_METADATA_REGISTRY.get_metadata(name)


# Register metadata for key tools
# Destructive tools
register_tool_metadata(
    "create_file",
    destructive=True,
    requires_confirmation=True,
    timeout=30,
    category="file_mods",
)
register_tool_metadata(
    "delete_file",
    destructive=True,
    requires_confirmation=True,
    timeout=30,
    category="file_mods",
)
register_tool_metadata(
    "replace_in_file",
    destructive=True,
    requires_confirmation=True,
    timeout=30,
    category="file_mods",
)
register_tool_metadata("edit_file", destructive=True, timeout=30, category="file_mods")
register_tool_metadata(
    "delete_snippet",
    destructive=True,
    requires_confirmation=True,
    timeout=30,
    category="file_mods",
)
register_tool_metadata(
    "agent_run_shell_command",
    destructive=True,
    requires_confirmation=True,
    timeout=120,
    category="shell",
)
# Safe / read-only tools
register_tool_metadata(
    "read_file",
    destructive=False,
    idempotent=True,
    timeout=30,
    category="file_ops",
)
register_tool_metadata(
    "grep", destructive=False, idempotent=True, timeout=60, category="file_ops"
)
register_tool_metadata(
    "list_files",
    destructive=False,
    idempotent=True,
    timeout=30,
    category="file_ops",
)
