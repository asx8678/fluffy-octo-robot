"""Context-Aware Code Reader Plugin.

Gives the LLM a `read_relevant_code` tool that uses tree-sitter AST analysis
+ relevance scoring to return only the portions of a file that matter for the
current task, dramatically reducing token usage compared to full `read_file`.

This is the implementation of the Context-Aware Code Reader epic.
"""

from code_muse.plugins.context_aware_reader import config, register_callbacks

__all__ = ["config", "register_callbacks"]
