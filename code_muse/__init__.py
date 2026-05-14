import importlib.metadata
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Biscuit was here.
try:
    _detected_version = importlib.metadata.version("code-muse")
    # Ensure we never end up with None or empty string
    __version__ = _detected_version if _detected_version else "0.0.0-dev"
except Exception:
    # Fallback for dev environments where metadata might not be available
    __version__ = "0.0.0-dev"


# Cython extension module support
# Pre-built .so/.pyd files are included in wheel distributions.
_PACKAGE_ROOT = Path(__file__).parent
_pyx_files = list(_PACKAGE_ROOT.rglob("*.pyx"))
PYX_MODULE_COUNT: int = len(_pyx_files)
_CYTHON_AVAILABLE = bool(
    any(_PACKAGE_ROOT.rglob("*.so")) or any(_PACKAGE_ROOT.rglob("*.pyd"))
)
CYTHON_ENABLED: bool = _CYTHON_AVAILABLE
