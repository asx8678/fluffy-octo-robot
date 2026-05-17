"""Tests for the document store."""

import pytest

from code_muse.plugins.task_context.document_store import (
    DocumentStore,
    get_document_store,
    get_reference_stub,
    is_long_document,
    reset_document_store,
    store_long_document,
)


@pytest.fixture
def short_text() -> str:
    return "This is a short text."


@pytest.fixture
def long_text() -> str:
    """Generate a ~3500 word document with markdown headings."""
    paragraphs = []
    for i in range(10):
        sections = []
        sections.append(f"# Section {i + 1}\n")
        for j in range(35):
            sections.append(f"Paragraph {j + 1} of section {i + 1}. " * 10)
        paragraphs.append("\n".join(sections))
    return "\n\n".join(paragraphs)


def test_is_long_document_short(short_text):
    assert not is_long_document(short_text)


def test_is_long_document_long(long_text):
    assert is_long_document(long_text)


def test_store_long_document_short(short_text):
    reset_document_store()
    result = store_long_document(short_text)
    assert result is None


def test_store_long_document_long(long_text):
    reset_document_store()
    doc = store_long_document(long_text)
    assert doc is not None
    assert doc.word_count > 0
    assert doc.section_count > 0


def test_get_reference_stub_short(short_text):
    result = get_reference_stub(short_text)
    assert result == short_text


def test_get_reference_stub_long(long_text):
    result = get_reference_stub(long_text)
    assert "[📄 Document:" in result
    assert "[Sections:" in result
    assert "/doc get" in result


def test_document_retrieval(long_text):
    reset_document_store()
    doc = store_long_document(long_text)
    assert doc is not None

    store = get_document_store()
    retrieved = store.get_document(doc.doc_id[:12])
    assert retrieved is not None
    assert retrieved.doc_id == doc.doc_id


def test_section_retrieval(long_text):
    reset_document_store()
    doc = store_long_document(long_text)
    assert doc is not None

    store = get_document_store()
    section = store.get_section(doc.doc_id[:12], 1)
    assert section is not None
    assert section.doc_id == doc.doc_id


def test_document_summary(long_text):
    reset_document_store()
    doc = store_long_document(long_text)
    assert doc is not None

    store = get_document_store()
    summary = store.get_document_summary(doc.doc_id[:12])
    assert summary is not None
    assert "Section" in summary


def test_lru_eviction():
    reset_document_store()
    store = DocumentStore(max_documents=2)

    # Store 3 documents — first should be evicted
    doc1_text = "word " * 4000
    doc2_text = "lorem " * 4000
    doc3_text = "ipsum " * 4000

    d1 = store.store_document(doc1_text, title="Doc 1")
    d2 = store.store_document(doc2_text, title="Doc 2")
    d3 = store.store_document(doc3_text, title="Doc 3")

    # d1 should be evicted
    assert store.get_document(d1.doc_id[:12]) is None
    assert store.get_document(d2.doc_id[:12]) is not None
    assert store.get_document(d3.doc_id[:12]) is not None


def test_dedup(long_text):
    reset_document_store()
    doc1 = store_long_document(long_text)
    doc2 = store_long_document(long_text)
    assert doc1 is not None
    assert doc2 is not None
    assert doc1.doc_id == doc2.doc_id

    store = get_document_store()
    assert store.count == 1  # Only one unique document
