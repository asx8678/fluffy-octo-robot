"""Compression strategies for the filter engine."""

try:
    import pyximport

    pyximport.install(language_level=3, build_in_temp=True, inplace=True)
except Exception:
    pass  # Cython not installed or pyximport unavailable — pure Python fallback
