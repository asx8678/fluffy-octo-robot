# file_operations.py

import contextlib
import os
import shutil
import stat
import subprocess
import tempfile
from collections import deque
from pathlib import Path

from pydantic import BaseModel, conint
from pydantic_ai import RunContext

from code_muse.agents._history import estimate_tokens

# ---------------------------------------------------------------------------
# Module-level helper functions (exposed for unit tests _and_ used as tools)
# ---------------------------------------------------------------------------
from code_muse.messaging import (  # New structured messaging types
    FileContentMessage,
    FileEntry,
    FileListingMessage,
    GrepMatch,
    GrepResultMessage,
    get_message_bus,
)
from code_muse.tools.path_policy import Operation, check_path_allowed

# Caps for listing / reading to avoid unbounded memory and model-context blowup
MAX_LIST_FILES_UI_ENTRIES = 5_000
MAX_LIST_FILES_LLM_ENTRIES = 1_000
MAX_READ_FILE_BYTES = 128_000
MAX_GREP_MATCHES = 50
MAX_GREP_LINE_LENGTH = 512


# Pydantic models for tool return types
class ListedFile(BaseModel):
    path: str | None
    type: str | None
    size: int = 0
    full_path: str | None
    depth: int | None


class ListFileOutput(BaseModel):
    content: str
    error: str | None = None


class ReadFileOutput(BaseModel):
    content: str | None
    num_tokens: conint(lt=10000)
    error: str | None = None


class MatchInfo(BaseModel):
    file_path: str | None
    line_number: int | None
    line_content: str | None


class GrepOutput(BaseModel):
    matches: list[MatchInfo]
    error: str | None = None


def is_likely_home_directory(directory):
    """Detect if directory is likely a user's home directory or common home subdirectory"""
    abs_dir = Path(directory).resolve()
    home_dir = Path.home()

    # Exact home directory match
    if abs_dir == home_dir:
        return True

    # Check for common home directory subdirectories
    common_home_subdirs = {
        "Documents",
        "Desktop",
        "Downloads",
        "Pictures",
        "Music",
        "Videos",
        "Movies",
        "Public",
        "Library",
        "Applications",  # Cover macOS/Linux
    }
    return bool(abs_dir.name in common_home_subdirs and abs_dir.parent == home_dir)


def is_project_directory(directory):
    """Quick heuristic to detect if this looks like a project directory"""
    project_indicators = {
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "CMakeLists.txt",
        ".git",
        "requirements.txt",
        "composer.json",
        "Gemfile",
        "go.mod",
        "Makefile",
        "setup.py",
    }

    try:
        contents = os.listdir(directory)
        return any(indicator in contents for indicator in project_indicators)
    except OSError:
        return False


def would_match_directory(pattern: str, directory: str) -> bool:
    """Check if a glob pattern would match the given directory path.

    This is used to avoid adding ignore patterns that would inadvertently
    exclude the directory we're actually trying to search in.

    Args:
        pattern: A glob pattern like '**/tmp/**' or 'node_modules'
        directory: The directory path to check against

    Returns:
        True if the pattern would match the directory, False otherwise
    """
    import fnmatch

    # Normalize the directory path
    abs_dir = Path(directory).resolve()
    dir_name = abs_dir.name

    # Strip leading/trailing wildcards and slashes for simpler matching
    clean_pattern = pattern.strip("*").strip("/")

    # Check if the directory name matches the pattern
    if fnmatch.fnmatch(dir_name, clean_pattern):
        return True

    # Check if the full path contains the pattern
    if fnmatch.fnmatch(abs_dir, pattern):
        return True

    # Check if any part of the path matches
    path_parts = str(abs_dir).split(os.sep)
    return any(fnmatch.fnmatch(part, clean_pattern) for part in path_parts)


def _list_files(
    context: RunContext, directory: str = ".", recursive: bool = True
) -> ListFileOutput:
    import sys

    directory = Path(directory).expanduser().resolve()

    # Enforce workspace / sensitive directory policy before listing
    policy = check_path_allowed(str(directory), Operation.LIST)
    if not policy.allowed:
        error_msg = policy.reason or "Directory listing blocked by path policy."
        return ListFileOutput(content=error_msg, error=error_msg)

    # Plain text output for LLM consumption
    output_lines = []
    output_lines.append(f"DIRECTORY LISTING: {directory} (recursive={recursive})")

    if not directory.exists():
        error_msg = f"Error: Directory '{directory}' does not exist"
        return ListFileOutput(content=error_msg, error=error_msg)
    if not directory.is_dir():
        error_msg = f"Error: '{directory}' is not a directory"
        return ListFileOutput(content=error_msg, error=error_msg)

    results = []

    # Smart home directory detection - auto-limit recursion for performance
    # But allow recursion in tests (when context=None) or when explicitly requested
    if context is not None and is_likely_home_directory(str(directory)) and recursive:
        if not is_project_directory(str(directory)):
            output_lines.append(
                "Warning: Detected home directory - limiting to non-recursive listing for performance"
            )
            recursive = False

    # Create a temporary ignore file with our ignore patterns
    ignore_file = None
    try:
        # Find ripgrep executable - first check system PATH, then virtual environment
        rg_path = shutil.which("rg")
        if not rg_path:
            # Try to find it in the virtual environment
            # Use sys.executable to determine the Python environment path
            python_dir = Path(sys.executable).parent
            # python_dir is already bin/ (Unix) or Scripts/ (Windows)
            for name in ["rg", "rg.exe"]:
                candidate = python_dir / name
                if candidate.exists():
                    rg_path = str(candidate)
                    break

        if not rg_path and recursive:
            # Only need ripgrep for recursive listings
            error_msg = "Error: ripgrep (rg) not found. Please install ripgrep to use this tool."
            return ListFileOutput(content=error_msg, error=error_msg)

        # Only use ripgrep for recursive listings
        if recursive:
            # Build command for ripgrep --files
            cmd = [rg_path, "--files"]

            # Add ignore patterns to the command via a temporary file
            from code_muse.tools.common import (
                DIR_IGNORE_PATTERNS,
            )

            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".ignore"
            ) as f:
                ignore_file = f.name
                for pattern in DIR_IGNORE_PATTERNS:
                    # Skip patterns that would match the search directory itself
                    # For example, if searching in /tmp/test-dir, skip **/tmp/**
                    if would_match_directory(pattern, directory):
                        continue
                    f.write(f"{pattern}\n")

            cmd.extend(["--ignore-file", ignore_file])
            cmd.append(str(directory))

            # Run ripgrep to get file listing
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # Process the output lines
            files = result.stdout.strip().split("\n") if result.stdout.strip() else []

            # Create ListedFile objects with metadata
            for full_path in files:
                if not full_path:  # Skip empty lines
                    continue

                fp = Path(full_path)
                # Skip if file doesn't exist (though it should)
                if not fp.exists():
                    continue

                # Extract relative path from the full path
                if full_path.startswith(str(directory)):
                    file_path = full_path[len(str(directory)) :].lstrip(os.sep)
                else:
                    file_path = full_path

                try:
                    st = fp.stat()
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode):
                    entry_type = "file"
                    size = st.st_size
                elif stat.S_ISDIR(st.st_mode):
                    entry_type = "directory"
                    size = 0
                else:
                    continue

                try:
                    # Calculate depth based on the relative path
                    depth = file_path.count(os.sep)

                    # Add directory entries if needed for files
                    if entry_type == "file":
                        p = Path(file_path).parent
                        dir_path = str(p) if p != Path(".") else ""
                        if dir_path:
                            # Add directory path components if they don't exist
                            path_parts = dir_path.split(os.sep)
                            seen_dirs: set[str] = set()
                            for i in range(len(path_parts)):
                                partial_path = os.sep.join(path_parts[: i + 1])
                                # Check if we already added this directory
                                if partial_path not in seen_dirs:
                                    results.append(
                                        ListedFile(
                                            path=partial_path,
                                            type="directory",
                                            size=0,
                                            full_path=str(directory / partial_path),
                                            depth=partial_path.count(os.sep),
                                        )
                                    )
                                    seen_dirs.add(partial_path)

                    # Add the entry (file or directory)
                    results.append(
                        ListedFile(
                            path=file_path,
                            type=entry_type,
                            size=size,
                            full_path=full_path,
                            depth=depth,
                        )
                    )
                except OSError:
                    # Skip files we can't access
                    continue

        # In non-recursive mode, we also need to explicitly list immediate entries
        # ripgrep's --files option only returns files; we add directories and files ourselves
        if not recursive:
            try:
                entries = os.listdir(directory)
                for entry in sorted(entries):
                    full_entry_path = directory / entry
                    if not full_entry_path.exists():
                        continue

                    if full_entry_path.is_dir():
                        # In non-recursive mode, only skip obviously system/hidden directories
                        # Don't use the full should_ignore_dir_path which is too aggressive
                        if entry.startswith("."):
                            continue
                        results.append(
                            ListedFile(
                                path=entry,
                                type="directory",
                                size=0,
                                full_path=str(full_entry_path),
                                depth=0,
                            )
                        )
                    elif full_entry_path.is_file():
                        # Include top-level files (including binaries)
                        try:
                            size = full_entry_path.stat().st_size
                        except OSError:
                            size = 0
                        results.append(
                            ListedFile(
                                path=entry,
                                type="file",
                                size=size,
                                full_path=str(full_entry_path),
                                depth=0,
                            )
                        )
            except OSError:
                # Skip entries we can't access
                pass
    except subprocess.TimeoutExpired:
        error_msg = "Error: List files command timed out after 30 seconds"
        return ListFileOutput(content=error_msg, error=error_msg)
    except Exception as e:
        error_msg = f"Error: Error during list files operation: {e}"
        return ListFileOutput(content=error_msg, error=error_msg)
    finally:
        # Clean up the temporary ignore file
        if ignore_file and Path(ignore_file).exists():
            os.unlink(ignore_file)

    def format_size(size_bytes):
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def get_file_icon(file_path):
        ext = Path(file_path).suffix.lower()
        if ext in [".py", ".pyw"]:
            return "\U0001f40d"
        elif ext in [".js", ".jsx", ".ts", ".tsx"]:
            return "\U0001f4dc"
        elif ext in [".html", ".htm", ".xml"]:
            return "\U0001f310"
        elif ext in [".css", ".scss", ".sass"]:
            return "\U0001f3a8"
        elif ext in [".md", ".markdown", ".rst"]:
            return "\U0001f4dd"
        elif ext in [".json", ".yaml", ".yml", ".toml"]:
            return "\u2699\ufe0f"
        elif ext in [".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"]:
            return "\U0001f5bc\ufe0f"
        elif ext in [".mp3", ".wav", ".ogg", ".flac"]:
            return "\U0001f3b5"
        elif ext in [".mp4", ".avi", ".mov", ".webm"]:
            return "\U0001f3ac"
        elif ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"]:
            return "\U0001f4c4"
        elif ext in [".zip", ".tar", ".gz", ".rar", ".7z"]:
            return "\U0001f4e6"
        elif ext in [".exe", ".dll", ".so", ".dylib"]:
            return "\u26a1"
        else:
            return "\U0001f4c4"

    # Count items in results
    dir_count = sum(1 for item in results if item.type == "directory")
    file_count = sum(1 for item in results if item.type == "file")
    total_size = sum(item.size for item in results if item.type == "file")

    # Build structured FileEntry objects for the UI
    file_entries = []

    def _sort_key(item):
        """Sort by path components to keep children grouped under parents.

        Splitting on os.sep ensures 'src/foo' always sorts right after 'src'
        rather than letting 'src-tauri' (with '-' < '/') slip in between.
        Directories sort before files at the same level.
        """
        parts = item.path.split(os.sep)
        return (parts, item.type != "directory")

    sorted_results = sorted(results, key=_sort_key)

    for item in sorted_results:
        if item.type == "directory" and not item.path:
            continue
        file_entries.append(
            FileEntry(
                path=item.path,
                type="dir" if item.type == "directory" else "file",
                size=item.size,
                depth=item.depth or 0,
            )
        )

    # Cap UI structured entries
    ui_truncated = False
    if len(file_entries) > MAX_LIST_FILES_UI_ENTRIES:
        file_entries = file_entries[:MAX_LIST_FILES_UI_ENTRIES]
        ui_truncated = True

    # Emit structured message for the UI
    file_listing_msg = FileListingMessage(
        directory=str(directory),
        files=file_entries,
        recursive=recursive,
        total_size=total_size,
        dir_count=dir_count,
        file_count=file_count,
    )
    get_message_bus().emit(file_listing_msg)

    # Build plain text output for LLM consumption
    llm_lines: list[str] = []
    for item in sorted_results:
        if item.type == "directory" and not item.path:
            continue
        name = Path(item.path).name or item.path
        indent = "  " * (item.depth or 0)
        if item.type == "directory":
            llm_lines.append(f"{indent}{name}/")
        else:
            size_str = format_size(item.size)
            llm_lines.append(f"{indent}{name} ({size_str})")

    llm_truncated = False
    if len(llm_lines) > MAX_LIST_FILES_LLM_ENTRIES:
        llm_lines = llm_lines[:MAX_LIST_FILES_LLM_ENTRIES]
        llm_truncated = True

    output_lines.extend(llm_lines)

    # Add summary
    output_lines.append(
        f"\nSummary: {dir_count} directories, {file_count} files ({format_size(total_size)} total)"
    )
    if ui_truncated or llm_truncated:
        output_lines.append(
            f"\n[Truncated: shown {MAX_LIST_FILES_LLM_ENTRIES} of {len(sorted_results)} entries]"
        )

    return ListFileOutput(content="\n".join(output_lines))


def _read_file(
    context: RunContext,
    file_path: str,
    start_line: int | None = None,
    num_lines: int | None = None,
) -> ReadFileOutput:
    file_path = Path(file_path).expanduser().resolve()

    # Enforce path policy before reading
    policy = check_path_allowed(str(file_path), Operation.READ)
    if not policy.allowed:
        error_msg = policy.reason or "File read blocked by path policy."
        return ReadFileOutput(content=error_msg, num_tokens=0, error=error_msg)

    if not file_path.exists():
        error_msg = f"File {file_path} does not exist"
        return ReadFileOutput(content=error_msg, num_tokens=0, error=error_msg)
    if not file_path.is_file():
        error_msg = f"{file_path} is not a file"
        return ReadFileOutput(content=error_msg, num_tokens=0, error=error_msg)

    # Huge-file gate: reject full reads of files larger than cap unless chunked
    try:
        file_size = file_path.stat().st_size
    except OSError:
        file_size = 0
    if start_line is None and num_lines is None and file_size > MAX_READ_FILE_BYTES:
        return ReadFileOutput(
            content=None,
            error=(
                f"File is too large ({file_size} bytes > {MAX_READ_FILE_BYTES} bytes). "
                "Please read this file in chunks using start_line and num_lines."
            ),
            num_tokens=0,
        )

    try:
        # Use errors="surrogateescape" to handle files with invalid UTF-8 sequences
        # This is common on Windows when files contain emojis or were created by
        # applications that don't properly encode Unicode
        with open(file_path, encoding="utf-8", errors="surrogateescape") as f:
            if start_line is not None and start_line < 1:
                error_msg = "start_line must be >= 1 (1-based indexing)"
                return ReadFileOutput(content=error_msg, num_tokens=0, error=error_msg)
            if num_lines is not None and num_lines < 1:
                error_msg = "num_lines must be >= 1"
                return ReadFileOutput(content=error_msg, num_tokens=0, error=error_msg)
            if start_line is not None and num_lines is not None:
                # Read only the specified lines efficiently using itertools.islice
                # to avoid loading the entire file into memory
                import itertools

                start_idx = start_line - 1
                selected_lines = list(
                    itertools.islice(f, start_idx, start_idx + num_lines)
                )
                content = "".join(selected_lines)
            else:
                # Read the entire file
                content = f.read()

            # Sanitize the content to remove any surrogate characters that could
            # cause issues when the content is later serialized or displayed
            # This re-encodes with surrogatepass then decodes with replace to
            # convert lone surrogates to replacement characters
            try:
                content = content.encode("utf-8", errors="surrogatepass").decode(
                    "utf-8", errors="replace"
                )
            except (UnicodeEncodeError, UnicodeDecodeError):
                # If that fails, do a more aggressive cleanup
                content = "".join(
                    char if ord(char) < 0xD800 or ord(char) > 0xDFFF else "\ufffd"
                    for char in content
                )

            # Simple approximation using canonical estimator (~3 chars/token)
            num_tokens = estimate_tokens(content)
            if num_tokens > 10000:
                return ReadFileOutput(
                    content=None,
                    error="The file is massive, greater than 10,000 tokens which is dangerous to read entirely. Please read this file in chunks.",
                    num_tokens=0,
                )

            # Count total lines for the message
            total_lines = content.count("\n") + (
                1 if content and not content.endswith("\n") else 0
            )

            # Emit structured message for the UI
            # Only include start_line/num_lines if they are valid positive integers
            emit_start_line = (
                start_line if start_line is not None and start_line >= 1 else None
            )
            emit_num_lines = (
                num_lines if num_lines is not None and num_lines >= 1 else None
            )
            file_content_msg = FileContentMessage(
                path=str(file_path),
                content=content,
                start_line=emit_start_line,
                num_lines=emit_num_lines,
                total_lines=total_lines,
                num_tokens=num_tokens,
            )
            get_message_bus().emit(file_content_msg)

        return ReadFileOutput(content=content, num_tokens=num_tokens)
    except FileNotFoundError:
        error_msg = "FILE NOT FOUND"
        return ReadFileOutput(content=error_msg, num_tokens=0, error=error_msg)
    except PermissionError:
        error_msg = "PERMISSION DENIED"
        return ReadFileOutput(content=error_msg, num_tokens=0, error=error_msg)
    except Exception as e:
        message = f"An error occurred trying to read the file: {e}"
        return ReadFileOutput(content=message, num_tokens=0, error=message)


def _sanitize_string(text: str) -> str:
    """Sanitize a string to remove invalid Unicode surrogates.

    This handles encoding issues common on Windows with copy-paste operations.
    """
    if not text:
        return text
    try:
        # Try encoding - if it works, string is clean
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        pass

    try:
        # Encode allowing surrogates, then decode replacing them
        return text.encode("utf-8", errors="surrogatepass").decode(
            "utf-8", errors="replace"
        )
    except (UnicodeEncodeError, UnicodeDecodeError):
        # Last resort: filter out surrogate characters
        return "".join(
            char if ord(char) < 0xD800 or ord(char) > 0xDFFF else "\ufffd"
            for char in text
        )


def _grep(context: RunContext, search_string: str, directory: str = ".") -> GrepOutput:
    import json
    import os
    import shutil
    import subprocess
    import sys

    # Sanitize search string to handle any surrogates from copy-paste
    search_string = _sanitize_string(search_string)

    directory = Path(directory).expanduser().resolve()

    # Enforce workspace / sensitive directory policy before searching
    policy = check_path_allowed(str(directory), Operation.SEARCH)
    if not policy.allowed:
        error_message = policy.reason or "Search blocked by path policy."
        return GrepOutput(matches=[], error=error_message)

    matches: deque[MatchInfo] = deque(maxlen=MAX_GREP_MATCHES)
    error_message: str | None = None

    # Create a temporary ignore file with our ignore patterns
    ignore_file = None
    try:
        # Find ripgrep executable - first check system PATH, then virtual environment
        rg_path = shutil.which("rg")
        if not rg_path:
            python_dir = Path(sys.executable).parent
            for name in ["rg", "rg.exe"]:
                candidate = python_dir / name
                if candidate.exists():
                    rg_path = str(candidate)
                    break

        if not rg_path:
            error_message = (
                "ripgrep (rg) not found. Please install ripgrep to use this tool."
            )
            return GrepOutput(matches=[], error=error_message)

        # Prevent option injection: treat search_string as data/regex only.
        # Use '--' before the pattern so ripgrep stops parsing flags.
        cmd = [
            rg_path,
            "--json",
            "--max-count",
            str(MAX_GREP_MATCHES),
            "--max-filesize",
            "5M",
            "--type=all",
            "--",
            search_string,
            directory,
        ]

        # Add ignore patterns to the command via a temporary file
        from code_muse.tools.common import DIR_IGNORE_PATTERNS

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".ignore") as f:
            ignore_file = f.name
            for pattern in DIR_IGNORE_PATTERNS:
                # Skip patterns that would match the search directory itself
                if would_match_directory(pattern, directory):
                    continue
                f.write(f"{pattern}\n")

        # Insert ignore-file arg after the base flags and before '--'
        cmd.insert(1, "--ignore-file")
        cmd.insert(2, ignore_file)

        # Stream JSON output via Popen to avoid buffering huge results
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        timed_out = False
        import threading

        def _kill_on_timeout():
            nonlocal timed_out
            timed_out = True
            with contextlib.suppress(Exception):
                process.kill()

        timer = threading.Timer(30.0, _kill_on_timeout)
        timer.start()

        try:
            for raw_line in process.stdout:
                if timed_out:
                    raise subprocess.TimeoutExpired("rg", 30)
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                try:
                    match_data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if match_data.get("type") != "match":
                    continue
                data = match_data.get("data", {})
                path_data = data.get("path", {})
                file_path = path_data.get("text", "") if path_data.get("text") else ""
                line_number = data.get("line_number", None)
                line_content = (
                    data.get("lines", {}).get("text", "")
                    if data.get("lines", {}).get("text")
                    else ""
                )
                if len(line_content) > MAX_GREP_LINE_LENGTH:
                    line_content = line_content[:MAX_GREP_LINE_LENGTH]
                if file_path and line_number:
                    matches.append(
                        MatchInfo(
                            file_path=_sanitize_string(file_path),
                            line_number=line_number,
                            line_content=_sanitize_string(line_content.strip()),
                        )
                    )
                    if len(matches) >= MAX_GREP_MATCHES:
                        break
        finally:
            timer.cancel()
            # Ensure ripgrep is killed even if we stopped early
            try:
                if process.poll() is None:
                    process.kill()
            except Exception:
                pass
            with contextlib.suppress(Exception):
                process.wait(timeout=2)

    except subprocess.TimeoutExpired:
        error_message = "Grep command timed out after 30 seconds"
    except FileNotFoundError:
        error_message = (
            "ripgrep (rg) not found. Please install ripgrep to use this tool."
        )
    except Exception as e:
        error_message = f"Error during grep operation: {e}"
    finally:
        if ignore_file and Path(ignore_file).exists():
            with contextlib.suppress(OSError):
                os.unlink(ignore_file)

    match_list = list(matches)

    # Build structured GrepMatch objects for the UI
    grep_matches = [
        GrepMatch(
            file_path=m.file_path or "",
            line_number=m.line_number or 1,
            line_content=m.line_content or "",
        )
        for m in match_list
    ]

    unique_files = len(set(m.file_path for m in match_list)) if match_list else 0

    grep_result_msg = GrepResultMessage(
        search_term=search_string,
        directory=str(directory),
        matches=grep_matches,
        total_matches=len(match_list),
        files_searched=unique_files,
    )
    get_message_bus().emit(grep_result_msg)

    return GrepOutput(matches=match_list, error=error_message)


def register_list_files(agent):
    """Register only the list_files tool."""
    from code_muse.config import get_allow_recursion

    @agent.tool
    def list_files(
        context: RunContext, directory: str = ".", recursive: bool = True
    ) -> ListFileOutput:
        """List files and directories with intelligent filtering and safety features.

        Automatically ignores build artifacts, caches, and common noise.
        """
        warning = None
        if recursive and not get_allow_recursion():
            warning = "Recursion disabled globally for list_files - returning non-recursive results"
            recursive = False
        result = _list_files(context, directory, recursive)

        # The structured FileListingMessage is already emitted by _list_files
        # No need to emit again here
        if warning:
            result.error = warning
        if (len(result.content)) > 200000:
            result.content = result.content[0:200000]
            result.error = "Results truncated. This is a massive directory tree, recommend non-recursive calls to list_files"
        return result


def register_read_file(agent):
    """Register only the read_file tool."""

    @agent.tool
    def read_file(
        context: RunContext,
        file_path: str = "",
        start_line: int | None = None,
        num_lines: int | None = None,
    ) -> ReadFileOutput:
        """Read file contents with optional line-range selection and token safety.

        Use start_line/num_lines for large files to avoid overwhelming context.
        """
        return _read_file(context, file_path, start_line, num_lines)


def register_grep(agent):
    """Register only the grep tool."""

    @agent.tool
    def grep(
        context: RunContext, search_string: str = "", directory: str = "."
    ) -> GrepOutput:
        """Recursively search for text patterns across files using ripgrep (rg).

        search_string is treated as a regex pattern, not CLI flags.
        Use plain text or regex syntax; option injection is blocked.
        Output is capped to 50 matches and 512 characters per line.
        """
        return _grep(context, search_string, directory)
