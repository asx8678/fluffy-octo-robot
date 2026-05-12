"""Auto-Review plugin — second-agent review of file changes.

Hooks into ``post_tool_call`` to automatically review file modifications
using a separate LLM call. Displays visible review status so the user always
knows when a review is happening and what was found.
"""
