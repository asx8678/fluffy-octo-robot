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
# Runtime compilation via pyximport is only used as fallback for development.
_CYTHON_AVAILABLE = False
PYX_MODULE_COUNT: int = 0

# Check for pre-built extensions first
_PACKAGE_ROOT = Path(__file__).parent
_pyx_files = list(_PACKAGE_ROOT.rglob("*.pyx"))
PYX_MODULE_COUNT = len(_pyx_files)
_has_prebuilt_extensions = (
    any(_PACKAGE_ROOT.rglob("*.so")) or any(_PACKAGE_ROOT.rglob("*.pyd"))
)

if not _has_prebuilt_extensions:
    try:
        import pyximport
        pyximport.install(language_level=3, build_in_temp=True, inplace=True)
        _CYTHON_AVAILABLE = True
    except Exception:
        pass  # Cython not available — .pyx modules need pre-compiled extension files

CYTHON_ENABLED: bool = _has_prebuilt_extensions or (
    _CYTHON_AVAILABLE and PYX_MODULE_COUNT > 0
)
