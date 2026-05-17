"""Smart Output Compressor Plugin.

Gives the LLM a `read_smart` tool that uses tree-sitter AST analysis
+ relevance scoring to return only the portions of a file that matter for the
current task, dramatically reducing token usage compared to full `read_file`.

This is the implementation of Initiative 1.2: Smart Output Compressor.
"""

from code_muse.plugins.smart_output_compressor import config, register_callbacks

__all__ = ["config", "register_callbacks"]
