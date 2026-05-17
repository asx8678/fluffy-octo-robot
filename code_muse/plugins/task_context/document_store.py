"""External document store for long pasted content.

When a user pastes a long document (>3000 words), it's stored externally
and replaced in-context with a structured reference stub that includes
title, section index, token count, and a brief abstract.

The document store uses a file-based backend with LRU eviction
to prevent unbounded growth.
"""

import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default threshold: 3000 words → triggers external storage
_DEFAULT_WORD_THRESHOLD = 3000

# Default threshold in tokens (approximate)
_DEFAULT_TOKEN_THRESHOLD = 4000

# Max documents in store before LRU eviction
_DEFAULT_MAX_DOCUMENTS = 100

# Store directory relative to CONFIG_DIR
_DOCUMENT_STORE_DIR = "document_store"


@dataclass
class StoredDocument:
    """A document stored externally with section/page indexing."""

    doc_id: str  # SHA256 hash of content
    title: str
    content: str
    tokens: int
    word_count: int
    sections: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = 0.0
    accessed_at: float = 0.0
    section_count: int = 0

    @property
    def reference_stub(self) -> str:
        """Generate the in-context reference stub."""
        doc_id_short = self.doc_id[:12]
        lines = [
            f"[📄 Document: {self.title}]",
            (
                f"[Sections: {self.section_count} | "
                f"Words: {self.word_count:,} | Tokens: ~{self.tokens:,}]"
            ),
            f"[Abstract: {self._generate_abstract()}]",
            (
                f"[To retrieve: use /doc get {doc_id_short} "
                f"or /doc section {doc_id_short} <section_number>]"
            ),
        ]
        return "\n".join(lines)

    def _generate_abstract(self, max_chars: int = 200) -> str:
        """Generate a brief abstract from the first content block."""
        for line in self.content.split("\n"):
            line = line.strip()
            if line and len(line) > 20:
                return line[:max_chars] + ("..." if len(line) > max_chars else "")
        suffix = "..." if len(self.content) > max_chars else ""
        return self.content[:max_chars] + suffix


@dataclass
class DocumentSection:
    """A single section of a document."""

    doc_id: str
    section_number: int
    heading: str
    content: str
    start_line: int
    end_line: int


class DocumentStore:
    """External document store with LRU eviction."""

    def __init__(
        self,
        store_dir: str | Path | None = None,
        max_documents: int = _DEFAULT_MAX_DOCUMENTS,
    ):
        if store_dir is None:
            from code_muse.config.paths import CONFIG_DIR

            store_dir = Path(CONFIG_DIR) / _DOCUMENT_STORE_DIR
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._max_documents = max_documents
        self._index_path = self._store_dir / "index.json"
        self._documents: dict[str, StoredDocument] = {}
        self._access_order: OrderedDict[str, float] = OrderedDict()
        self._load_index()

    def _load_index(self) -> None:
        """Load document index from disk."""
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text())
                for key, val in data.items():
                    sd = StoredDocument(**val)
                    self._documents[key] = sd
                    self._access_order[key] = sd.accessed_at
                logger.debug("Loaded %d documents from index", len(self._documents))
            except Exception:
                logger.warning("Failed to load document index", exc_info=True)

    def _save_index(self) -> None:
        """Save document index to disk."""
        try:
            data = {}
            for key, doc in self._documents.items():
                d = {k: v for k, v in doc.__dict__.items() if k != "content"}
                d["content"] = ""  # Don't store full content in index
                data[key] = d
            self._index_path.write_text(json.dumps(data, indent=2))
        except Exception:
            logger.warning("Failed to save document index", exc_info=True)

    def _get_content_path(self, doc_id: str) -> Path:
        """Get path to the content file for a document."""
        return self._store_dir / f"{doc_id}.txt"

    def store_document(
        self,
        content: str,
        title: str = "Pasted Document",
        metadata: dict | None = None,
    ) -> StoredDocument:
        """Store a long document externally.

        Returns the StoredDocument (stub inserted in-context).
        """
        doc_id = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Dedup
        if doc_id in self._documents:
            self._touch(doc_id)
            return self._documents[doc_id]

        # Evict if at capacity
        if len(self._documents) >= self._max_documents:
            self._evict_lru()

        # Parse sections
        sections = self._parse_sections(content, doc_id)

        # Token estimation
        from code_muse.agents._history import estimate_tokens

        tokens = estimate_tokens(content)
        word_count = len(content.split())

        doc = StoredDocument(
            doc_id=doc_id,
            title=title,
            content=content,
            tokens=tokens,
            word_count=word_count,
            sections=[{k: v for k, v in s.__dict__.items()} for s in sections],
            created_at=time.time(),
            accessed_at=time.time(),
            section_count=len(sections),
        )

        # Write content to disk
        try:
            content_path = self._get_content_path(doc_id)
            content_path.write_text(content)
        except Exception:
            logger.error("Failed to write document content", exc_info=True)
            return doc  # Still return in-memory

        self._documents[doc_id] = doc
        self._access_order[doc_id] = time.time()
        self._save_index()
        logger.info(
            "Stored document %s (%d words, %d sections)",
            doc_id[:12],
            word_count,
            len(sections),
        )
        return doc

    def _evict_lru(self) -> None:
        """Evict oldest accessed document."""
        if not self._access_order:
            return
        oldest_key = next(iter(self._access_order))
        if oldest_key in self._documents:
            del self._documents[oldest_key]
            del self._access_order[oldest_key]
            from contextlib import suppress

            with suppress(Exception):
                self._get_content_path(oldest_key).unlink(missing_ok=True)
            self._save_index()
            logger.info("LRU evicted document %s", oldest_key[:12])

    def _touch(self, doc_id: str) -> None:
        """Update access time for a document."""
        if doc_id in self._documents:
            self._documents[doc_id].accessed_at = time.time()
            self._access_order[doc_id] = time.time()
            # Move to end (most recently used)
            self._access_order.move_to_end(doc_id, last=True)

    def _parse_sections(self, content: str, doc_id: str) -> list[DocumentSection]:
        """Parse document into sections by headings.

        Recognizes markdown headings (# ## ###), numbered sections,
        and paragraph breaks.
        """
        lines = content.split("\n")
        sections: list[DocumentSection] = []
        current_heading = "Introduction"
        current_start = 0
        current_content_lines: list[str] = []

        heading_pattern = re.compile(r"^(#{1,4}\s+|\w+\.\s+[A-Z])")

        for i, line in enumerate(lines):
            match = heading_pattern.match(line)
            if match:
                # Save previous section
                if current_content_lines:
                    section_content = "\n".join(current_content_lines).strip()
                    if section_content:
                        sections.append(
                            DocumentSection(
                                doc_id=doc_id,
                                section_number=len(sections) + 1,
                                heading=current_heading,
                                content=section_content,
                                start_line=current_start,
                                end_line=i - 1,
                            )
                        )
                current_heading = line.strip().lstrip("# ")
                current_start = i
                current_content_lines = [line]
            else:
                current_content_lines.append(line)

        # Last section
        if current_content_lines:
            section_content = "\n".join(current_content_lines).strip()
            if section_content:
                sections.append(
                    DocumentSection(
                        doc_id=doc_id,
                        section_number=len(sections) + 1,
                        heading=current_heading,
                        content=section_content,
                        start_line=current_start,
                        end_line=len(lines) - 1,
                    )
                )

        return sections or [
            DocumentSection(
                doc_id=doc_id,
                section_number=1,
                heading="Content",
                content=content,
                start_line=0,
                end_line=len(lines) - 1,
            )
        ]

    def get_document(self, doc_id: str) -> StoredDocument | None:
        """Retrieve a stored document by ID (full or first 12 chars)."""
        for key in self._documents:
            if key == doc_id or key.startswith(doc_id):
                self._touch(key)
                return self._documents[key]
        return None

    def get_section(self, doc_id: str, section_number: int) -> DocumentSection | None:
        """Retrieve a specific section of a document by section number."""
        doc = self.get_document(doc_id)
        if not doc:
            return None
        # Load from disk if content is empty
        if not doc.content:
            content_path = self._get_content_path(doc.doc_id)
            if content_path.exists():
                doc.content = content_path.read_text()
                # Re-parse sections
                doc.sections = [
                    {k: v for k, v in s.__dict__.items()}
                    for s in self._parse_sections(doc.content, doc.doc_id)
                ]

        matching = [
            s for s in doc.sections if s.get("section_number") == section_number
        ]
        if matching:
            return DocumentSection(**matching[0])

        # Fallback: try to load section from content
        if doc.content:
            sections = self._parse_sections(doc.content, doc.doc_id)
            for s in sections:
                if s.section_number == section_number:
                    return s
        return None

    def get_document_summary(self, doc_id: str, max_bullets: int = 3) -> str | None:
        """Generate a summary from the document's sections."""
        doc = self.get_document(doc_id)
        if not doc:
            return None

        # Re-parse sections if needed
        if doc.content:
            sections = self._parse_sections(doc.content, doc.doc_id)
        else:
            content_path = self._get_content_path(doc.doc_id)
            if content_path.exists():
                doc.content = content_path.read_text()
                sections = self._parse_sections(doc.content, doc.doc_id)
            else:
                sections = []

        if not sections:
            return f"- {doc._generate_abstract()}"

        bullets: list[str] = []
        for s in sections[:max_bullets]:
            # Take first meaningful line of each section
            for line in s.content.split("\n"):
                line = line.strip()
                if line and len(line) > 15:
                    truncated = line[:150]
                    suffix = "..." if len(line) > 150 else ""
                    bullets.append(f"- {s.heading}: {truncated}{suffix}")
                    break

        if len(sections) > max_bullets:
            bullets.append(f"- ... and {len(sections) - max_bullets} more sections")

        return "\n".join(bullets)

    def list_documents(self) -> list[dict[str, Any]]:
        """List all stored documents (metadata only)."""
        return [
            {
                "doc_id": d.doc_id[:12],
                "title": d.title,
                "words": d.word_count,
                "sections": d.section_count,
                "accessed": d.accessed_at,
            }
            for d in self._documents.values()
        ]

    @property
    def count(self) -> int:
        return len(self._documents)


# Singleton
_document_store: DocumentStore | None = None


def get_document_store() -> DocumentStore:
    """Get or create the singleton document store."""
    global _document_store
    if _document_store is None:
        _document_store = DocumentStore()
    return _document_store


def reset_document_store() -> None:
    """Reset the singleton (useful in tests)."""
    global _document_store
    _document_store = None


def is_long_document(text: str) -> bool:
    """Check if text exceeds the word threshold for external storage."""
    return len(text.split()) >= _DEFAULT_WORD_THRESHOLD


def store_long_document(
    text: str, title: str = "Pasted Document"
) -> StoredDocument | None:
    """Store a long document if it meets threshold criteria.

    Returns the StoredDocument if stored, None if too short.
    """
    if not is_long_document(text):
        return None
    store = get_document_store()
    return store.store_document(text, title=title)


def get_reference_stub(text: str, title: str = "Pasted Document") -> str:
    """Replace long document content with a reference stub.

    If the text exceeds the threshold, stores it externally and
    returns a reference stub. Otherwise returns the original text.
    """
    doc = store_long_document(text, title=title)
    if doc:
        return doc.reference_stub
    return text


def _find_long_documents_in_messages(
    messages: list,
) -> list[tuple[int, str]]:
    """Find long user message content in a message list.

    Returns list of (index, content) for messages that exceed threshold.
    """
    from code_muse.plugins.task_context._text_utils import _extract_text

    found: list[tuple[int, str]] = []
    for i, msg in enumerate(messages):
        text = _extract_text(msg)
        if is_long_document(text):
            found.append((i, text))
    return found


def replace_long_documents_in_history(messages: list) -> list:
    """Replace long documents in message history with reference stubs.

    Returns a new message list with long content replaced.
    Safe to call multiple times (stubs are idempotent).
    """
    result = list(messages)
    for idx, text in _find_long_documents_in_messages(messages):
        stub = get_reference_stub(text, title=f"Pasted Document (turn {idx})")
        # Replace content in the message
        msg = result[idx]
        for part in getattr(msg, "parts", []) or []:
            if (
                hasattr(part, "content")
                and isinstance(part.content, str)
                and part.content == text
            ):
                part.content = stub
    return result
