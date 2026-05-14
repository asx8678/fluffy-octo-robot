"""Platform-aware async sound playback for the Task Complete Sound plugin.

Plays notification sounds in a non-blocking way using async subprocesses
or thread offloading.  Never raises — all errors are caught and logged.
"""

import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


async def play_sound(file_path: str | None = None) -> None:
    """Play a notification sound asynchronously.

    Args:
        file_path: Path to a custom sound file, or None for the default
            system beep.

    Platform strategy:
        - **macOS**: ``afplay <path>`` for custom, ``osascript -e 'beep'``
          for default.
        - **Linux**: ``paplay <path>`` or ``aplay <path>`` for custom,
          ``canberra-gtk-play`` for default, then terminal bell.
        - **Windows**: ``winsound.PlaySound`` for custom,
          ``winsound.MessageBeep`` for default.
        - **Fallback**: Terminal bell ``\\a``.
    """
    try:
        if file_path and Path(file_path).is_file():
            await _play_file(file_path)
        else:
            await _play_default()
    except Exception:
        logger.debug("Sound playback failed", exc_info=True)


async def _play_file(path: str) -> None:
    """Play a sound file via the platform's preferred player."""
    system = sys.platform

    if system == "darwin":
        if not await _run_subprocess("afplay", path):
            _terminal_bell()
    elif system == "win32":
        await _play_winsound_file(path)
    elif system.startswith("linux"):
        # Try PulseAudio first, fall back to ALSA, then bell
        if not await _run_subprocess("paplay", path) and not await _run_subprocess(
            "aplay", path
        ):
            _terminal_bell()
    else:
        # Unknown platform — terminal bell fallback
        _terminal_bell()


async def _play_default() -> None:
    """Play the default system notification sound."""
    system = sys.platform

    if system == "darwin":
        if not await _run_subprocess("osascript", "-e", "beep"):
            _terminal_bell()
    elif system == "win32":
        await _play_winsound_default()
    elif system.startswith("linux"):
        # Try libcanberra system sound, then terminal bell
        if not await _run_subprocess("canberra-gtk-play", "--id", "bell"):
            _terminal_bell()
    else:
        _terminal_bell()


async def _run_subprocess(*args: str) -> bool:
    """Execute a subprocess asynchronously.

    Returns:
        ``True`` if the command ran and exited successfully,
        ``False`` on any failure (not found, timeout, non-zero exit).

    Does **not** call ``_terminal_bell()`` — callers decide fallback.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        returncode = await asyncio.wait_for(proc.wait(), timeout=5.0)
        return returncode == 0
    except FileNotFoundError:
        logger.debug("Sound player not found: %s", args[0])
    except TimeoutError:
        logger.debug("Sound playback timed out: %s", args[0])
    except Exception:
        logger.debug("Sound subprocess error", exc_info=True)
    return False


async def _play_winsound_file(path: str) -> None:
    """Play a sound file on Windows via winsound (thread-offloaded)."""
    try:
        import winsound

        def _sync() -> None:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)

        await asyncio.to_thread(_sync)
    except ImportError:
        _terminal_bell()
    except Exception:
        logger.debug("winsound file playback failed", exc_info=True)


async def _play_winsound_default() -> None:
    """Play the default Windows notification sound via winsound."""
    try:
        import winsound

        await asyncio.to_thread(winsound.MessageBeep)
    except ImportError:
        _terminal_bell()
    except Exception:
        logger.debug("winsound default playback failed", exc_info=True)


def _terminal_bell() -> None:
    """Ring the terminal bell as a universal fallback."""
    import contextlib

    with contextlib.suppress(Exception):
        print("\a", end="", flush=True)


async def play_notification() -> None:
    """Read config and play the appropriate notification sound."""
    from code_muse.plugins.task_complete_sound.config import (
        get_sound_file,
        is_sound_enabled,
    )

    if not is_sound_enabled():
        return

    await play_sound(get_sound_file())


async def play_test() -> None:
    """Play a test sound immediately (awaited, not fire-and-forget)."""
    from code_muse.plugins.task_complete_sound.config import get_sound_file

    await play_sound(get_sound_file())
