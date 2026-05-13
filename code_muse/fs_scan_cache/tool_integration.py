"""Cached wrappers around glob, grep, and find operations."""

import fnmatch
import os
import re
from pathlib import Path

from code_muse.fs_scan_cache.scan_cache_core import GlobMatch, ScanCache


def _resolve_root(root: str) -> Path:
    return Path(root).expanduser().resolve()


def _is_hidden(path: Path) -> bool:
    """Return True if any component of *path* starts with '.'."""
    return any(
        part.startswith(".") for part in path.parts if part not in (".", "..", os.sep)
    )


def _should_skip(
    path: Path,
    *,
    include_hidden: bool,
    use_gitignore: bool,
    skip_node_modules: bool,
) -> bool:
    """Return True if *path* should be excluded from scan results."""
    if not include_hidden and _is_hidden(path):
        return True
    if skip_node_modules and "node_modules" in path.parts:
        return True
    if use_gitignore:
        # Lightweight approximation: skip `.git` directory
        if ".git" in path.parts:
            return True
    return False


def _stat_entry(p: Path) -> tuple[str, float, int]:
    """Return (file_type, mtime, size) for *p*, falling back gracefully."""
    try:
        st = p.stat(follow_symlinks=False)
        if p.is_symlink():
            return "symlink", st.st_mtime, 0
        if p.is_dir():
            return "dir", st.st_mtime, 0
        return "file", st.st_mtime, st.st_size
    except (OSError, ValueError):
        return "file", 0.0, 0


def _glob_scanner(
    pattern: str,
    root: str,
    *,
    hidden: bool,
    gitignore: bool,
    node_modules: bool,
) -> list[GlobMatch]:
    """Perform a filesystem glob and return filtered GlobMatch entries."""
    base = _resolve_root(root)
    results: list[GlobMatch] = []

    if "**" in pattern:
        # Recursive glob via rglob
        raw_pattern = pattern.replace("**/", "").replace("**", "")
        # If pattern is just '**', match everything
        if raw_pattern in {"", "*"}:
            iterator = base.rglob("*")
        else:
            iterator = base.rglob(raw_pattern)
    else:
        iterator = base.glob(pattern)

    for p in iterator:
        try:
            relative = p.relative_to(base)
        except ValueError:
            relative = p
        if _should_skip(
            relative,
            include_hidden=hidden,
            use_gitignore=gitignore,
            skip_node_modules=node_modules,
        ):
            continue
        file_type, mtime, size = _stat_entry(p)
        results.append(
            GlobMatch(
                path=str(p),
                file_type=file_type,
                mtime=mtime,
                size=size,
            )
        )
    return results


def _grep_scanner(
    pattern: str,
    root: str,
    *,
    hidden: bool,
    gitignore: bool,
    node_modules: bool,
) -> list[GlobMatch]:
    """Recursively search file contents with regex and return matching files."""
    base = _resolve_root(root)
    results: list[GlobMatch] = []
    compiled = re.compile(pattern)
    max_matches = 50

    for p in base.rglob("*"):
        try:
            relative = p.relative_to(base)
        except ValueError:
            relative = p
        if _should_skip(
            relative,
            include_hidden=hidden,
            use_gitignore=gitignore,
            skip_node_modules=node_modules,
        ):
            continue
        if not p.is_file() or p.is_symlink():
            continue
        try:
            # Skip binary / very large files
            size = p.stat().st_size
            if size > 5 * 1024 * 1024:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        if compiled.search(text):
            file_type, mtime, fsize = _stat_entry(p)
            results.append(
                GlobMatch(
                    path=str(p),
                    file_type=file_type,
                    mtime=mtime,
                    size=fsize,
                )
            )
            if len(results) >= max_matches:
                break
    return results


def _find_scanner(
    name: str,
    root: str,
    *,
    hidden: bool,
    gitignore: bool,
    node_modules: bool,
) -> list[GlobMatch]:
    """Recursively find files/directories whose basename matches *name*."""
    base = _resolve_root(root)
    results: list[GlobMatch] = []

    for p in base.rglob("*"):
        try:
            relative = p.relative_to(base)
        except ValueError:
            relative = p
        if _should_skip(
            relative,
            include_hidden=hidden,
            use_gitignore=gitignore,
            skip_node_modules=node_modules,
        ):
            continue
        if not fnmatch.fnmatch(p.name, name):
            continue
        file_type, mtime, size = _stat_entry(p)
        results.append(
            GlobMatch(
                path=str(p),
                file_type=file_type,
                mtime=mtime,
                size=size,
            )
        )
    return results


# Module-level default cache used by the cached_* helpers.
_default_cache: ScanCache | None = None


def _get_default_cache() -> ScanCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = ScanCache()
    return _default_cache


def cached_glob(
    pattern: str,
    root: str = ".",
    hidden: bool = False,
    gitignore: bool = True,
    node_modules: bool = True,
    cache: bool = False,
) -> tuple[list[GlobMatch], float | None]:
    """Glob with optional scan caching.

    Returns:
        ``(entries, cache_age_ms)`` — *cache_age_ms* is ``None`` when
        *cache* is ``False``.
    """
    if not cache:
        return (
            _glob_scanner(
                pattern,
                root,
                hidden=hidden,
                gitignore=gitignore,
                node_modules=node_modules,
            ),
            None,
        )

    key = (root, hidden, gitignore, node_modules, pattern)
    sc = _get_default_cache()
    entries, age = sc.get_or_scan(
        key,
        lambda: _glob_scanner(
            pattern, root, hidden=hidden, gitignore=gitignore, node_modules=node_modules
        ),
    )
    return (entries, age)


def cached_grep(
    pattern: str,
    root: str = ".",
    hidden: bool = False,
    gitignore: bool = True,
    node_modules: bool = True,
    cache: bool = False,
) -> tuple[list[GlobMatch], float | None]:
    """Grep with optional scan caching.

    Returns:
        ``(entries, cache_age_ms)`` — *cache_age_ms* is ``None`` when
        *cache* is ``False``.
    """
    if not cache:
        return (
            _grep_scanner(
                pattern,
                root,
                hidden=hidden,
                gitignore=gitignore,
                node_modules=node_modules,
            ),
            None,
        )

    key = (root, hidden, gitignore, node_modules, pattern)
    sc = _get_default_cache()
    entries, age = sc.get_or_scan(
        key,
        lambda: _grep_scanner(
            pattern, root, hidden=hidden, gitignore=gitignore, node_modules=node_modules
        ),
    )
    return (entries, age)


def cached_find(
    name: str,
    root: str = ".",
    hidden: bool = False,
    gitignore: bool = True,
    node_modules: bool = True,
    cache: bool = False,
) -> tuple[list[GlobMatch], float | None]:
    """Filename search with optional scan caching.

    Returns:
        ``(entries, cache_age_ms)`` — *cache_age_ms* is ``None`` when
        *cache* is ``False``.
    """
    if not cache:
        return (
            _find_scanner(
                name,
                root,
                hidden=hidden,
                gitignore=gitignore,
                node_modules=node_modules,
            ),
            None,
        )

    key = (root, hidden, gitignore, node_modules, name)
    sc = _get_default_cache()
    entries, age = sc.get_or_scan(
        key,
        lambda: _find_scanner(
            name, root, hidden=hidden, gitignore=gitignore, node_modules=node_modules
        ),
    )
    return (entries, age)
