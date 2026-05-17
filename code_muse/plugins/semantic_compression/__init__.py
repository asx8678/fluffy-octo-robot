"""Semantic Compression Plugin.

Lossy text compression that strips predictable grammar while
preserving semantic content. Works on tool outputs and provides
a ``/compress`` slash command for manual use.

Compression is **enabled by default** for high-impact tools:
``read_file``, ``grep``, ``run_shell_command``, ``list_files``,
``agent_run_shell_command``, ``invoke_agent``, ``read_relevant_code``.

Use ``/semantic-compression off`` to disable; ``/show original`` to
view the last uncompressed output.
"""
