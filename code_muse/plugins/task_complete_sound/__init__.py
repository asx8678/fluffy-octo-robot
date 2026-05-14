"""Task Complete Sound plugin for Muse — audible notification on agent completion.

Plays a system notification sound (or custom file) when the top-level
agent run completes successfully.  On Linux, tries ``canberra-gtk-play``
before falling back to terminal bell.  Enabled via ``/sound on``;
disabled by default.

Architecture
------------
File structure under ``code_muse/plugins/task_complete_sound/``:

- ``config.py``            — Configuration accessors (muse.cfg) + toggle
- ``sound_player.py``      — Platform-aware async sound playback
- ``register_callbacks.py`` — Hook registration & slash commands
"""
