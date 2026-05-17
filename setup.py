"""Cython build configuration — compiles .pyx extensions in-place."""

from Cython.Build import cythonize
from setuptools import setup

setup(
    ext_modules=cythonize(
        [
            "code_muse/list_filtering.pyx",
            "code_muse/tools/_ignore_matcher.pyx",
        ],
        language_level="3",
        compiler_directives={"binding": True, "embedsignature": True},
    ),
)
