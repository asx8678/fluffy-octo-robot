# cython: language_level=3
"""BM25 relevance scorer for memory extraction.

Cythonized implementation — uses int ID vocabulary and typed loops
for performance. No external dependencies.
"""

import array
import math
import re


cdef class BM25Scorer:
    """BM25 relevance scoring for text chunks.

    Cythonized version: term lookups use int IDs via a vocabulary
    built during ``fit()``, and the inner scoring loop uses Cython
    type declarations for the math steps.
    """

    cdef public double k1
    cdef public double b
    cdef public double epsilon
    cdef int _doc_count
    cdef double _avgdl
    cdef list _idf
    cdef dict _vocabulary
    cdef list _corpus_tfs
    cdef list _corpus_docs
    cdef list _corpus_lens

    def __init__(
        self,
        double k1=1.5,
        double b=0.75,
        double epsilon=0.25,
    ):
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self._doc_count = 0
        self._avgdl = 0.0
        self._idf = None
        self._vocabulary = {}
        self._corpus_tfs = []
        self._corpus_docs = []
        self._corpus_lens = []

    def fit(self, documents):
        """Compute corpus statistics for IDF calculation.

        Args:
            documents: Full document collection (all chunks across all sessions).
        """
        self._doc_count = len(documents)
        tokenized = [self._tokenize(doc) for doc in documents]
        self._avgdl = sum(len(tokens) for tokens in tokenized) / max(self._doc_count, 1)

        # Build vocabulary: str -> int
        cdef dict vocab = {}
        cdef int vocab_idx = 0
        cdef list doc_tokens
        cdef str token
        for doc_tokens in tokenized:
            for token in doc_tokens:
                if token not in vocab:
                    vocab[token] = vocab_idx
                    vocab_idx += 1
        self._vocabulary = vocab
        cdef int vocab_size = vocab_idx

        # Document frequency per term ID
        cdef list df = [0] * vocab_size
        cdef set seen
        for doc_tokens in tokenized:
            seen = set(doc_tokens)
            for token in seen:
                df[vocab[token]] += 1

        # IDF array indexed by term ID
        cdef list idf = [0.0] * vocab_size
        cdef int freq
        cdef double idf_val
        cdef int i
        cdef int N = self._doc_count
        cdef double eps = self.epsilon
        for i in range(vocab_size):
            freq = df[i]
            idf_val = math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)
            if idf_val < eps:
                idf_val = eps
            idf[i] = idf_val
        self._idf = idf

        # Pre-build dense tf arrays for corpus documents
        cdef list corpus_tfs = []
        cdef object tf
        cdef int term_id
        for doc_tokens in tokenized:
            tf = array.array('i', [0]) * vocab_size
            for token in doc_tokens:
                term_id = vocab[token]
                tf[term_id] = tf[term_id] + 1
            corpus_tfs.append(tf)
        self._corpus_tfs = corpus_tfs
        self._corpus_docs = list(documents)
        self._corpus_lens = [len(doc_tokens) for doc_tokens in tokenized]

    def score(self, query, document):
        """Score a single document against a query.

        Args:
            query: The query/project context string.
            document: The document/chunk to score.

        Returns:
            BM25 score (higher = more relevant).
        """
        if self._idf is None:
            raise RuntimeError("Scorer not fitted. Call fit() first.")

        cdef list query_tokens = self._tokenize(query)
        cdef list doc_tokens = self._tokenize(document)
        cdef int doc_len = len(doc_tokens)

        # Build sparse tf dict using int IDs
        cdef dict tf_dict = {}
        cdef str token
        cdef int term_id
        cdef dict vocab = self._vocabulary
        for token in doc_tokens:
            term_id = vocab.get(token, -1)
            if term_id != -1:
                if term_id in tf_dict:
                    tf_dict[term_id] = tf_dict[term_id] + 1
                else:
                    tf_dict[term_id] = 1

        cdef double score = 0.0
        cdef double idf
        cdef int term_tf
        cdef double numerator, denominator
        cdef double k1 = self.k1
        cdef double b = self.b
        cdef double avgdl = self._avgdl
        cdef double epsilon = self.epsilon
        cdef list idf_arr = self._idf

        for token in query_tokens:
            term_id = vocab.get(token, -1)
            if term_id == -1:
                continue
            idf = idf_arr[term_id]
            term_tf = tf_dict.get(term_id, 0)
            if term_tf == 0:
                continue
            numerator = term_tf * (k1 + 1.0)
            denominator = term_tf + k1 * (1.0 - b + b * doc_len / avgdl)
            score += idf * numerator / denominator

        return score

    def score_batch(self, query, documents):
        """Score multiple documents against a query.

        Args:
            query: The query/project context.
            documents: List of document strings.

        Returns:
            List of scores, one per document.
        """
        cdef list results = []
        cdef str doc
        cdef dict corpus_lookup = {}
        cdef int i
        cdef int n_corpus = len(self._corpus_docs)
        cdef list query_tokens
        cdef object tf
        cdef int doc_len
        cdef double score
        cdef double idf
        cdef int term_tf
        cdef double numerator, denominator
        cdef double k1 = self.k1
        cdef double b = self.b
        cdef double avgdl = self._avgdl
        cdef double epsilon = self.epsilon
        cdef list idf_arr = self._idf
        cdef dict vocab = self._vocabulary
        cdef str token
        cdef int term_id

        for i in range(n_corpus):
            corpus_lookup[self._corpus_docs[i]] = i

        cdef int idx
        for doc in documents:
            idx = corpus_lookup.get(doc, -1)
            if idx != -1:
                # Fast path: reuse pre-built tf array from fit()
                query_tokens = self._tokenize(query)
                tf = self._corpus_tfs[idx]
                doc_len = self._corpus_lens[idx]
                score = 0.0
                for token in query_tokens:
                    term_id = vocab.get(token, -1)
                    if term_id == -1:
                        continue
                    idf = idf_arr[term_id]
                    term_tf = tf[term_id]
                    if term_tf == 0:
                        continue
                    numerator = term_tf * (k1 + 1.0)
                    denominator = term_tf + k1 * (1.0 - b + b * doc_len / avgdl)
                    score += idf * numerator / denominator
                results.append(score)
            else:
                results.append(self.score(query, doc))
        return results

    @staticmethod
    def _tokenize(text):
        """Simple tokenization: lowercase, split on whitespace + punctuation.

        Keeps tokens >= 2 characters to filter noise.
        """
        text = text.lower()
        tokens = re.findall(r"[a-z0-9]{2,}", text)
        return tokens


def select_top_chunks(
    chunks,
    scores,
    threshold=None,
    top_n=None,
    min_keep=3,
):
    """Select the most relevant chunks.

    Args:
        chunks: List of text chunks.
        scores: Corresponding relevance scores.
        threshold: Minimum score to include (absolute). If None, uses top_n.
        top_n: Number of top chunks to keep. If None, uses threshold.
        min_keep: Always keep at least this many chunks (prevents empty results).

    Returns:
        Selected chunks in original order.
    """
    if not chunks:
        return []

    # Pair chunks with scores and original indices
    indexed = list(enumerate(zip(chunks, scores)))

    if threshold is not None:
        # Filter by threshold
        kept = [(i, (c, s)) for i, (c, s) in indexed if s >= threshold]
        if len(kept) < min_keep:
            # Ensure minimum kept: take top by score
            sorted_by_score = sorted(indexed, key=lambda x: x[1][1], reverse=True)
            kept = sorted_by_score[:max(min_keep, min(len(chunks), min_keep))]
    elif top_n is not None:
        sorted_by_score = sorted(indexed, key=lambda x: x[1][1], reverse=True)
        kept = sorted_by_score[:max(top_n, min_keep)]
    else:
        # Default: keep top 30% or at least min_keep
        n = max(min_keep, len(chunks) // 3)
        sorted_by_score = sorted(indexed, key=lambda x: x[1][1], reverse=True)
        kept = sorted_by_score[:n]

    # Return in original order
    kept_sorted = sorted(kept, key=lambda x: x[0])
    return [chunk for _, (chunk, _) in kept_sorted]


def score_chunks_against_context(
    chunks,
    context,
    double k1=1.5,
    double b=0.75,
):
    """Convenience: fit scorer on chunks, score them against context.

    Uses chunks as the document corpus and context as the query.
    """
    scorer = BM25Scorer(k1=k1, b=b)
    scorer.fit(chunks)
    return scorer.score_batch(context, chunks)
