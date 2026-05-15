#!/usr/bin/env python
"""Build script for Muse (code-muse) with Cython extensions.

This setup.py is used by the setuptools build backend (see pyproject.toml)
to compile the performance-critical Cython modules:

- code_muse.terminal_utils  (ANSI stripping + cross-platform terminal control)
- code_muse.security.redaction  (fast secret redaction for logs/output)

The .pyx sources are the only committed Cython artifacts. Generated .c and
platform binaries (.so/.pyd) are produced at build time and never committed.

Free-threaded Python 3.14+ is supported (Cython >= 3.1 required).
"""

from __future__ import annotations

import os

from setuptools import Extension, find_packages, setup
from setuptools.command.build_ext import build_ext

try:
    from Cython.Build import cythonize
    from Cython.Compiler import Options

    HAS_CYTHON = True
except ImportError:
    HAS_CYTHON = False


# ---------------------------------------------------------------------------


class BuildExt(build_ext):
    """Custom build_ext that gives better error messages for missing Cython."""

    def run(self) -> None:
        if not HAS_CYTHON:
            # This should never happen because cython is in build requirements,
            # but provide a helpful message if someone bypasses the PEP 517 build.
            raise RuntimeError(
                "Cython is required to build Muse from source.\n"
                "Install build deps with: pip install -e .[dev] or "
                "pip install build && pip wheel ."
            )
        super().run()


# ---------------------------------------------------------------------------


def get_extensions() -> list[Extension]:
    """Return the list of Cython extensions to build."""
    extensions = [
        Extension(
            "code_muse.terminal_utils",
            sources=["code_muse/terminal_utils.pyx"],
            # Optimization flags for the hot ANSI strip path (nogil loop)
            extra_compile_args=["-O3", "-ffast-math"] if os.name != "nt" else ["/O2"],
            define_macros=[("CYTHON_TRACE", "0")],
        ),
        Extension(
            "code_muse.security.redaction",
            sources=["code_muse/security/redaction.pyx"],
            extra_compile_args=["-O3"] if os.name != "nt" else ["/O2"],
        ),
    ]

    # Cython compiler directives — safe & fast for 3.14+ free-threaded builds
    compiler_directives = {
        "language_level": 3,
        "boundscheck": False,
        "wraparound": False,
        "initializedcheck": False,
        "cdivision": True,
        "nonecheck": False,
        "embedsignature": False,
    }

    # Only cythonize when Cython is present (normal PEP 517 build path)
    if HAS_CYTHON:
        # Set global options for cleaner build output
        Options.annotate = False
        Options.fast_fail = True

        return cythonize(
            extensions,
            compiler_directives=compiler_directives,
            annotate=False,
            nthreads=0,  # auto
            force=False,  # respect timestamps
        )

    # Fallback: return the .pyx as sources — setuptools will fail later with clear error
    return extensions


# ---------------------------------------------------------------------------


setup(
    # Most metadata comes from pyproject.toml [project]
    # We only augment with the compiled extensions here.
    ext_modules=get_extensions(),
    packages=find_packages(include=["code_muse", "code_muse.*"]),
    include_package_data=True,
    # The custom build_ext is optional but gives nicer errors
    cmdclass={"build_ext": BuildExt},
    zip_safe=False,  # C extensions cannot be run from zip
)


if __name__ == "__main__":
    # Allow running `python setup.py build_ext --inplace` during development
    setup(
        ext_modules=get_extensions(),
        packages=find_packages(include=["code_muse", "code_muse.*"]),
        cmdclass={"build_ext": BuildExt},
        zip_safe=False,
    )
