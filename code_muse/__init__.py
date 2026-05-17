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


# Cython is not used — everything runs in pure Python
PYX_MODULE_COUNT: int = 0
CYTHON_ENABLED: bool = False
