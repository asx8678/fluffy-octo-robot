"""Relevance scoring module for task-aware context pruning.

Computes relevance scores between messages and the active task context
using a two-tier approach:

**Fast tier** (always runs, synchronous, ~1ms per batch):
- Keyword overlap with task label/description
- TF-IDF cosine similarity (reuses vectorizer from detector)
- Recency bonus (more recent = more relevant)
- Tool call relevance (tool calls related to task goal)

**Deep tier** (optional, async, configurable via `task_embedding_enabled`):
- Sentence embedding cosine similarity
- Uses BAAI/bge-small-en-v1.5 (or all-MiniLM-L6-v2 fallback)
- Runs lazily on idle or when explicitly triggered

Scoring strategy:
- Score 0.0–1.0 where 1.0 = highly relevant to active task
- Active task messages always get score 1.0
- Completed task messages get score based on similarity to active task
- System messages get score 0.0 (handled separately)
"""

import logging
import math
import re
from typing import Any

from code_muse.plugins.task_context._text_utils import _extract_text
from code_muse.plugins.task_context.config import get_task_embedding_enabled

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding model research (from Helios analysis)
#
# Recommended models for optional deep scoring:
#
# Primary: BAAI/bge-small-en-v1.5
#   - Size: 127 MB (ONNX), 384-dim embeddings
#   - MTEB: 63.13 (best quality in small model class)
#   - Install: pip install onnxruntime sentence-transformers
#   - Use: from sentence_transformers import SentenceTransformer
#
# Fallback: all-MiniLM-L6-v2
#   - Size: 87 MB (PyTorch), 22 MB (ONNX qint8) — LIGHTEST OPTION
#   - MTEB: 58.80 (lower quality, but trained on code data)
#   - Benefit: Trained on code_search_net (1.15M code-query pairs)
#
# Runtime preference: ONNX (onnxruntime) over PyTorch
#   - onnxruntime ~17 MB vs torch ~84 MB install size
#   - both support Python 3.14+
#
# Config key: task_embedding_model = "bge-small-en-v1.5" | "all-MiniLM-L6-v2"
# ---------------------------------------------------------------------------


def score_message_relevance(
    message: Any,
    message_index: int,
    total_messages: int,
    active_task_label: str,
    active_task_messages: list[Any] | None = None,
    token_estimate: int = 0,
) -> float:
    """Compute relevance score for a message relative to the active task.

    Returns a float 0.0–1.0 where:
    - 1.0 = highly relevant to the current active task
    - 0.5 = somewhat relevant / neutral
    - 0.0 = completely irrelevant

    The score is a weighted combination of:
    1. Keyword overlap with task label (35% weight)
    2. TF-IDF similarity with active task messages (30% weight)
    3. Recency bonus (15% weight)
    4. Tool call relevance (10% weight)
    5. Token efficiency (10% weight) — cheaper messages score higher

    Args:
        message: The message to score (pydantic-ai ModelMessage or dict).
        message_index: Index of the message in the full history.
        total_messages: Total number of messages in history.
        active_task_label: Human-readable label of the active task.
        active_task_messages: Messages tagged with the active task for comparison.
        token_estimate: Estimated token count for this message (0 = unknown).

    Returns:
        Relevance score between 0.0 and 1.0.
    """
    text = _extract_text(message)
    if not text:
        return 0.0

    # 1. Keyword overlap (35% weight)
    keyword_score = _compute_keyword_overlap(text, active_task_label)

    # 2. TF-IDF similarity with active task context (30% weight)
    tfidf_score = _compute_tfidf_similarity(text, active_task_messages)

    # 3. Recency bonus (15% weight) — more recent = more relevant
    recency_score = _compute_recency(message_index, total_messages)

    # 4. Tool call relevance (10% weight)
    tool_score = _compute_tool_relevance(message, active_task_label)

    # 5. Token efficiency (10% weight) — cheaper messages score higher
    token_eff_score = score_token_efficiency(token_estimate)

    # Weighted combination
    score = (
        keyword_score * 0.35
        + tfidf_score * 0.30
        + recency_score * 0.15
        + tool_score * 0.10
        + token_eff_score * 0.10
    )

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, score))


def score_batch_relevance(
    messages: list[Any],
    active_task_label: str,
    active_task_messages: list[Any] | None = None,
    token_estimates: list[int] | None = None,
) -> list[float]:
    """Score multiple messages in batch.

    More efficient than calling score_message_relevance individually
    as it can cache TF-IDF computations.

    Args:
        messages: List of messages to score.
        active_task_label: Human-readable label of the active task.
        active_task_messages: Messages tagged with the active task for comparison.
        token_estimates: Optional per-message token estimates (0 = unknown).
    """
    total = len(messages)
    results = []
    for idx, msg in enumerate(messages):
        tok = (
            token_estimates[idx]
            if token_estimates and idx < len(token_estimates)
            else 0
        )
        results.append(
            score_message_relevance(
                msg, idx, total, active_task_label, active_task_messages, tok
            )
        )
    return results


# ---------------------------------------------------------------------------
# Token efficiency scoring
# ---------------------------------------------------------------------------

# Weight carved out from existing factors for the new token-efficiency component
TOKEN_EFFICIENCY_WEIGHT = 0.10


def score_token_efficiency(token_estimate: int, avg_token_size: int = 500) -> float:
    """Score how token-efficient a message is.

    Large messages (tool returns, big file reads) are penalized so the
    scorer can factor in context cost, not just semantic relevance.

    Returns 0.0–1.0 where 1.0 = very small/cheap, 0.0 = very large/expensive.
    """
    if token_estimate <= 0:
        return 0.5  # Neutral for unknown size
    # Sigmoid-style penalty: around avg_token_size, score ~0.5
    # Very small (<100 tokens) → near 1.0; very large (>2000) → near 0.0
    ratio = token_estimate / avg_token_size
    return 1.0 / (1.0 + (ratio**1.5))


# ---------------------------------------------------------------------------
# Scoring components
# ---------------------------------------------------------------------------


def _compute_keyword_overlap(text: str, task_label: str) -> float:
    """Compute keyword overlap between message text and task label.

    Extracts meaningful keywords (nouns, verbs) from both and computes
    Jaccard similarity on the keyword sets.
    """
    if not task_label:
        return 0.3  # Neutral score when no label

    task_words = set(
        w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", task_label)
    )
    if not task_words:
        return 0.3

    message_words = set(
        w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text)
    )
    if not message_words:
        return 0.0

    intersection = task_words & message_words
    union = task_words | message_words

    if not union:
        return 0.0

    return len(intersection) / len(union)


def _compute_tfidf_similarity(
    text: str,
    active_task_messages: list[Any] | None,
) -> float:
    """Compute TF-IDF cosine similarity between message text and task messages.

    Uses character n-gram features (same as detector module) for fast comparison.
    """
    if not active_task_messages:
        return 0.3  # Neutral score when no context to compare

    task_texts = [_extract_text(m) for m in active_task_messages if _extract_text(m)]
    if not task_texts:
        return 0.3

    # Build combined task representation
    task_corpus = " ".join(task_texts)

    if not task_corpus.strip():
        return 0.3

    # Simple character n-gram overlap (fast approximation of TF-IDF)
    message_ngrams = _get_char_ngrams(text.lower(), n=3)
    task_ngrams = _get_char_ngrams(task_corpus.lower(), n=3)

    if not message_ngrams or not task_ngrams:
        return 0.0

    intersection = message_ngrams & task_ngrams
    union = message_ngrams | task_ngrams

    if not union:
        return 0.0

    jaccard = len(intersection) / len(union)
    return min(1.0, jaccard * 2.0)  # Scale up slightly


def _get_char_ngrams(text: str, n: int = 3) -> set[str]:
    """Extract character n-grams from text."""
    return {text[i : i + n] for i in range(max(0, len(text) - n + 1))}


def _compute_recency(message_index: int, total_messages: int) -> float:
    """Compute a recency bonus — more recent messages score higher.

    Uses a logarithmic decay: the last 20% of messages get most of the bonus.
    """
    if total_messages <= 1:
        return 1.0

    # Normalize position: 0.0 = oldest, 1.0 = newest
    position = message_index / (total_messages - 1)

    # Sigmoid-like curve: messages in the last 20% get high recency
    # score = 1 / (1 + e^(-10 * (position - 0.7)))
    raw = 1.0 / (1.0 + math.exp(-10.0 * (position - 0.7)))
    return raw


def _compute_tool_relevance(message: Any, task_label: str) -> float:
    """Check if a message contains tool calls related to the task goal.

    Tool calls matching task keywords get higher relevance.
    """
    parts = getattr(message, "parts", []) or []
    if not parts:
        return 0.0

    tool_names: list[str] = []
    for part in parts:
        tool_name = getattr(part, "tool_name", None)
        if tool_name:
            tool_names.append(tool_name)
        # Also check for tool_call_id which indicates a tool use
        if getattr(part, "tool_call_id", None):
            pass  # Tool was involved

    if not tool_names:
        return 0.0

    # If task label mentions specific operations, check tool matches
    if task_label:
        task_keywords = set(w.lower() for w in re.findall(r"[a-zA-Z]{2,}", task_label))
        for tool in tool_names:
            if any(kw in tool.lower() for kw in task_keywords):
                return 1.0

    return 0.5  # Generic tool use gets neutral score


# ---------------------------------------------------------------------------
# Embedding-based deep scoring (optional)
# ---------------------------------------------------------------------------


class EmbeddingScorer:
    """Optional deep relevance scorer using sentence embeddings.

    Requires sentence-transformers or onnxruntime to be installed.
    Enabled via config: task_embedding_enabled = true
    """

    def __init__(self) -> None:
        self._model = None
        self._model_name: str | None = None
        self._loaded = False

    @property
    def is_available(self) -> bool:
        """Check if embedding model is loaded and available."""
        return self._loaded and self._model is not None

    def load_model(self, model_name: str = "all-MiniLM-L6-v2") -> bool:
        """Load the embedding model.

        Uses the lightweight all-MiniLM-L6-v2 by default for faster loading.
        Can be configured to use bge-small-en-v1.5 for better quality.

        Returns True if loaded successfully, False otherwise.
        """
        if self._loaded and self._model_name == model_name:
            return True

        try:
            from sentence_transformers import SentenceTransformer

            logger.debug("Loading embedding model: %s", model_name)
            self._model = SentenceTransformer(model_name)
            self._model_name = model_name
            self._loaded = True
            logger.info("Embedding model loaded: %s", model_name)
            return True
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
            return False
        except Exception as exc:
            logger.error("Failed to load embedding model %s: %s", model_name, exc)
            return False

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Compute cosine similarity between two texts using embeddings.

        Returns 0.0–1.0 where 1.0 = semantically identical.
        Returns 0.0 if model is not loaded.
        """
        if not self.is_available:
            return 0.0

        try:
            embeddings = self._model.encode([text_a, text_b])
            vec_a, vec_b = embeddings[0], embeddings[1]
            dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
            norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
            norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
            return max(0.0, min(1.0, dot / (norm_a * norm_b)))
        except Exception as exc:
            logger.warning("Embedding similarity computation failed: %s", exc)
            return 0.0

    def score_message_embedding(
        self, message_text: str, task_context_text: str
    ) -> float:
        """Score a single message's embedding similarity to task context.

        Returns 0.0–1.0 relevance score based on semantic similarity.
        """
        if not self.is_available or not message_text or not task_context_text:
            return 0.0
        return self.compute_similarity(message_text, task_context_text)

    def score_batch_embedding(
        self, message_texts: list[str], task_context_text: str
    ) -> list[float]:
        """Score multiple messages in batch using embeddings."""
        if not self.is_available or not task_context_text:
            return [0.0] * len(message_texts)

        try:
            all_texts = [task_context_text] + message_texts
            embeddings = self._model.encode(all_texts)
            task_vec = embeddings[0]
            scores = []
            for msg_vec in embeddings[1:]:
                dot = sum(a * b for a, b in zip(task_vec, msg_vec, strict=False))
                norm_a = math.sqrt(sum(a * a for a in task_vec)) or 1.0
                norm_b = math.sqrt(sum(b * b for b in msg_vec)) or 1.0
                scores.append(max(0.0, min(1.0, dot / (norm_a * norm_b))))
            return scores
        except Exception as exc:
            logger.warning("Batch embedding scoring failed: %s", exc)
            return [0.0] * len(message_texts)


# Global singleton for the embedding scorer
_embedding_scorer = EmbeddingScorer()


def get_embedding_scorer() -> EmbeddingScorer:
    """Get or initialize the global embedding scorer.

    Only loads the model if task_embedding_enabled is True.
    """
    if get_task_embedding_enabled() and not _embedding_scorer.is_available:
        _embedding_scorer.load_model()
    return _embedding_scorer


# ---------------------------------------------------------------------------
# Text extraction helper (shared with detector)
# ---------------------------------------------------------------------------
