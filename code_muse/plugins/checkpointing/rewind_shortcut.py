"""Esc×2 rewind keyboard shortcut."""

import logging
import sys
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class DoublePressDetector:
    """Detects double-press of a key within a time window."""

    def __init__(self, window_ms: int = 500) -> None:
        self._window_ms = window_ms
        self._last_press: float = 0.0

    def press(self) -> bool:
        now = time.monotonic()
        delta_ms = (now - self._last_press) * 1000
        self._last_press = now
        return 0 < delta_ms < self._window_ms


class RewindKeyListener:
    """Daemon thread that listens for raw ESC keycodes and triggers rewind on double-press."""

    def __init__(self, on_double_esc: Callable[[], None]) -> None:
        self._detector = DoublePressDetector()
        self._on_double_esc = on_double_esc
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True)

    def start(self) -> None:
        self._thread.start()
        logger.info("RewindKeyListener started")

    def stop(self) -> None:
        self._stop.set()
        logger.info("RewindKeyListener stopped")

    def _listen(self) -> None:
        if sys.platform == "win32":
            self._listen_windows()
        else:
            self._listen_posix()

    def _listen_posix(self) -> None:
        try:
            import select
            import termios
            import tty

            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            try:
                while not self._stop.is_set():
                    ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if ready:
                        char = sys.stdin.read(1)
                        if char == "\x1b":
                            if self._detector.press():
                                try:
                                    self._on_double_esc()
                                except Exception as exc:
                                    logger.error(f"Double-esc handler failed: {exc}")
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception as exc:
            logger.debug(f"POSIX rewind listener could not start: {exc}")

    def _listen_windows(self) -> None:
        try:
            import msvcrt

            while not self._stop.is_set():
                if msvcrt.kbhit():
                    char = msvcrt.getch()
                    if char == b"\x1b" and self._detector.press():
                        try:
                            self._on_double_esc()
                        except Exception as exc:
                            logger.error(f"Double-esc handler failed: {exc}")
                time.sleep(0.05)
        except Exception as exc:
            logger.debug(f"Windows rewind listener could not start: {exc}")
