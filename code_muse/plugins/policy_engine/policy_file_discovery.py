import logging
import os
from pathlib import Path

from code_muse.plugins.policy_engine.policy_toml_schema import (
    ToolRule,
    parse_policy_toml,
)

logger = logging.getLogger(__name__)

# Simple cache: list of rules + dict of file mtimes
_rule_cache: list[ToolRule] | None = None
_file_mtimes: dict[str, float] = {}


def _get_user_policies_dir() -> Path:
    return Path.home() / ".muse" / "policies"


def _get_project_policies_dir() -> Path:
    return Path(os.getcwd()) / ".muse" / "policies"


def discover_policy_files() -> list[Path]:
    files: list[Path] = []
    for directory in (_get_user_policies_dir(), _get_project_policies_dir()):
        if not directory.exists():
            continue
        try:
            toml_files = sorted(directory.glob("*.toml"))
        except OSError as exc:
            logger.warning("Cannot scan policy directory %s: %s", directory, exc)
            continue
        for f in toml_files:
            if not f.is_file():
                continue
            try:
                # Check readability
                _ = f.stat()
            except OSError as exc:
                logger.warning("Unreadable policy file %s: %s", f, exc)
                continue
            files.append(f)
    return files


def _files_changed(files: list[Path]) -> bool:
    global _file_mtimes
    current: dict[str, float] = {}
    for f in files:
        try:
            current[str(f)] = f.stat().st_mtime
        except OSError:
            return True
    return current != _file_mtimes


def load_all_policies(force_reload: bool = False) -> list[ToolRule]:
    global _rule_cache, _file_mtimes

    files = discover_policy_files()

    if not force_reload and _rule_cache is not None and not _files_changed(files):
        return _rule_cache

    all_rules: list[ToolRule] = []
    new_mtimes: dict[str, float] = {}

    for f in files:
        try:
            rules = parse_policy_toml(f)
            all_rules.extend(rules)
            new_mtimes[str(f)] = f.stat().st_mtime
        except ValueError as exc:
            logger.warning("Skipping invalid policy file %s: %s", f, exc)
        except OSError as exc:
            logger.warning("Cannot read policy file %s: %s", f, exc)

    _rule_cache = all_rules
    _file_mtimes = new_mtimes
    logger.info("Loaded %d policy rules from %d file(s)", len(all_rules), len(files))
    return all_rules


def clear_policy_cache() -> None:
    global _rule_cache, _file_mtimes
    _rule_cache = None
    _file_mtimes = {}
    logger.info("Policy cache cleared")
