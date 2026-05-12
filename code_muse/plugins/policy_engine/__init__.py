"""Policy Engine plugin for Muse.

TOML-based rules that control tool execution:
- allow → auto-approve (skip confirmation)
- deny → block with message
- ask_user → show normal confirmation dialog

Rules match by toolName (with * wildcard) and optional commandPrefix
(for shell commands). Rules are loaded from:
- User tier: ~/.muse/policies/*.toml
- Project tier: .muse/policies/*.toml

Priority resolves conflicts (higher wins).
"""

from code_muse.plugins.policy_engine.approval_flow_integration import (
    integrate_policy_check,
)
from code_muse.plugins.policy_engine.policy_evaluator import (
    evaluate_policy,
    evaluate_tool_policy,
)
from code_muse.plugins.policy_engine.policy_file_discovery import (
    clear_policy_cache,
    discover_policy_files,
    load_all_policies,
)
from code_muse.plugins.policy_engine.policy_toml_schema import (
    Decision,
    ToolRule,
    parse_policy_toml,
    validate_rules,
)

__all__ = [
    "Decision",
    "ToolRule",
    "clear_policy_cache",
    "discover_policy_files",
    "evaluate_policy",
    "evaluate_tool_policy",
    "integrate_policy_check",
    "load_all_policies",
    "parse_policy_toml",
    "validate_rules",
]
