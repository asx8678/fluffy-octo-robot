"""Version checking utilities for Muse."""

import asyncio

import httpx

from code_muse.messaging import emit_info, emit_success, emit_warning, get_message_bus
from code_muse.messaging.messages import VersionCheckMessage

UVX_REFRESH_COMMAND = "uvx code-muse"


def normalize_version(version_str):
    if not version_str:
        return version_str
    version_str = version_str.lstrip("v")
    return version_str


def _version_tuple(version_str):
    """Convert version string to tuple of ints for proper comparison."""
    try:
        return tuple(int(x) for x in version_str.split("."))
    except ValueError, AttributeError:
        return None


def version_is_newer(latest, current):
    """Return True if latest version is strictly newer than current."""
    latest_tuple = _version_tuple(normalize_version(latest))
    current_tuple = _version_tuple(normalize_version(current))
    if latest_tuple is None or current_tuple is None:
        return False
    return latest_tuple > current_tuple


def versions_are_equal(current, latest):
    current_norm = normalize_version(current)
    latest_norm = normalize_version(latest)
    # Try numeric tuple comparison first
    current_tuple = _version_tuple(current_norm)
    latest_tuple = _version_tuple(latest_norm)
    if current_tuple is not None and latest_tuple is not None:
        return current_tuple == latest_tuple
    # Fallback to string comparison
    return current_norm == latest_norm


async def fetch_latest_version(package_name):
    """Fetch the latest version of a package from PyPI asynchronously."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://pypi.org/pypi/{package_name}/json", timeout=5.0
            )
            response.raise_for_status()
            data = response.json()
            return data["info"]["version"]
    except Exception as e:
        emit_warning(f"Error fetching version: {e}")
        return None


async def default_version_mismatch_behavior(current_version):
    """Check for version updates asynchronously without blocking startup."""
    # Defensive: ensure current_version is never None
    if current_version is None:
        current_version = "0.0.0-unknown"
        emit_warning("Could not detect current version, using fallback")

    latest_version = await fetch_latest_version("code-muse")

    update_available = bool(
        latest_version and version_is_newer(latest_version, current_version)
    )

    # Emit structured version check message
    version_msg = VersionCheckMessage(
        current_version=current_version,
        latest_version=latest_version or current_version,
        update_available=update_available,
    )
    get_message_bus().emit(version_msg)

    # Also emit plain text for legacy renderer
    emit_info(f"Current version: {current_version}")

    if update_available:
        emit_info(f"Latest version: {latest_version}")
        emit_warning(f"A new version of Muse is available: {latest_version}")
        emit_success(
            f"Run to refresh uvx and start the latest version: {UVX_REFRESH_COMMAND}"
        )


def start_version_check(current_version):
    """Fire-and-forget version check as a background task."""
    asyncio.create_task(default_version_mismatch_behavior(current_version))
