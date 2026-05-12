"""Autonomous Memory Pipeline plugin.

Infrastructure for scanning past sessions, extracting knowledge,
consolidating memories, and injecting them into prompts.
"""

from .consolidation import consolidate_memories, write_memory_files
from .extraction import ExtractionResult, extract_session_knowledge
from .lease_lock import LeaseHandle, acquire_memory_lease, release_lease
from .memory_injection import inject_into_system_prompt, load_memory_injection
from .secret_scanner import SCAN_PATTERNS, SecretMatch, scan_for_secrets
from .session_scanner import (
    SessionInfo,
    get_memory_dir,
    get_sessions_dir,
    mark_session_processed,
    scan_eligible_sessions,
)

__all__ = [
    "acquire_memory_lease",
    "consolidate_memories",
    "extract_session_knowledge",
    "get_memory_dir",
    "get_sessions_dir",
    "inject_into_system_prompt",
    "lease_lock",
    "load_memory_injection",
    "mark_session_processed",
    "release_lease",
    "scan_eligible_sessions",
    "scan_for_secrets",
    "write_memory_files",
    "ExtractionResult",
    "LeaseHandle",
    "SCAN_PATTERNS",
    "SecretMatch",
    "SessionInfo",
]
