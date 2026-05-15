"""Task shift auto-detection module.

Detects when a conversation shifts to a new task using multi-signal analysis:
1. Keyword patterns (fast, synchronous) — explicit task shift phrases
2. TF-IDF cosine similarity (fast, synchronous) — implicit goal changes
3. Embedding similarity (async, optional) — deep semantic change detection

The detector is designed to be conservative — false negatives are better than
false positives (user can always use /task new explicitly).
"""

import logging
import math
import re
from collections import Counter
from typing import Any

from code_muse.messaging import emit_info
from code_muse.plugins.task_context.config import get_task_auto_detect
from code_muse.plugins.task_context.models import TaskShiftSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword-based task shift signals
# ---------------------------------------------------------------------------

# High-confidence signals (threshold >= 0.8)
_HIGH_CONFIDENCE_PATTERNS: list[tuple[re.Pattern, str | None]] = [
    (re.compile(r"\bnew task\b", re.IGNORECASE), None),
    (re.compile(r"\bnext task\b", re.IGNORECASE), None),
    (re.compile(r"\bswitch(?:ing)?\s+to\b", re.IGNORECASE), None),
    (re.compile(r"\bmoving\s+on\s+to\b", re.IGNORECASE), None),
    (
        re.compile(
            r"\blet'?s\s+(?:start|begin|work\s+on|handle|do)\b",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        re.compile(
            r"\bnow\s+(?:handle|work\s+on|let'?s|start)\b",
            re.IGNORECASE,
        ),
        None,
    ),
    (re.compile(r"\bfirst,?\s+let'?s\b", re.IGNORECASE), None),
    (
        re.compile(
            r"\bstart\s+(?:a\s+)?new\s+(?:task|feature|project|module)\b",
            re.IGNORECASE,
        ),
        None,
    ),
]

# Medium-confidence signals (threshold >= 0.5)
_MEDIUM_CONFIDENCE_PATTERNS: list[tuple[re.Pattern, str | None]] = [
    (
        re.compile(
            r"\b(?:let'?s|time\s+to)\s+"
            r"(?:refactor|redesign|reimplement|rewrite|restructure)\b",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        re.compile(
            r"\b(?:start|begin)\s+(?:working\s+on|implementing|building|creating)\b",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        re.compile(
            r"\b(?:next|another|different)\s+(?:thing|topic|area|module|file)\b",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        re.compile(
            r"\bshift\s+(?:gears|focus|attention)\s+(?:to|toward)",
            re.IGNORECASE,
        ),
        None,
    ),
]

# Label extraction patterns — extract a suggested task label from the message
_LABEL_EXTRACTION_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(?:refactor|implement|build|create|fix|add|update)"
        r"\s+([a-zA-Z0-9_/-]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:work\s+on|handle)\s+(?:the\s+)?"
        r"([a-zA-Z0-9_/-]+(?:\s+[a-zA-Z0-9_/-]+){0,3})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:new\s+(?:task|feature|project):?\s+)?"
        r"([a-zA-Z0-9_/-]+(?:\s+[a-zA-Z0-9_/-]+){0,3})",
        re.IGNORECASE,
    ),
]

# ---------------------------------------------------------------------------
# Fast TF-IDF similarity scorer
# ---------------------------------------------------------------------------


class _TfIdfVectorizer:
    """Minimal TF-IDF vectorizer for fast text similarity.

    Uses character n-grams (2-4) to capture code-relevant features.
    No external dependencies — pure Python math.
    """

    def __init__(self, max_features: int = 500) -> None:
        self.max_features = max_features
        self._vocab: dict[str, int] = {}
        self._idf: dict[int, float] = {}
        self._fitted = False

    def _tokenize(self, text: str) -> list[str]:
        """Extract character n-grams from text."""
        text = text.lower()
        ngrams: list[str] = []
        # Character n-grams of length 2-4
        for n in range(2, 5):
            for i in range(len(text) - n + 1):
                ngrams.append(text[i : i + n])
        return ngrams

    def fit(self, texts: list[str]) -> None:
        """Fit the vectorizer on a corpus of texts."""
        doc_freq: Counter[str] = Counter()
        for text in texts:
            ngrams = set(self._tokenize(text))
            doc_freq.update(ngrams)

        n_docs = len(texts)
        # Select top features by document frequency
        top_features = doc_freq.most_common(self.max_features)
        self._vocab = {ng: idx for idx, (ng, _) in enumerate(top_features)}
        self._idf = {
            idx: math.log((n_docs + 1) / (freq + 1)) + 1
            for idx, (ng, freq) in enumerate(top_features)
        }
        self._fitted = True

    def transform(self, text: str) -> list[float]:
        """Transform text into a TF-IDF vector."""
        if not self._fitted:
            return [0.0] * len(self._vocab) if self._vocab else []

        ngrams = self._tokenize(text)
        tf = Counter(ngrams)

        vector = [0.0] * len(self._vocab)
        total = len(ngrams) or 1
        for ng, count in tf.items():
            idx = self._vocab.get(ng)
            if idx is not None:
                vector[idx] = (count / total) * self._idf.get(idx, 1.0)
        return vector

    def cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
        norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
        norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
        return dot / (norm_a * norm_b)


# Singleton vectorizer — we fit once and reuse
_vectorizer = _TfIdfVectorizer()
_vectorizer_fitted = False
_previous_message_vectors: list[list[float]] = []


def _ensure_vectorizer_fitted(messages: list[str]) -> None:
    """Fit the vectorizer if not already done."""
    global _vectorizer_fitted, _previous_message_vectors  # noqa: PLW0603
    if not _vectorizer_fitted and messages:
        _vectorizer.fit(messages)
        _vectorizer_fitted = True
        _previous_message_vectors = [_vectorizer.transform(msg) for msg in messages]


def _compute_similarity_drop(
    current_msg: str,
    previous_messages: list[str],
) -> float:
    """Compute how different the current message is from recent history.

    Returns a float 0.0–1.0 where higher values mean more different
    (stronger task shift signal).
    """
    global _vectorizer, _vectorizer_fitted, _previous_message_vectors  # noqa: PLW0603

    if not previous_messages:
        return 0.0

    _ensure_vectorizer_fitted(previous_messages)

    if not _vectorizer_fitted:
        return 0.0

    current_vec = _vectorizer.transform(current_msg)

    if not _previous_message_vectors:
        return 0.0

    # Average similarity to last 3 messages (or fewer)
    recent = _previous_message_vectors[-3:]
    avg_similarity = sum(
        _vectorizer.cosine_similarity(current_vec, vec) for vec in recent
    ) / max(len(recent), 1)

    # Convert similarity to "difference" score
    # 1.0 = completely different, 0.0 = identical
    difference = 1.0 - avg_similarity
    return max(0.0, min(1.0, difference))


# ---------------------------------------------------------------------------
# Main detection API
# ---------------------------------------------------------------------------


def detect_task_shift(
    message: Any,
    recent_messages: list[Any],
    task_manager: Any = None,
) -> TaskShiftSignal:
    """Detect whether *message* signals a shift to a new task.

    Uses multi-signal analysis with configurable sensitivity.
    Returns a TaskShiftSignal with confidence score.

    Args:
        message: The incoming user message (pydantic-ai ModelMessage or str).
        recent_messages: List of recent messages for context comparison.
        task_manager: Optional TaskManager instance (for getting active task context).

    Returns:
        TaskShiftSignal with detection result.
    """
    if not get_task_auto_detect():
        return TaskShiftSignal(detected=False, confidence=0.0)

    # Extract text from message
    text = _extract_text(message)
    if not text:
        return TaskShiftSignal(detected=False, confidence=0.0)

    recent_texts = [_extract_text(m) for m in recent_messages[-5:] if _extract_text(m)]

    # Signal 1: High-confidence keyword patterns
    for pattern, _ in _HIGH_CONFIDENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            label = _extract_label(text) if not match.lastgroup else match.lastgroup
            logger.debug(
                "Task shift detected (high confidence): matched '%s'",
                pattern.pattern,
            )
            label_text = f" '{label}'" if label else ""
            emit_info(
                f"🔀 Task switch detected (confidence: {0.85:.0%}){label_text}",
            )
            return TaskShiftSignal(
                detected=True,
                confidence=0.85,
                signal_source="keyword",
                suggested_label=label,
                trigger_message=text[:200],
            )

    # Signal 2: Medium-confidence keyword patterns
    for pattern, _ in _MEDIUM_CONFIDENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            label = _extract_label(text)
            logger.debug(
                "Task shift detected (medium confidence): matched '%s'",
                pattern.pattern,
            )
            label_text = f" '{label}'" if label else ""
            emit_info(
                f"🔀 Possible task shift (confidence: {0.65:.0%}){label_text}",
            )
            return TaskShiftSignal(
                detected=True,
                confidence=0.65,
                signal_source="keyword",
                suggested_label=label,
                trigger_message=text[:200],
            )

    # Signal 3: TF-IDF similarity drop (implicit task shift)
    if recent_texts:
        similarity_drop = _compute_similarity_drop(text, recent_texts)
        if similarity_drop > 0.75:
            label = _extract_label(text)
            logger.debug("Task shift detected (similarity drop): %.2f", similarity_drop)
            return TaskShiftSignal(
                detected=True,
                confidence=min(0.6, similarity_drop * 0.8),
                signal_source="embedding",
                suggested_label=label,
                trigger_message=text[:200],
            )

    # Signal 4: Very short messages that don't look like continuations
    # (e.g. "now do X" after a long silence)
    # This is a weak signal — only fire if the message is a single imperative
    if len(text.split()) <= 8 and not _looks_like_continuation(text, recent_texts):
        label = _extract_label(text)
        if label:
            logger.debug("Task shift detected (imperative signal): '%s'", text[:80])
            return TaskShiftSignal(
                detected=True,
                confidence=0.45,
                signal_source="keyword",
                suggested_label=label,
                trigger_message=text[:200],
            )

    return TaskShiftSignal(detected=False, confidence=0.0)


def _extract_text(message: Any) -> str:
    """Extract plain text content from various message formats.

    Handles pydantic-ai ModelMessage, dict messages, and plain strings.
    """
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        # Try common dict formats
        for key in ("content", "text", "message", "parts", "user_message"):
            val = message.get(key)
            if isinstance(val, str):
                return val
        return ""
    # pydantic-ai ModelMessage
    try:
        parts = getattr(message, "parts", []) or []
        texts: list[str] = []
        for part in parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, str):
                        texts.append(item)
        return " ".join(texts)
    except Exception:
        return str(message) if message else ""


def _extract_label(text: str) -> str | None:
    """Try to extract a task label from the message text.

    Returns the first match found, or None.
    """
    for pattern in _LABEL_EXTRACTION_PATTERNS:
        match = pattern.search(text)
        if match:
            label = match.group(1).strip()
            # Clean up — take only first 3 meaningful words max
            words = label.split()
            clean = " ".join(words[:3])
            if clean:
                return clean.lower().replace(" ", "-")
    return None


def _looks_like_continuation(text: str, recent_texts: list[str]) -> bool:
    """Check if *text* looks like a continuation of recent conversation.

    Looks for referencing pronouns, continuation markers, and anaphora.
    """
    if not recent_texts:
        return False

    continuation_markers = [
        r"\b(?:it|this|that|these|those|they|them)\b",
        r"\b(?:also|too|as\s+well|additionally|furthermore|moreover)\b",
        r"\b(?:and\s+then|next|after\s+that|then)\b",
        r"\b(?:what\s+about|how\s+about|what\s+next)\b",
        r"\byes\b|\bno\b|\bok\b|\bsure\b|\bgreat\b|\bthanks?\b",
        r"\b(?:fix|update|change|modify|adjust|tweak)\s+(?:it|this|that)\b",
    ]

    for pattern_src in continuation_markers:
        if re.search(pattern_src, text, re.IGNORECASE):
            return True

    return False


def reset_detector() -> None:
    """Reset the detector state (for testing or session reset)."""
    global _vectorizer_fitted, _previous_message_vectors  # noqa: PLW0603
    _vectorizer = _TfIdfVectorizer()  # noqa: F841
    _vectorizer_fitted = False
    _previous_message_vectors = []
