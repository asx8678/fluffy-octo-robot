"""Shared pytest fixtures for plugin tests."""

import pyximport

pyximport.install(language_level=3, build_in_temp=True, inplace=True)
