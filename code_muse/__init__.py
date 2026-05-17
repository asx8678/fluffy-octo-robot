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
    import importlib
    import pathlib

    _spec = importlib.util.find_spec("code_muse")
    if _spec is not None and _spec.origin is not None:
        _pkg_path = pathlib.Path(_spec.origin).parent
        for _so in _pkg_path.rglob("*.so"):
            # Extract module name from PEP 3149 naming: {name}.cpython-{ver}-{abi}.so
            _module_name = _so.name.split(".cpython-")[0]
            # Only count .so files that have a corresponding .pyx (not 3rd-party)
            _pyx_path = _so.parent / f"{_module_name}.pyx"
            if _pyx_path.exists():
                PYX_MODULE_COUNT += 1

        CYTHON_ENABLED = PYX_MODULE_COUNT > 0
except Exception:
    pass
