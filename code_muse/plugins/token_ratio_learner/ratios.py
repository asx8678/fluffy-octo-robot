"""Learned token-per-character ratios for accurate token estimation.

Stores actual chars-per-token ratios observed from API responses.
Future estimates use the learned ratio, falling back to 2.5 (the default).
Storage: ``~/.muse/token_ratios.json``.
"""

import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_RATIO = 2.5
_MIN_RATIO = 1.5
_MAX_RATIO = 3.5

_LEARNED_RATIOS: dict[str, float] = {}
_ratios_loaded: bool = False
_ratios_lock = threading.Lock()

_TOKEN_RATIOS_PATH: Path = Path(
    os.path.expanduser(
        os.environ.get(
            "MUSE_TOKEN_RATIOS_PATH",
            str(Path.home() / ".muse" / "token_ratios.json"),
        )
    )
)


def _ensure_ratios_loaded() -> None:
    global _ratios_loaded
    with _ratios_lock:
        if _ratios_loaded:
            return
        _LEARNED_RATIOS.clear()
        _LEARNED_RATIOS.update(_load_learned_ratios())
        _ratios_loaded = True


def _load_learned_ratios() -> dict[str, float]:
    try:
        if _TOKEN_RATIOS_PATH.is_file():
            data = json.loads(_TOKEN_RATIOS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    k.lower(): max(_MIN_RATIO, min(_MAX_RATIO, float(v)))
                    for k, v in data.items()
                    if isinstance(v, (int, float)) and v > 0
                }
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


def _save_learned_ratios(ratios: dict[str, float]) -> None:
    try:
        parent = _TOKEN_RATIOS_PATH.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(ratios, tmp, indent=2)
            os.replace(tmp_name, str(_TOKEN_RATIOS_PATH))
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
    except OSError:
        pass


def _record_token_ratio(model: str, char_count: int, token_count: int) -> None:
    """Record an observed chars-per-token ratio. 70/30 blend with existing."""
    if char_count <= 0 or token_count <= 0:
        return

    model_name = model.split(":", 1)[1] if ":" in model else model
    model_name = model_name.lower()

    _ensure_ratios_loaded()

    new_ratio = max(_MIN_RATIO, min(_MAX_RATIO, char_count / token_count))

    with _ratios_lock:
        old = _LEARNED_RATIOS.get(model_name)
        blended = 0.7 * old + 0.3 * new_ratio if old is not None else new_ratio
        _LEARNED_RATIOS[model_name] = round(blended, 4)
        _save_learned_ratios(_LEARNED_RATIOS)


def count_tokens(text: str, model: str | None = None) -> int:
    """Estimate token count using learned ratio or default (2.5)."""
    _ensure_ratios_loaded()

    if not text:
        return 0

    model_name = None
    if model:
        model_name = model.split(":", 1)[1] if ":" in model else model
        model_name = model_name.lower()

    ratio = _LEARNED_RATIOS.get(model_name or "", _DEFAULT_RATIO)
    ratio = max(_MIN_RATIO, min(_MAX_RATIO, ratio))

    return max(1, round(len(text) / ratio))


def get_ratio_for_model(model: str) -> float:
    _ensure_ratios_loaded()
    model_name = model.split(":", 1)[1] if ":" in model else model
    raw = _LEARNED_RATIOS.get(model_name.lower(), _DEFAULT_RATIO)
    return max(_MIN_RATIO, min(_MAX_RATIO, raw))


def list_known_ratios() -> dict[str, float]:
    _ensure_ratios_loaded()
    with _ratios_lock:
        return dict(_LEARNED_RATIOS)


def set_ratios_path(path: str | Path) -> None:
    """Override path (for testing)."""
    global _TOKEN_RATIOS_PATH, _ratios_loaded
    _TOKEN_RATIOS_PATH = Path(path)
    with _ratios_lock:
        _LEARNED_RATIOS.clear()
        _ratios_loaded = False
