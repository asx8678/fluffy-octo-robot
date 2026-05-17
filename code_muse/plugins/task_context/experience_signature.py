"""Deterministic local semantic signature & fingerprint for experience retrieval.

No heavyweight embedding dependencies. Uses:
- Keyword extraction (alpha-numeric tokens, >=3 chars)
- Character n-gram (3-gram) hash-vector with cosine similarity
- Structural fingerprint from tools/files/categories in metadata

All signatures are deterministic given the same input text.
Sensitive content is redacted before fingerprinting.
"""

import hashlib
import math
import re
from typing import Any

from code_muse.security.redaction import redact_secrets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of dimensions in the hash-vector (sparse projection space)
_SIG_DIMENSIONS = 128

# Character n-gram size for hash-vector
_NGRAM_SIZE = 3

# Minimum keyword length
_MIN_KEYWORD_LEN = 3

# Maximum keywords kept per capsule
_MAX_KEYWORDS = 40

# Structural fingerprint keys to preserve
_STRUCTURAL_KEYS = frozenset(
    {
        "tools_used",
        "file_types",
        "step_types",
        "languages",
        "categories",
        "tags",
    }
)

# ---------------------------------------------------------------------------
# Text preprocessing
# ---------------------------------------------------------------------------

# Patterns for sensitive path-like content that should be redacted
_PATH_RE = re.compile(r"(?:(?:/home|/Users|/root|C:\\)[^\s]+)")
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:password|secret|token|key|api_key|credential)\s*[=:]\s*\S+"
)


def redact_for_signature(text: str) -> str:
    """Redact sensitive content before deriving signature.

    - Uses core redaction for secrets/bearer tokens/env vars
    - Additional path redaction for absolute paths
    """
    if not text:
        return ""
    # Core secret redaction
    text = redact_secrets(text)
    if not isinstance(text, str):
        text = str(text)
    # Redact absolute paths
    text = _PATH_RE.sub("<path>", text)
    # Redact secret-like assignments the core might miss
    text = _SECRET_VALUE_RE.sub(
        lambda m: (
            m.group().split("=")[0].split(":")[0] + "=<redacted>"
            if "=" in m.group() or ":" in m.group()
            else "<redacted>"
        ),
        text,
    )
    return text


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{2,}")


def extract_keywords(text: str, max_keywords: int = _MAX_KEYWORDS) -> list[str]:
    """Extract meaningful keywords from text.

    Returns deduplicated, lowercased keywords sorted by first appearance.
    """
    words = _WORD_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        low = w.lower()
        if low not in seen:
            seen.add(low)
            result.append(low)
            if len(result) >= max_keywords:
                break
    return result


# ---------------------------------------------------------------------------
# Hash-vector signature
# ---------------------------------------------------------------------------


def _ngram_hash(ngram: str) -> int:
    """Deterministic hash of an n-gram to a signed integer."""
    h = hashlib.sha256(ngram.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def compute_semantic_signature(text: str) -> list[float]:
    """Compute a deterministic hash-vector signature from text.

    Projects character n-grams into a fixed-dimension vector using
    locality-sensitive hashing (random projection via hash).
    The vector is L2-normalised so cosine similarity is just dot product.
    """
    if not text.strip():
        return [0.0] * _SIG_DIMENSIONS

    text_lower = text.lower()
    vec = [0.0] * _SIG_DIMENSIONS

    # Generate character n-grams
    for i in range(max(0, len(text_lower) - _NGRAM_SIZE + 1)):
        ngram = text_lower[i : i + _NGRAM_SIZE]
        h = _ngram_hash(ngram)
        # Use hash bits to pick dimension and sign
        dim = h % _SIG_DIMENSIONS
        sign = 1.0 if (h // _SIG_DIMENSIONS) % 2 == 0 else -1.0
        vec[dim] += sign

    # Also project keywords (higher weight)
    keywords = extract_keywords(text)
    for kw in keywords:
        h = _ngram_hash(kw)
        dim = h % _SIG_DIMENSIONS
        sign = 1.0 if (h // _SIG_DIMENSIONS) % 2 == 0 else -1.0
        vec[dim] += sign * 2.0  # Keywords weighted more

    # L2 normalise
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two L2-normalised vectors.

    For normalised vectors, this is just the dot product.
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    return max(0.0, sum(a * b for a, b in zip(vec_a, vec_b, strict=False)))


def compute_similarity(text_a: str, text_b: str) -> float:
    """Compute semantic similarity between two texts.

    Convenience wrapper: redacts, signs, compares.
    """
    sig_a = compute_semantic_signature(redact_for_signature(text_a))
    sig_b = compute_semantic_signature(redact_for_signature(text_b))
    return cosine_similarity(sig_a, sig_b)


# ---------------------------------------------------------------------------
# Structural fingerprint
# ---------------------------------------------------------------------------


def extract_structural_fingerprint(
    metadata: dict[str, Any] | None = None,
    tools_used: list[str] | None = None,
    file_types: list[str] | None = None,
) -> dict:
    """Extract structural fingerprint from task metadata.

    Captures what tools were used, file types touched, and high-level
    categories — useful for disambiguation when keywords overlap.
    """
    fp: dict[str, Any] = {}
    if tools_used:
        fp["tools_used"] = sorted(set(tools_used))
    if file_types:
        fp["file_types"] = sorted(set(file_types))
    if metadata:
        for key in _STRUCTURAL_KEYS:
            val = metadata.get(key)
            if val:
                fp[key] = sorted(set(val)) if isinstance(val, list) else val
    return fp


# ---------------------------------------------------------------------------
# Full capsule signature computation
# ---------------------------------------------------------------------------


def compute_capsule_signature(
    task_label: str,
    outcome_summary: str,
    summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[list[str], list[float], dict]:
    """Compute the full signature components for an experience capsule.

    Returns (key_terms, semantic_signature, structural_fingerprint).
    """
    # Combine all text for signature (redacted)
    combined = f"{task_label} {outcome_summary} {summary}"
    redacted = redact_for_signature(combined)

    key_terms = extract_keywords(redacted)
    semantic_signature = compute_semantic_signature(redacted)
    structural_fingerprint = extract_structural_fingerprint(metadata=metadata)

    return key_terms, semantic_signature, structural_fingerprint


def search_capsules(
    query: str,
    capsules: list[Any],
    semantic_signatures: list[list[float]] | None = None,
    top_k: int = 3,
    min_similarity: float = 0.3,
) -> list[tuple[Any, float]]:
    """Search capsules by query, returning top-k ranked results.

    Args:
        query: Search query text.
        capsules: List of ExperienceCapsule objects.
        semantic_signatures: Optional pre-extracted signatures (same order).
        top_k: Max results to return.
        min_similarity: Minimum similarity threshold.

    Returns:
        List of (capsule, similarity) tuples, sorted descending.
    """
    if not capsules:
        return []

    redacted_query = redact_for_signature(query)
    query_sig = compute_semantic_signature(redacted_query)
    query_keywords = set(extract_keywords(redacted_query))

    scored: list[tuple[Any, float]] = []
    for i, cap in enumerate(capsules):
        # Cosine similarity of hash-vectors
        if semantic_signatures and i < len(semantic_signatures):
            cap_sig = semantic_signatures[i]
        else:
            cap_sig = getattr(cap, "semantic_signature", [])

        vec_sim = cosine_similarity(query_sig, cap_sig) if cap_sig else 0.0

        # Keyword overlap bonus
        cap_keywords = set(getattr(cap, "key_terms", []))
        if query_keywords and cap_keywords:
            overlap = len(query_keywords & cap_keywords) / len(
                query_keywords | cap_keywords
            )
            # Blend: 60% vector, 40% keyword Jaccard
            score = vec_sim * 0.6 + overlap * 0.4
        else:
            score = vec_sim

        if score >= min_similarity:
            scored.append((cap, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
