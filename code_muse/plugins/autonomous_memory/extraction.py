"""Stub extraction engine for the Autonomous Memory Pipeline.

Reads a session's messages file and produces a basic markdown summary.
Future iterations will drive this via a headless LLM agent.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_RELEVANCE_THRESHOLD = float(
    os.environ.get("MEMORY_RELEVANCE_THRESHOLD", "0.15")
)
_MEMORY_MIN_KEEP = int(os.environ.get("MEMORY_MIN_KEEP_CHUNKS", "3"))

# Optional BM25 scorer — gracefully degrades if module missing
_BM25_AVAILABLE = True
try:
    from code_muse.plugins.autonomous_memory.bm25_scorer import (
        BM25Scorer,
        select_top_chunks,
    )
except Exception:
    _BM25_AVAILABLE = False

_ROLE_RE = re.compile(r'"role"\s*:\s*"(\w+)"')
_TOOL_RE = re.compile(r'"name"\s*:\s*"([^"]+)"')


@dataclass
class ExtractionResult:
    """Output of extracting knowledge from a single session."""

    session_path: str
    raw_memory: str
    synopsis: str
    extracted_at: str


def _parse_messages_jsonl(path: Path) -> list[dict[str, Any]]:
    """Best-effort parse of a JSONL messages file."""
    messages: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as exc:
        logger.warning(f"Failed to read messages file {path}: {exc}")
    return messages


def _parse_messages_json(path: Path) -> list[dict[str, Any]]:
    """Best-effort parse of a JSON array messages file."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, list):
                return data
    except Exception as exc:
        logger.warning(f"Failed to read messages file {path}: {exc}")
    return []


def _load_messages(path: Path) -> list[dict[str, Any]]:
    """Load messages from either JSONL or JSON array format."""
    if path.suffix == ".jsonl":
        return _parse_messages_jsonl(path)
    return _parse_messages_json(path)


def _count_roles(messages: list[dict[str, Any]]) -> dict[str, int]:
    """Tally message roles."""
    counts: dict[str, int] = {}
    for msg in messages:
        role = msg.get("role", "unknown")
        counts[role] = counts.get(role, 0) + 1
    return counts


def _extract_tools(messages: list[dict[str, Any]]) -> set[str]:
    """Extract unique tool names from tool-call messages."""
    tools: set[str] = set()
    for msg in messages:
        if msg.get("role") != "tool":
            # Also look inside assistant messages for tool_calls
            tool_calls = msg.get("tool_calls", [])
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    name = (
                        tc.get("function", {}).get("name")
                        if isinstance(tc, dict)
                        else None
                    )
                    if name:
                        tools.add(name)
                    elif isinstance(tc, dict):
                        name = tc.get("name")
                        if name:
                            tools.add(name)
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            match = _TOOL_RE.search(content)
            if match:
                tools.add(match.group(1))
        name = msg.get("name") or msg.get("tool_name")
        if isinstance(name, str):
            tools.add(name)
    return tools


def _collect_project_context(cwd: str | None = None) -> str:
    """Collect project context from key files in the working directory.

    Reads README, pyproject.toml/package.json, and key source files
    to build a context string for relevance scoring.

    Args:
        cwd: Working directory. Uses current working dir if None.

    Returns:
        Context string (up to 2000 chars).
    """
    root = Path(cwd) if cwd else Path.cwd()
    parts: list[str] = []

    # Project name from directory
    parts.append(f"Project: {root.name}")

    # Read README (first 500 chars)
    readme_paths = [
        root / "README.md",
        root / "README.rst",
        root / "README",
    ]
    for rp in readme_paths:
        if rp.exists():
            try:
                text = rp.read_text(encoding="utf-8", errors="replace")
                parts.append(f"README: {text[:500]}")
            except Exception:
                pass
            break

    # Read project config
    config_paths = [
        root / "pyproject.toml",
        root / "package.json",
        root / "Cargo.toml",
        root / "go.mod",
    ]
    for cp in config_paths:
        if cp.exists():
            try:
                text = cp.read_text(encoding="utf-8", errors="replace")
                parts.append(f"Config ({cp.name}): {text[:300]}")
            except Exception:
                pass
            break

    # Key source files (first 200 chars each, up to 5 files)
    src_dirs = [root / "src", root / "lib", root / "app", root]
    seen = 0
    for src_dir in src_dirs:
        if not src_dir.exists():
            continue
        for ext in (".py", ".js", ".ts", ".go", ".rs"):
            for sf in sorted(src_dir.rglob(f"*{ext}"))[:3]:
                try:
                    text = sf.read_text(encoding="utf-8", errors="replace")
                    parts.append(f"Source ({sf.name}): {text[:200]}")
                    seen += 1
                    if seen >= 5:
                        break
                except Exception:
                    pass
            if seen >= 5:
                break
        if seen >= 5:
            break

    context = "\n\n".join(parts)
    return context[:2000]


def _split_into_chunks(text: str, max_chunk_lines: int = 30) -> list[str]:
    """Split session transcript into turn-level chunks.

    Each chunk is roughly one conversational turn (user/assistant pair)
    or a block of up to max_chunk_lines.

    Args:
        text: Full transcript text.
        max_chunk_lines: Maximum lines per chunk.

    Returns:
        List of chunk strings.
    """
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []

    for line in lines:
        current.append(line)
        # Split on common turn boundaries
        if (
            line.strip().startswith(("User:", "Assistant:", "Human:", "AI:", ">>>"))
            or line.strip().startswith("---")
            or len(current) >= max_chunk_lines
        ):
            chunk_text = "\n".join(current).strip()
            if chunk_text and len(chunk_text) > 20:
                chunks.append(chunk_text)
            current = []

    # Don't forget last chunk
    if current:
        chunk_text = "\n".join(current).strip()
        if chunk_text and len(chunk_text) > 20:
            chunks.append(chunk_text)

    # If no chunks found, return whole text as one chunk
    if not chunks:
        return [text]

    return chunks


def _messages_to_transcript(messages: list[dict[str, Any]]) -> str:
    """Convert message list to a plain-text transcript."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            lines.append(f"{role.capitalize()}: {content.strip()}")
        # Include tool call summaries
        tool_calls = msg.get("tool_calls", [])
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                name = tc.get("function", {}).get("name") or tc.get("name")
                if name:
                    lines.append(f"Tool: {name}")
    return "\n".join(lines)


def _extract_topics(messages: list[dict[str, Any]]) -> list[str]:
    """Extract user message content snippets as 'topics'."""
    topics: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            # Truncate long messages to first 120 chars for brevity
            snippet = content.strip().replace("\n", " ")
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            topics.append(snippet)
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped[:20]  # Cap at 20 topics


def extract_session_knowledge(session_path: Path) -> ExtractionResult | None:
    """Extract a basic memory summary from a session directory.

    This is a stub implementation. Future work will replace it with a
    headless LLM agent that performs deeper semantic extraction.
    """
    try:
        messages_file = None
        for candidate in (
            session_path / "messages.json",
            *session_path.glob("*.jsonl"),
        ):
            if candidate.exists():
                messages_file = candidate
                break

        if messages_file is None:
            logger.warning(f"No messages file found in {session_path}")
            return None

        messages = _load_messages(messages_file)
        if not messages:
            logger.warning(f"Empty or unreadable messages file in {session_path}")
            return None

        # --- Relevance scoring (added Epic 022) ---
        # Convert messages to transcript, split into chunks, score against context
        transcript = _messages_to_transcript(messages)
        session_chunks = _split_into_chunks(transcript)

        relevant_messages = messages
        if _BM25_AVAILABLE and session_chunks:
            try:
                project_context = _collect_project_context()
                scorer = BM25Scorer()
                scorer.fit(session_chunks)
                scores = scorer.score_batch(project_context, session_chunks)
                relevant_chunks = select_top_chunks(
                    session_chunks,
                    scores,
                    threshold=_MEMORY_RELEVANCE_THRESHOLD,
                    min_keep=_MEMORY_MIN_KEEP,
                )
                logger.debug(
                    "Relevance scoring: %d/%d chunks kept (%.0f%%) for extraction",
                    len(relevant_chunks),
                    len(session_chunks),
                    len(relevant_chunks) / max(len(session_chunks), 1) * 100,
                )
                # Map relevant chunks back to messages for topic extraction
                # A message is "relevant" if its content appears in a kept chunk
                relevant_text = "\n".join(relevant_chunks)
                relevant_messages = [
                    msg
                    for msg in messages
                    if isinstance(msg.get("content", ""), str)
                    and msg.get("content", "") in relevant_text
                ]
                # Ensure at least some messages remain for topic extraction
                if not relevant_messages:
                    relevant_messages = messages[:_MEMORY_MIN_KEEP]
            except Exception as exc:
                logger.warning(
                    f"BM25 scoring failed, falling back to full transcript: {exc}"
                )
                relevant_messages = messages
        # --- End relevance scoring ---

        counts = _count_roles(messages)
        tools = _extract_tools(messages)
        topics = _extract_topics(relevant_messages)

        user_count = counts.get("user", 0)
        assistant_count = counts.get("assistant", 0)
        tool_count = counts.get("tool", 0)

        lines = [
            "## Session Summary",
            f"- Messages: {user_count} user, {assistant_count} assistant, {tool_count} tool",
        ]
        if tools:
            lines.append(f"- Tools: {', '.join(sorted(tools))}")
        if topics:
            lines.append(f"- Topics: {'; '.join(topics)}")

        raw_memory = "\n".join(lines)
        synopsis = f"Session with {user_count} user messages, {len(tools)} tools, {len(topics)} topics"
        extracted_at = datetime.now(UTC).isoformat()

        return ExtractionResult(
            session_path=str(session_path),
            raw_memory=raw_memory,
            synopsis=synopsis,
            extracted_at=extracted_at,
        )
    except Exception as exc:
        logger.warning(f"Extraction failed for {session_path}: {exc}")
        return None
