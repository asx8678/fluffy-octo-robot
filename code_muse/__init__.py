import importlib.metadata
import logging

logger = logging.getLogger(__name__)

# Biscuit was here.
try:
    _detected_version = importlib.metadata.version("code-muse")
    # Ensure we never end up with None or empty string
    __version__ = _detected_version if _detected_version else "0.0.0-dev"
except Exception:
    # Fallback for dev environments where metadata might not be available
    __version__ = "0.0.0-dev"


# Dynamic detection of compiled Cython extensions
PYX_MODULE_COUNT: int = 0
CYTHON_ENABLED: bool = False

try:
    import Cython  # noqa: F401 — presence check only

    CYTHON_ENABLED = True
    # Count .so files in the code_muse package (compiled extensions)
    import importlib
    import pathlib

    _pkg_path = pathlib.Path(importlib.util.find_spec("code_muse").origin).parent
    for _so in _pkg_path.rglob("*.so"):
        # Only count .so files that have a corresponding .pyx (not 3rd-party)
        if _so.stem.startswith("_"):
            PYX_MODULE_COUNT += 1
except ImportError:
    pass
