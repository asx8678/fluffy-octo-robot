"""Config: central configuration for code_muse.

Re-exports every public name from submodules so that
``from code_muse.config import X`` continues to work.
"""

# --- Paths ---
# --- Models ---
from code_muse.config.models import (  # noqa: F401
    _SESSION_MODEL,
    _default_model_from_models_json,
    _default_vision_model_from_models_json,
    _validate_model_exists,
    clear_model_cache,
    get_global_model_name,
    get_model_context_length,
    get_protected_token_count,
    model_supports_setting,
    reset_session_model,
    set_model_name,
)

# --- Parser ---
from code_muse.config.parser import (  # noqa: F401
    DEFAULT_SECTION,
    REQUIRED_KEYS,
    ensure_config_exists,
    get_agent_name,
    get_allow_recursion,
    get_animations_enabled,
    get_auto_approve,
    get_compaction_strategy,
    get_compaction_threshold,
    get_config_keys,
    get_enable_streaming,
    get_frontend_emitter_enabled,
    get_frontend_emitter_max_recent_events,
    get_frontend_emitter_queue_size,
    get_grep_output_verbose,
    get_http2,
    get_max_consecutive_tool_errors,
    get_max_hook_retries,
    get_max_tool_calls,
    get_message_limit,
    get_max_agent_steps,
    get_overall_run_timeout_seconds,
    get_owner_name,
    get_puppy_name,
    get_resume_message_count,
    get_safety_permission_level,
    get_subagent_verbose,
    get_total_tokens_limit,
    get_value,
    get_yolo_mode,
    isolated_config,
    reset_value,
    set_config_value,
    set_http2,
    set_value,
)
from code_muse.config.paths import (  # noqa: F401
    AGENTS_DIR,
    AUTOSAVE_DIR,
    CACHE_DIR,
    CHATGPT_MODELS_FILE,
    CLAUDE_MODELS_FILE,
    COMMAND_HISTORY_FILE,
    CONFIG_DIR,
    CONFIG_FILE,
    CONTEXTS_DIR,
    COPILOT_MODELS_FILE,
    DATA_DIR,
    EXTRA_MODELS_FILE,
    GEMINI_MODELS_FILE,
    MODELS_CACHE_FILE,
    MODELS_FILE,
    SKILLS_DIR,
    STATE_DIR,
    _get_xdg_dir,
)

# --- Security ---
from code_muse.config.security import (  # noqa: F401
    get_api_key,
    load_api_keys_to_environment,
    set_api_key,
)

# --- Session ---
from code_muse.config.session import (  # noqa: F401
    auto_save_session_if_enabled,
    finalize_autosave_session,
    get_auto_save_session,
    get_current_autosave_id,
    get_current_autosave_session_name,
    get_max_saved_sessions,
    initialize_command_history_file,
    normalize_command_history,
    rotate_autosave_id,
    save_command_to_history,
    set_auto_save_session,
    set_current_autosave_from_session_name,
    set_max_saved_sessions,
)

# --- Agent ---
from code_muse.config_agent import (  # noqa: F401
    PACK_AGENT_NAMES,
    UC_AGENT_NAMES,
    clear_agent_pinned_model,
    get_agent_pinned_model,
    get_agents_pinned_to_model,
    get_all_agent_pinned_models,
    get_default_agent,
    get_pack_agents_enabled,
    get_project_agents_directory,
    get_universal_constructor_enabled,
    get_user_agents_directory,
    set_agent_pinned_model,
    set_default_agent,
    set_universal_constructor_enabled,
)

# --- Appearance ---
from code_muse.config_appearance import (  # noqa: F401
    _DEFAULT_DIFF_ADDITION_HEX,
    _DEFAULT_DIFF_DELETION_HEX,
    DEFAULT_BANNER_COLORS,
    _coerce_to_hex,
    get_all_banner_colors,
    get_banner_color,
    get_diff_addition_color,
    get_diff_context_lines,
    get_diff_deletion_color,
    get_suppress_informational_messages,
    get_suppress_thinking_messages,
    reset_all_banner_colors,
    reset_banner_color,
    set_banner_color,
    set_diff_addition_color,
    set_diff_deletion_color,
    set_diff_highlight_style,
    set_suppress_informational_messages,
    set_suppress_thinking_messages,
)

# --- Per-model settings ---
from code_muse.config_model import (  # noqa: F401
    _sanitize_model_name_for_key,
    clear_model_settings,
    get_all_model_settings,
    get_effective_model_settings,
    get_effective_seed,
    get_effective_temperature,
    get_effective_top_p,
    get_model_setting,
    get_muse_token,
    get_openai_reasoning_effort,
    get_openai_reasoning_summary,
    get_openai_verbosity,
    get_summarization_model_name,
    get_temperature,
    set_model_setting,
    set_muse_token,
    set_openai_reasoning_effort,
    set_openai_reasoning_summary,
    set_openai_verbosity,
    set_summarization_model_name,
    set_temperature,
)
