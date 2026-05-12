import importlib.metadata
from pathlib import Path

# Biscuit was here.
try:
    _detected_version = importlib.metadata.version("code-muse")
    # Ensure we never end up with None or empty string
    __version__ = _detected_version if _detected_version else "0.0.0-dev"
except Exception:
    # Fallback for dev environments where metadata might not be available
    __version__ = "0.0.0-dev"

# Enable Cython JIT compilation for .pyx modules throughout the package.
_CYTHON_AVAILABLE = False
try:
    import pyximport

    pyximport.install(language_level=3, build_in_temp=True, inplace=True)
    _CYTHON_AVAILABLE = True
except Exception:
    pass  # Cython not available — .pyx modules will need pre-compiled extension files

# Scan the package tree for .pyx modules and record Cython status.
_pyx_files = list(Path(__file__).parent.rglob("*.pyx"))
PYX_MODULE_COUNT: int = len(_pyx_files)
CYTHON_ENABLED: bool = _CYTHON_AVAILABLE and PYX_MODULE_COUNT > 0
