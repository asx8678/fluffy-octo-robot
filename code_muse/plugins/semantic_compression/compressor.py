"""Semantic Compression Engine.

Lossy text compression that removes predictable grammar while preserving
semantic payload.  LLMs reconstruct grammar from content words, so we
strip the glue and keep the meaning.

Rules are applied in tiers:
- Tier 1 (always safe): articles, copulas, filler phrases, intensifiers,
  complementizer "that"
- Tier 2 (aggressive): auxiliaries, modals (except must), pronouns,
  relative pronouns
- Structural: passive→active, nominalization→verb, redundant pairs,
  clause→modifier

Always preserved: nouns, main verbs, meaning-bearing modifiers, numbers,
uncertainty markers, negation, temporal markers, causality, requirements,
proper nouns, and technical terms.

Code blocks (``` fenced ```) are detected and left untouched.
"""

import re

# ---------------------------------------------------------------------------
# Tier 1 — always safe deletions
# ---------------------------------------------------------------------------

# Articles: a, an, the (standalone, word boundary)
_RE_ARTICLES = re.compile(r"\b(a|an|the)\b", re.IGNORECASE)

# Copulas: is, are, was, were, am, be, been, being
_RE_COPULAS = re.compile(r"\b(is|are|was|were|am|be|been|being)\b", re.IGNORECASE)

# Pure intensifiers: very, quite, rather, really, extremely, somewhat
_RE_INTENSIFIERS = re.compile(
    r"\b(very|quite|rather|really|extremely|somewhat)\b", re.IGNORECASE
)

# Filler phrase → replacement
_FILLER_PHRASES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to"),
    (re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "because"),
    (re.compile(r"\bin terms of\b", re.IGNORECASE), ""),
    (re.compile(r"\bin the process of\b", re.IGNORECASE), ""),
    (re.compile(r"\bin the context of\b", re.IGNORECASE), ""),
    (re.compile(r"\bit is worth noting that\b", re.IGNORECASE), ""),
    (re.compile(r"\bneedless to say\b", re.IGNORECASE), ""),
    (re.compile(r"\bwhat is called\b", re.IGNORECASE), ""),
    (re.compile(r"\bas a matter of fact\b", re.IGNORECASE), ""),
]

# Complementizer "that" after bridge verbs.
# Matches stems with regular -s/-ed/-ing plus common irregulars.
# e.g. "report/reports/reported/reporting that X" → "report X"
_BRIDGE_STEMS = (
    r"know|think|believe|say|see|find|show|note|ensure|suggest"
    r"|indicate|report|state|claim|argue|feel|suspect|realize"
    r"|learn|discover|remember|forget|understand|assume"
)
# Captures bridge verb (stem + optional -s/-ed/-ing, or irregular)
# Suffix handles regular -s/-ed/-ing and e-dropping -d (e.g. assume→assumed)
_RE_COMPLEMENTIZER = re.compile(
    rf"\b((?:{_BRIDGE_STEMS})(?:s|e?d|ing)?"
    r"|knew|thought|said|saw|seen|found|showed|shown"
    r"|felt|learnt|learnt|forgot|forgotten|understood"
    r")\s+that\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Tier 2 — aggressive (only when aggressive=True)
# ---------------------------------------------------------------------------

# Auxiliary verbs: have/has/had, do/does/did, will/would
_RE_AUXILIARIES = re.compile(
    r"\b(have|has|had|do|does|did|will|would)\b", re.IGNORECASE
)

# Modal verbs except "must"
_RE_MODALS = re.compile(r"\b(can|could|may|might|should)\b", re.IGNORECASE)

# Pronouns (subject/object, when referent is obvious)
_RE_PRONOUNS = re.compile(
    r"\b(it|this|that|these|those|he|she|they|him|her|them)\b",
    re.IGNORECASE,
)

# Relative pronouns
_RE_RELATIVES = re.compile(r"\b(which|that|who|whom)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Structural compression patterns
# ---------------------------------------------------------------------------

# Passive → active: "was eaten by dog" → "dog ate"
# Pattern captures: group 1 = past participle, group 2 = agent noun
# Handles regular -ed/-en and irregulars like made, gone, done, known
_PASSIVE_BY_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+"
    r"(\w+(?:ed|en|[dt]e?|wn|own))"
    r"\s+by\s+(?:the\s+)?(\w+)",
    re.IGNORECASE,
)

# Nominalization → verb (common patterns)
_NOMINALIZATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bmade? a decision\b", re.IGNORECASE), "decided"),
    (re.compile(r"\bmade? an? analysis\b", re.IGNORECASE), "analyzed"),
    (re.compile(r"\bgave? consideration\b", re.IGNORECASE), "considered"),
    (re.compile(r"\btook? into account\b", re.IGNORECASE), "considered"),
    (re.compile(r"\bmade? an? assessment\b", re.IGNORECASE), "assessed"),
    (re.compile(r"\bmade? an? evaluation\b", re.IGNORECASE), "evaluated"),
    (re.compile(r"\bmade? a recommendation\b", re.IGNORECASE), "recommended"),
    (re.compile(r"\bmade? an? observation\b", re.IGNORECASE), "observed"),
    (re.compile(r"\bmade? a prediction\b", re.IGNORECASE), "predicted"),
    (re.compile(r"\bmade? a statement\b", re.IGNORECASE), "stated"),
    (re.compile(r"\bgave? permission\b", re.IGNORECASE), "permitted"),
    (re.compile(r"\bconducted an? investigation\b", re.IGNORECASE), "investigated"),
    (re.compile(r"\bperformed an? analysis\b", re.IGNORECASE), "analyzed"),
    (re.compile(r"\btook? a look\b", re.IGNORECASE), "looked"),
    (re.compile(r"\breached a conclusion\b", re.IGNORECASE), "concluded"),
    (re.compile(r"\bcame to the conclusion\b", re.IGNORECASE), "concluded"),
    (re.compile(r"\bprovided an? explanation\b", re.IGNORECASE), "explained"),
]

# Redundant pairs → single
_REDUNDANT_PAIRS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\beach and every\b", re.IGNORECASE), "every"),
    (re.compile(r"\bfirst and foremost\b", re.IGNORECASE), "first"),
    (re.compile(r"\bbasic and fundamental\b", re.IGNORECASE), "fundamental"),
    (re.compile(r"\bnull and void\b", re.IGNORECASE), "void"),
    (re.compile(r"\btrue and accurate\b", re.IGNORECASE), "accurate"),
    (re.compile(r"\bfull and complete\b", re.IGNORECASE), "complete"),
    (re.compile(r"\bany and all\b", re.IGNORECASE), "all"),
    (re.compile(r"\bvarious and sundry\b", re.IGNORECASE), "various"),
]

# Clause → modifier: "anomaly that was reported" → "reported anomaly"
# Pattern: noun + relative pronoun + copula + past participle → past participle + noun
_CLAUSE_TO_MODIFIER_RE = re.compile(
    r"\b(\w+)\s+(?:that|which|who)\s+(?:is|are|was|were|be|been|being)\s+"
    r"(\w+(?:ed|en|[dt]e?|wn|own))\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Code block handling
# ---------------------------------------------------------------------------

# Fenced code blocks (``` ... ```) and inline code (` ... `)
_CODE_SEGMENT_RE = re.compile(r"```[\s\S]*?```|`[^`]+`")

# Quoted strings (double or single, with backslash-escape support)
# Protects JSON values, XML attributes, and other structured data.
_QUOTED_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\\\]|\\.)*\'')


def _split_code_blocks(text: str) -> list[tuple[bool, str]]:
    """Split *text* into (is_code, segment) tuples.

    Fenced code blocks (``` ... ```) and inline code (` ... `) are
    marked as code and left untouched.  Everything else is non-code
    and eligible for compression.
    """
    segments: list[tuple[bool, str]] = []
    pos = 0
    for match in _CODE_SEGMENT_RE.finditer(text):
        start = match.start()
        if start > pos:
            segments.append((False, text[pos:start]))
        segments.append((True, match.group()))
        pos = match.end()
    if pos < len(text):
        segments.append((False, text[pos:]))
    return segments


def _split_quoted_strings(text: str) -> list[tuple[bool, str]]:
    """Split *text* into (is_quoted, segment) tuples.

    Quoted strings (double or single, with escape support) are marked
    as quoted and left untouched.  Unquoted parts are eligible for
    compression.
    """
    segments: list[tuple[bool, str]] = []
    pos = 0
    for match in _QUOTED_STRING_RE.finditer(text):
        start = match.start()
        if start > pos:
            segments.append((False, text[pos:start]))
        segments.append((True, match.group()))
        pos = match.end()
    if pos < len(text):
        segments.append((False, text[pos:]))
    return segments


# ---------------------------------------------------------------------------
# Core compression pipeline
# ---------------------------------------------------------------------------


def compress_semantic(text: str, aggressive: bool = False) -> str:
    """Apply semantic compression to *text*.

    Parameters
    ----------
    text:
        The input text to compress.
    aggressive:
        If ``True``, also apply Tier 2 deletions (auxiliaries, modals,
        pronouns, relatives) in addition to Tier 1.

    Returns
    -------
    str
        The compressed text with code blocks preserved.
    """
    if not text or not text.strip():
        return text

    # Split into code and non-code segments
    segments = _split_code_blocks(text)

    result_parts: list[str] = []
    for is_code, segment in segments:
        if is_code:
            result_parts.append(segment)
        else:
            result_parts.append(_compress_segment(segment, aggressive))

    return "".join(result_parts)


def _compress_segment(segment: str, aggressive: bool) -> str:
    """Compress a single non-code text segment.

    Quoted strings (double/single) are detected and preserved verbatim.
    Only unquoted portions are eligible for compression.

    Order matters: structural transformations run *before* Tier 1
    deletions so patterns like passive→active can see the copulas
    before they are stripped.
    """
    # Protect quoted strings — only compress unquoted portions
    parts = _split_quoted_strings(segment)
    compressed_parts: list[str] = []
    for is_quoted, part in parts:
        if is_quoted:
            compressed_parts.append(part)
        else:
            compressed_parts.append(_apply_compression_rules(part, aggressive))
    return "".join(compressed_parts)


def _apply_compression_rules(s: str, aggressive: bool) -> str:
    """Apply all compression rules to an unquoted text fragment."""
    # --- Structural compression (before Tier 1) ---

    # Passive → active: "was eaten by dog" → "dog ate"
    s = _PASSIVE_BY_RE.sub(r"\2 \1", s)

    # Clause → modifier: "anomaly that was reported" → "reported anomaly"
    s = _CLAUSE_TO_MODIFIER_RE.sub(r"\2 \1", s)

    # Nominalizations → verb
    for pattern, replacement in _NOMINALIZATIONS:
        s = pattern.sub(replacement, s)

    # Redundant pairs → single
    for pattern, replacement in _REDUNDANT_PAIRS:
        s = pattern.sub(replacement, s)

    # --- Tier 1 (always safe deletions) ---

    # Filler phrases first (they may contain articles/copulas)
    for pattern, replacement in _FILLER_PHRASES:
        s = pattern.sub(replacement, s)

    # Complementizer "that" after bridge verbs
    s = _RE_COMPLEMENTIZER.sub(r"\1", s)

    # Articles
    s = _RE_ARTICLES.sub("", s)

    # Copulas (after structural pass, so passive→active already fired)
    s = _RE_COPULAS.sub("", s)

    # Pure intensifiers
    s = _RE_INTENSIFIERS.sub("", s)

    # --- Tier 2 (aggressive only) ---
    if aggressive:
        s = _RE_AUXILIARIES.sub("", s)
        s = _RE_MODALS.sub("", s)
        s = _RE_PRONOUNS.sub("", s)
        s = _RE_RELATIVES.sub("", s)

    # --- Post-processing ---

    # Collapse multiple spaces into one
    s = re.sub(r" {2,}", " ", s)

    # Remove space before punctuation
    s = re.sub(r" +([.,!?;:])", r"\1", s)

    # Remove leading/trailing whitespace per line
    lines = [ln.strip() for ln in s.splitlines()]
    s = "\n".join(ln for ln in lines if ln)

    # Collapse 3+ consecutive newlines into 2
    s = re.sub(r"\n{3,}", "\n\n", s)

    return s


# ---------------------------------------------------------------------------
# Convenience: compress known patterns in one shot
# ---------------------------------------------------------------------------


def compress_for_llm(text: str) -> str:
    """Compress text intended for LLM consumption (aggressive mode).

    Equivalent to ``compress_semantic(text, aggressive=True)``.
    """
    return compress_semantic(text, aggressive=True)


def compress_for_display(text: str) -> str:
    """Compress text for human display (safe mode only, Tier 1).

    Equivalent to ``compress_semantic(text, aggressive=False)``.
    """
    return compress_semantic(text, aggressive=False)
