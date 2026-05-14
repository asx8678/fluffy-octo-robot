"""Task Complete Sound plugin for Muse — audible notification on agent completion.

Plays a system beep or custom sound file when the top-level agent run
completes successfully.  Enabled via ``/sound on``; disabled by default.

Architecture
------------
File structure under ``code_muse/plugins/task_complete_sound/``:

- ``config.py``            — Configuration accessors (muse.cfg) + toggle
- ``sound_player.py``      — Platform-aware async sound playback
- ``register_callbacks.py`` — Hook registration & slash commands
"""
