"""UC Tool Registry - discovers and manages user-created tools.

This module provides the core registry that scans the user's UC directory,
loads tool metadata, extracts function signatures, and provides access
to enabled tools for the LLM.

Hardened to parse TOOL_META via AST before importing, and to skip
disabled or untrusted tools during scan.
"""

import ast
import importlib.util
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import ModuleType

from . import USER_UC_DIR
from .models import ToolMeta, UCToolInfo
from .safety import (
    UCApprovalStore,
    check_code_safety,
    is_path_within_uc_dir,
    validate_full_tool_name,
)

logger = logging.getLogger(__name__)


class UCRegistry:
    """Registry for discovering and managing UC tools.

    Scans the user's UC directory recursively, loading tool metadata
    and providing access to enabled tools. Supports namespacing via
    subdirectories (e.g., api/weather.py → "api.weather").
    """

    def __init__(self, tools_dir: Path | None = None):
        """Initialize the registry.

        Args:
            tools_dir: Directory to scan for tools. Defaults to USER_UC_DIR.
        """
        self._tools_dir = tools_dir or USER_UC_DIR
        self._tools: dict[str, UCToolInfo] = {}
        self._modules: dict[str, ModuleType] = {}
        self._last_scan: datetime | None = None

    def ensure_tools_dir(self) -> Path:
        """Ensure the tools directory exists.

        Returns:
            Path to the tools directory.
        """
        self._tools_dir.mkdir(parents=True, exist_ok=True)
        return self._tools_dir

    def scan(self) -> int:
        """Scan the tools directory and load all tools.

        Returns:
            Number of tools found.
        """
        self._tools.clear()
        self._modules.clear()

        if not self._tools_dir.exists():
            logger.debug(f"Tools directory does not exist: {self._tools_dir}")
            return 0

        # Find all Python files recursively
        tool_files = list(self._tools_dir.rglob("*.py"))

        for tool_file in tool_files:
            # Skip __init__.py and hidden files
            if tool_file.name.startswith("_") or tool_file.name.startswith("."):
                continue

            try:
                tool_info = self._load_tool_file(tool_file)
                if tool_info:
                    self._tools[tool_info.full_name] = tool_info
                    logger.debug(f"Loaded tool: {tool_info.full_name}")
            except Exception as e:
                logger.warning(f"Failed to load tool from {tool_file}: {e}")

        self._last_scan = datetime.now()
        logger.info(f"Scanned {len(self._tools)} tools from {self._tools_dir}")
        return len(self._tools)

    def _load_tool_file(self, file_path: Path) -> UCToolInfo | None:
        """Load a tool from a Python file.

        Hardened flow:
        1. Parse TOOL_META via AST before importing the module.
        2. Validate tool name for path traversal / reserved names.
        3. Skip disabled tools (no import needed).
        4. For enabled tools with dangerous code, require approval.
        5. Only import if the tool passes safety and trust checks.

        Args:
            file_path: Path to the Python file.

        Returns:
            UCToolInfo if valid tool, None otherwise.
        """
        # Safety: file must be within tools directory
        if not is_path_within_uc_dir(file_path, self._tools_dir):
            logger.warning(f"Tool file outside UC directory: {file_path}")
            return None

        # Calculate namespace from relative path
        try:
            rel_path = file_path.relative_to(self._tools_dir)
            namespace_parts = list(rel_path.parent.parts)
            namespace = ".".join(namespace_parts) if namespace_parts else ""
        except ValueError:
            namespace = ""

        # Step 1: Parse TOOL_META via AST without importing
        try:
            code = file_path.read_text(encoding="utf-8")
            tree = ast.parse(code)
        except (SyntaxError, OSError) as e:
            logger.warning(f"Cannot parse {file_path}: {e}")
            return None

        raw_meta = self._extract_tool_meta_from_ast(tree)
        if raw_meta is None:
            logger.debug(f"No TOOL_META found in {file_path}")
            return None
        if not isinstance(raw_meta, dict):
            logger.warning(f"TOOL_META is not a dict in {file_path}")
            return None

        # Set namespace from directory structure
        raw_meta["namespace"] = namespace

        # Parse metadata
        try:
            meta = ToolMeta(**raw_meta)
        except Exception as e:
            logger.warning(f"Invalid TOOL_META in {file_path}: {e}")
            return None

        # Validate tool name
        full_name = f"{namespace}.{meta.name}" if namespace else meta.name
        name_error = validate_full_tool_name(full_name)
        if name_error:
            logger.warning(f"Invalid tool name '{full_name}': {name_error}")
            return None

        # Step 2: Skip disabled tools without importing
        if not meta.enabled:
            return UCToolInfo(
                meta=meta,
                signature=f"{meta.name}(...)",
                source_path=str(file_path),
                function_name=meta.name,
                docstring=None,
            )

        # Step 3: Safety check for enabled tools
        safety = check_code_safety(code)
        if safety.blocked:
            logger.warning(
                f"Tool '{full_name}' blocked by safety check: {safety.errors}"
            )
            return UCToolInfo(
                meta=meta,
                signature=f"{meta.name}(...)",
                source_path=str(file_path),
                function_name=meta.name,
                docstring=None,
            )

        if safety.requires_approval:
            approval_store = UCApprovalStore()
            if not approval_store.is_approved(full_name, safety.code_hash):
                logger.warning(
                    f"Tool '{full_name}' requires approval (dangerous patterns). "
                    f"Run /approve-uc {full_name} to enable."
                )
                return UCToolInfo(
                    meta=meta,
                    signature=f"{meta.name}(...)",
                    source_path=str(file_path),
                    function_name=meta.name,
                    docstring=None,
                )

        # Step 4: Extract metadata from AST without importing
        func_def = self._extract_function_def(tree, meta.name)
        if func_def is None:
            logger.warning(f"No callable function found in {file_path}")
            return None

        signature_str = self._extract_signature_from_ast(func_def)

        # Extract docstring from AST (first constant expression in function body)
        docstring = None
        if (
            func_def.body
            and isinstance(func_def.body[0], ast.Expr)
            and isinstance(func_def.body[0].value, ast.Constant)
            and isinstance(func_def.body[0].value.value, str)
        ):
            docstring = func_def.body[0].value.value

        # Module loading is deferred to runtime (runner.py handles it on invocation)
        # to avoid executing arbitrary code at scan time

        return UCToolInfo(
            meta=meta,
            signature=signature_str,
            source_path=str(file_path),
            function_name=func_def.name,
            docstring=docstring,
        )

    @staticmethod
    def _extract_tool_meta_from_ast(tree: ast.AST) -> dict | None:
        """Extract TOOL_META dict from an AST without executing code."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "TOOL_META"
                        and isinstance(node.value, ast.Dict)
                    ):
                        try:
                            meta_str = ast.unparse(node.value)
                            return ast.literal_eval(meta_str)
                        except (ValueError, SyntaxError):
                            return None
        return None

    @staticmethod
    def _extract_function_def(tree: ast.AST, tool_name: str) -> ast.FunctionDef | None:
        """Find the function definition for a tool by name in the AST.

        Searches for function definitions with the given name.
        Falls back to 'run', 'execute', or the first public function.
        """
        candidates = [tool_name, "run", "execute"]
        functions: list[ast.FunctionDef] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node)

        # Try candidates in priority order
        for name in candidates:
            for fn in functions:
                if fn.name == name:
                    return fn

        # Fall back to first public function
        for fn in functions:
            if not fn.name.startswith("_"):
                return fn

        return None

    @staticmethod
    def _extract_signature_from_ast(func_def: ast.FunctionDef) -> str:
        """Extract a signature string from an AST function definition."""
        args = func_def.args
        parts = [func_def.name, "("]

        params = []
        # Positional args
        for i, arg in enumerate(args.args):
            # Check if we're past the positional-only separator
            if args.posonlyargs and i >= len(args.posonlyargs):
                pass
            param = arg.arg
            if arg.annotation:
                param += f": {ast.unparse(arg.annotation)}"
            if args.defaults and i >= len(args.args) - len(args.defaults):
                default_idx = i - (len(args.args) - len(args.defaults))
                param += f"={ast.unparse(args.defaults[default_idx])}"
            params.append(param)

        # *args
        if args.vararg:
            param = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                param += f": {ast.unparse(args.vararg.annotation)}"
            params.append(param)

        # Keyword-only args
        for i, arg in enumerate(args.kwonlyargs):
            param = arg.arg
            if arg.annotation:
                param += f": {ast.unparse(arg.annotation)}"
            if (
                args.kw_defaults
                and i < len(args.kw_defaults)
                and args.kw_defaults[i] is not None
            ):
                param += f"={ast.unparse(args.kw_defaults[i])}"
            params.append(param)

        # **kwargs
        if args.kwarg:
            param = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                param += f": {ast.unparse(args.kwarg.annotation)}"
            params.append(param)

        parts.append(", ".join(params))
        parts.append(")")

        # Return annotation
        if func_def.returns:
            parts.append(f" -> {ast.unparse(func_def.returns)}")

        return "".join(parts)

    def _load_module(self, file_path: Path) -> ModuleType | None:
        """Load a Python module from a file path.

        Args:
            file_path: Path to the Python file.

        Returns:
            Loaded module or None if failed.
        """
        module_name = f"uc_tool_{file_path.stem}_{hash(str(file_path))}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception:
            return None

    def _find_tool_function(
        self, module: ModuleType, tool_name: str
    ) -> tuple[Callable | None, str]:
        """Find the callable function in a tool module.

        Looks for:
        1. A function with the same name as the tool
        2. A function named 'run'
        3. A function named 'execute'
        4. Any public function (not starting with _)

        Args:
            module: The loaded module.
            tool_name: The tool name from metadata.

        Returns:
            Tuple of (function, function_name) or (None, "") if not found.
        """
        # Priority order for finding the function
        candidates = [tool_name, "run", "execute"]

        for name in candidates:
            if hasattr(module, name):
                func = getattr(module, name)
                if callable(func) and not isinstance(func, type):
                    return func, name

        # Fall back to first public callable
        for name in dir(module):
            if name.startswith("_"):
                continue
            obj = getattr(module, name)
            if callable(obj) and not isinstance(obj, type):
                return obj, name

        return None, ""

    def list_tools(self, include_disabled: bool = False) -> list[UCToolInfo]:
        """List all discovered tools.

        Args:
            include_disabled: Whether to include disabled tools.

        Returns:
            List of tool info objects.
        """
        if not self._tools:
            self.scan()

        tools = list(self._tools.values())
        if not include_disabled:
            tools = [t for t in tools if t.meta.enabled]

        return sorted(tools, key=lambda t: t.full_name)

    def get_tool(self, name: str) -> UCToolInfo | None:
        """Get a specific tool by name.

        Args:
            name: Full tool name (including namespace).

        Returns:
            Tool info or None if not found.
        """
        if not self._tools:
            self.scan()

        return self._tools.get(name)

    def get_tool_function(self, name: str) -> Callable | None:
        """Get the callable function for a tool.

        Args:
            name: Full tool name (including namespace).

        Returns:
            Callable function or None if not found.
        """
        tool = self.get_tool(name)
        if tool is None:
            return None

        # Do not load disabled, blocked, or unapproved tools
        if tool.signature == f"{tool.meta.name}(...)":
            return None

        module = self._modules.get(name)
        if module is None:
            # Defer module loading to runtime to avoid executing code at scan time
            module = self._load_module(Path(tool.source_path))
            if module is None:
                return None
            self._modules[name] = module

        func, _ = self._find_tool_function(module, tool.meta.name)
        return func

    def load_tool_module(self, name: str) -> ModuleType | None:
        """Get the loaded module for a tool.

        Args:
            name: Full tool name (including namespace).

        Returns:
            Module or None if not found.
        """
        if not self._tools:
            self.scan()

        tool = self._tools.get(name)
        if tool is None:
            return None

        # Do not load disabled, blocked, or unapproved tools
        if tool.signature == f"{tool.meta.name}(...)":
            return None

        module = self._modules.get(name)
        if module is None:
            module = self._load_module(Path(tool.source_path))
            if module is None:
                return None
            self._modules[name] = module

        return module

    def reload(self) -> int:
        """Force a rescan of all tools.

        Returns:
            Number of tools found.
        """
        return self.scan()


# Global registry instance
_registry: UCRegistry | None = None


def get_registry() -> UCRegistry:
    """Get the global UC registry instance.

    Returns:
        The global UCRegistry instance.
    """
    global _registry
    if _registry is None:
        _registry = UCRegistry()
    return _registry
