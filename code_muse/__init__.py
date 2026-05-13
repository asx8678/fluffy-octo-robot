import importlib.metadata
import logging
import os
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


def _rebuild_stale_cython_modules(package_root: Path) -> None:
    """Delete stale compiled extensions so pyximport rebuilds them.

    Checks both file mtime AND embedded module name to catch extensions
    compiled from an older package version (e.g. after a rename from
    ``code_puppy`` to ``code_muse``).

    Safe no-op when no ``.pyx`` files exist or no stale extensions found.
    """
    if not list(package_root.rglob("*.pyx")):
        return

    import importlib.util

    # Read first 4 KB of each .so to check for old module names.
    # Compiled Cython modules embed their source package path (e.g.
    # ``code_puppy.plugins.…``) in the binary.
    _OLD_NAMES = [b"code_puppy", b"code.puppy"]

    stale_count = 0
    for pyx_file in package_root.rglob("*.pyx"):
        pyx_mtime = pyx_file.stat().st_mtime
        parent = pyx_file.parent
        stem = pyx_file.stem

        for so_file in parent.glob(f"{stem}*.so"):
            if not so_file.is_file():
                continue

            # 1. Mtime check: .so is older than .pyx source
            # 2. Content check: .so still references old package name
            is_stale = so_file.stat().st_mtime < pyx_mtime
            if not is_stale:
                try:
                    header = so_file.read_bytes()[:4096]
                    is_stale = any(old in header for old in _OLD_NAMES)
                except OSError:
                    pass

            if is_stale:
                try:
                    so_file.unlink()
                    stale_count += 1
                    logger.debug("Removed stale extension: %s", so_file)
                except OSError:
                    pass

    if stale_count:
        logger.info(
            "Removed %d stale Cython extension(s) — will rebuild on next import",
            stale_count,
        )


# Enable Cython JIT compilation for .pyx modules throughout the package.
_CYTHON_AVAILABLE = False
_PACKAGE_ROOT = Path(__file__).parent
try:
    import pyximport

    pyximport.install(language_level=3, build_in_temp=True, inplace=True)
    _CYTHON_AVAILABLE = True
    _rebuild_stale_cython_modules(_PACKAGE_ROOT)
except Exception:
    pass  # Cython not available — .pyx modules will need pre-compiled extension files

# Scan the package tree for .pyx modules and record Cython status.
_pyx_files = list(_PACKAGE_ROOT.rglob("*.pyx"))
PYX_MODULE_COUNT: int = len(_pyx_files)
CYTHON_ENABLED: bool = _CYTHON_AVAILABLE and PYX_MODULE_COUNT > 0
