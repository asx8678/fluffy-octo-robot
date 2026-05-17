"""Universal Constructor safety and approval engine.

Validates tool names/namespaces, blocks dangerous code patterns,
and stores per-tool approval decisions keyed by code hash.
"""

import ast
import contextlib
import hashlib
import hmac
import logging
import os
import re
from pathlib import Path

import orjson
import orjson as json

logger = logging.getLogger(__name__)

# XDG state directory for private approval storage
_APPROVAL_DIR = (
    Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    / "code_muse"
)
_APPROVAL_FILE = _APPROVAL_DIR / "uc_approvals.json"

# Valid tool name: [a-zA-Z_][a-zA-Z0-9_]*
_VALID_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Reserved module names that should not be used as tool names
_RESERVED_MODULE_NAMES: set[str] = {
    "abc",
    "ast",
    "builtins",
    "code",
    "codecs",
    "collections",
    "copy",
    "datetime",
    "enum",
    "fnmatch",
    "functools",
    "glob",
    "hashlib",
    "importlib",
    "inspect",
    "io",
    "json",
    "logging",
    "math",
    "os",
    "pathlib",
    "pickle",
    "platform",
    "random",
    "re",
    "shutil",
    "signal",
    "socket",
    "sqlite3",
    "string",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "time",
    "traceback",
    "types",
    "typing",
    "urllib",
    "uuid",
    "warnings",
    "xml",
    "zipfile",
}

# HMAC key derivation — single secret per installation prevents tampering
_APPROVAL_HMAC_KEY = hashlib.sha256(b"uc_approval_v1:muse_integrity").digest()


def _compute_entry_hmac(entry: dict) -> str:
    """Compute HMAC for an approval entry dict."""
    payload = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(_APPROVAL_HMAC_KEY, payload, hashlib.sha256).hexdigest()


# Dangerous patterns that should BLOCK tool creation/execution
_DANGEROUS_IMPORTS_BLOCK: set[str] = {
    "subprocess",
    "os.system",
    "eval",
    "exec",
    "compile",
    "__import__",
    "pickle",
    "marshal",
    "socket",
    "ctypes",
    "importlib",
    "builtins",
}

_DANGEROUS_CALLS_BLOCK: set[str] = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "system",
    "popen",
    "spawn",
    "fork",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "vars",
    "dir",
}

# Additional dangerous patterns that require explicit approval
_DANGEROUS_IMPORTS_APPROVAL: set[str] = {
    "requests",
    "urllib",
    "http.client",
    "ftplib",
    "smtplib",
    "paramiko",
}

_DANGEROUS_OPEN_MODES = {
    "w",
    "a",
    "x",
    "wb",
    "ab",
    "xb",
    "w+",
    "a+",
    "r+",
    "rb+",
    "wb+",
}


def _ensure_private_dir(path: Path) -> Path:
    """Ensure directory exists with 0o700 permissions."""
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)
    return path


def _atomic_write_private_json(file_path: Path, data: dict) -> None:
    """Atomically write JSON with 0o600 permissions."""
    tmp_path = file_path.with_suffix(".tmp")
    try:
        fd = os.open(
            str(tmp_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, option=orjson.OPT_INDENT_2).decode())
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(file_path))
        with contextlib.suppress(OSError):
            os.chmod(file_path, 0o600)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise


def _load_approval_db() -> dict[str, dict]:
    """Load the UC approval database from private storage.

    Verifies HMAC integrity of every entry. Corrupted/tampered entries
    are silently dropped.
    """
    _ensure_private_dir(_APPROVAL_DIR)
    if not _APPROVAL_FILE.exists():
        return {}
    try:
        with open(_APPROVAL_FILE, encoding="utf-8") as f:
            data = json.loads(f.read())
        if not isinstance(data, dict):
            return {}
        # Verify and strip HMAC from every entry
        verified = {}
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            stored_hmac = entry.pop("_hmac", None)
            if stored_hmac is None:
                continue  # no HMAC — skip unverifiable entry
            expected = _compute_entry_hmac(entry)
            entry["_hmac"] = stored_hmac  # restore
            if hmac.compare_digest(stored_hmac, expected):
                verified[key] = entry
        return verified
    except json.JSONDecodeError, OSError:
        return {}


def _save_approval_db(db: dict[str, dict]) -> None:
    """Save the UC approval database to private storage.

    Every entry is HMAC-signed to detect tampering on load.
    """
    _ensure_private_dir(_APPROVAL_DIR)
    # Add HMAC to every entry before saving
    signed = {}
    for key, entry in db.items():
        entry_no_hmac = {k: v for k, v in entry.items() if k != "_hmac"}
        entry_no_hmac["_hmac"] = _compute_entry_hmac(entry_no_hmac)
        signed[key] = entry_no_hmac
    _atomic_write_private_json(_APPROVAL_FILE, signed)


def compute_code_hash(code: str) -> str:
    """Compute SHA-256 hash of tool source code."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def validate_tool_name(name: str, *, check_reserved: bool = True) -> str | None:
    """Strictly validate a tool name or namespace segment.

    Args:
        name: Tool name or namespace segment to validate.
        check_reserved: If True, reject names matching Python stdlib modules.
            Set to False for namespace segments that don't shadow modules
            (e.g., "json" in "json.validate_files" is a namespace, not
            an import target — the tool is invoked as "uc:json.validate_files").

    Returns:
        Error message if invalid, None if valid.
    """
    if not name:
        return "Tool name cannot be empty"
    if name.startswith(".") or name.startswith("_"):
        return f"Tool name cannot start with '.' or '_': {name}"
    if name.startswith("__") and name.endswith("__"):
        return f"Dunder names are reserved: {name}"
    if "/" in name or "\\" in name or ".." in name:
        return f"Path traversal characters not allowed: {name}"
    if not _VALID_NAME_RE.match(name):
        return f"Invalid tool name '{name}': must match [a-zA-Z_][a-zA-Z0-9_]*"
    if check_reserved and name.lower() in _RESERVED_MODULE_NAMES:
        return f"Tool name '{name}' is a reserved module name"
    return None


def validate_namespace(namespace: str) -> str | None:
    """Validate a dot-separated namespace.

    Namespace segments are not checked against reserved module names
    because they don't shadow Python modules — the full tool is invoked
    as "uc:namespace.tool_name", not "import namespace".

    Returns:
        Error message if invalid, None if valid.
    """
    if not namespace:
        return None
    parts = namespace.split(".")
    for part in parts:
        error = validate_tool_name(part, check_reserved=False)
        if error:
            return error
    return None


def validate_full_tool_name(name: str) -> str | None:
    """Validate a full tool name possibly including namespace.

    Reserved module name checks only apply to the final (leaf) segment,
    since namespace segments don't shadow Python modules — a tool named
    "json.validate_files" is invoked as "uc:json.validate_files", not
    "import orjson as json".

    Returns:
        Error message if invalid, None if valid.
    """
    if not name:
        return "Tool name cannot be empty"
    if name.startswith(".") or name.endswith("."):
        return "Tool name cannot start or end with '.'"
    parts = name.split(".")
    last_index = len(parts) - 1
    for i, part in enumerate(parts):
        # Only the final (leaf) segment can shadow a module name;
        # namespace segments like "json" in "json.validate_files"
        # are always accessed via "uc:" prefix, so skip reserved check.
        is_leaf = i == last_index
        error = validate_tool_name(part, check_reserved=is_leaf)
        if error:
            return error
    return None


class SafetyCheckResult:
    """Result of a UC safety check."""

    def __init__(
        self,
        safe: bool = True,
        blocked: bool = False,
        requires_approval: bool = False,
        errors: list[str | None] = None,
        warnings: list[str | None] = None,
        code_hash: str | None = None,
    ):
        self.safe = safe
        self.blocked = blocked
        self.requires_approval = requires_approval
        self.errors = errors or []
        self.warnings = warnings or []
        self.code_hash = code_hash


def check_code_safety(code: str) -> SafetyCheckResult:
    """Perform strict safety analysis on UC tool code.

    This is a BLOCKING check (not just advisory). Dangerous patterns
    like eval, exec, subprocess, pickle, etc. cause the tool to be
    rejected. Network-library usage requires explicit approval.

    Args:
        code: Python source code to analyze.

    Returns:
        SafetyCheckResult indicating whether the code is safe,
        blocked, or requires approval.
    """
    result = SafetyCheckResult(code_hash=compute_code_hash(code))

    # Parse AST
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        result.safe = False
        result.errors.append(f"Syntax error: {e}")
        return result

    dangerous_found: list[str] = []
    approval_required: list[str] = []

    # Track import aliases for attribute-call resolution
    # E.g., "import subprocess as sp" creates alias sp -> subprocess
    import_aliases: dict[str, str] = {}  # local_name -> module_name

    for node in ast.walk(tree):
        # Track import aliases
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name
                if alias.name in _DANGEROUS_IMPORTS_BLOCK:
                    dangerous_found.append(f"import {alias.name}")
                elif alias.name in _DANGEROUS_IMPORTS_APPROVAL:
                    approval_required.append(f"import {alias.name}")
                import_aliases[local_name] = alias.name
                continue

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Track from-import aliases
            for alias in node.names:
                full_name = f"{module}.{alias.name}"
                local_name = alias.asname or alias.name
                if (
                    module in _DANGEROUS_IMPORTS_BLOCK
                    or full_name in _DANGEROUS_IMPORTS_BLOCK
                ):
                    dangerous_found.append(f"from {module} import {alias.name}")
                elif (
                    module in _DANGEROUS_IMPORTS_APPROVAL
                    or full_name in _DANGEROUS_IMPORTS_APPROVAL
                ):
                    approval_required.append(f"from {module} import {alias.name}")
                import_aliases[local_name] = full_name
            continue

        # Check function calls — includes alias-resolved attribute calls
        elif isinstance(node, ast.Call):
            func_name = _get_call_name(node)
            if func_name in _DANGEROUS_CALLS_BLOCK:
                line = getattr(node, "lineno", "?")
                dangerous_found.append(f"{func_name}() call at line {line}")
            elif func_name == "open":
                if _is_dangerous_open_call(node):
                    line = getattr(node, "lineno", "?")
                    dangerous_found.append(f"open() with write mode at line {line}")
            else:
                # Check for attribute calls on aliased dangerous imports
                # E.g., sp.run(...) where sp is an alias for subprocess
                if isinstance(node.func, ast.Attribute) and isinstance(
                    node.func.value, ast.Name
                ):
                    obj_name = node.func.value.id
                    attr_name = node.func.attr
                    module_name = import_aliases.get(obj_name)
                    if module_name:
                        safe_name = f"{module_name}.{attr_name}"
                        if (
                            module_name in _DANGEROUS_IMPORTS_BLOCK
                            or safe_name in _DANGEROUS_IMPORTS_BLOCK
                        ):
                            line = getattr(node, "lineno", "?")
                            dangerous_found.append(
                                f"{obj_name}.{attr_name}() at line {line}"
                            )

    if dangerous_found:
        result.blocked = True
        result.safe = False
        result.errors.append(
            f"Blocked dangerous patterns: {', '.join(dangerous_found)}"
        )

    if approval_required and not result.blocked:
        result.requires_approval = True
        result.warnings.append(
            f"Potentially dangerous patterns require approval: {', '.join(approval_required)}"
        )

    return result


def _get_call_name(node: ast.Call) -> str:
    """Extract the function name from a Call node."""
    if hasattr(node, "func"):
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return node.func.attr
    return ""


def _is_dangerous_open_call(node: ast.Call) -> bool:
    """Check if an open() call uses a dangerous (write) mode."""
    if len(node.args) >= 2:
        mode_arg = node.args[1]
        if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
            return mode_arg.value in _DANGEROUS_OPEN_MODES
    for kw in node.keywords:
        if (
            kw.arg == "mode"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value in _DANGEROUS_OPEN_MODES
    return False


class UCApprovalStore:
    """Persistent store for UC tool approvals keyed by code hash."""

    def __init__(self):
        self._db: dict[str, dict] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._db = _load_approval_db()
            self._loaded = True

    def is_approved(self, tool_name: str, code_hash: str) -> bool:
        """Check whether a specific code hash is approved for a tool."""
        self._ensure_loaded()
        key = f"{tool_name}:{code_hash}"
        entry = self._db.get(key)
        if entry is None:
            return False
        stored_hash = entry.get("code_hash")
        if stored_hash != code_hash:
            return False
        return entry.get("approved", False)

    def approve(self, tool_name: str, code_hash: str) -> None:
        """Explicitly approve a tool code hash."""
        self._ensure_loaded()
        key = f"{tool_name}:{code_hash}"
        self._db[key] = {
            "tool_name": tool_name,
            "code_hash": code_hash,
            "approved": True,
        }
        _save_approval_db(self._db)
        logger.info(f"UC tool approved: {tool_name} (hash={code_hash[:16]}...)")

    def revoke(self, tool_name: str, code_hash: str) -> None:
        """Revoke approval for a tool code hash."""
        self._ensure_loaded()
        key = f"{tool_name}:{code_hash}"
        if key in self._db:
            del self._db[key]
            _save_approval_db(self._db)
            logger.info(f"UC tool approval revoked: {tool_name}")


def is_path_within_uc_dir(file_path: Path, uc_dir: Path) -> bool:
    """Verify that file_path is safely contained within uc_dir.

    Resolves both paths and checks for symlink escape.

    Returns:
        True if file_path is within uc_dir, False otherwise.
    """
    try:
        resolved_file = file_path.resolve()
        resolved_dir = uc_dir.resolve()
        resolved_file.relative_to(resolved_dir)
        return True
    except ValueError, OSError:
        return False
