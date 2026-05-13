"""Build Cython extensions for wheel packaging.

Run as: python build_extensions.py build_ext --inplace
"""
import os

from Cython.Build import cythonize
from setuptools import Distribution, Extension

# Prevent setuptools from reading the project's pyproject.toml
# (it contains uv-specific keys like dev-dependencies that setuptools rejects).
Distribution.parse_config_files = lambda self, *args, **kwargs: None

# Find all .pyx files
pyx_files = []
for root, _dirs, files in os.walk("code_muse"):
    for f in files:
        if f.endswith(".pyx"):
            pyx_files.append(os.path.join(root, f))

extensions = [Extension(f.replace(os.sep, ".")[:-4], [f]) for f in pyx_files]

dist = Distribution(
    {
        "name": "code-muse-extensions",
        "ext_modules": cythonize(extensions, language_level=3),
    }
)
dist.script_args = ["build_ext", "--inplace"]
dist.parse_command_line()
dist.run_commands()
