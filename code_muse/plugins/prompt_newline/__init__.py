"""Plugin: drop user input onto a fresh line below the prompt chrome.

When enabled, transforms

    [Run] prompt [agent] [model] (~/very/long/cwd) >>> typed text

into

    [Run] prompt [agent] [model] (~/very/long/cwd) >>>
    typed text

Toggle at runtime with ``/prompt_newline [on|off]``. Persisted in muse.cfg.
"""
