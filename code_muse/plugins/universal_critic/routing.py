"""Task size estimation and routing logic for the Universal Critic workflow."""

import re

from code_muse.plugins.universal_critic.models import TaskMetadata

# ---------------------------------------------------------------------------
# Keyword sets for heuristic classification
# ---------------------------------------------------------------------------

_LARGE_KEYWORDS: frozenset[str] = frozenset(
    {
        "create",
        "build",
        "implement",
        "scaffold",
        "refactor",
        "feature",
        "module",
        "class",
        "function",
    }
)

_SMALL_KEYWORDS: frozenset[str] = frozenset(
    {
        "fix",
        "typo",
        "rename",
        "change",
        "update",
        "bump",
        "tweak",
    }
)

_NEW_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcreate\s+(?:a\s+)?(?:new\s+)?file", re.IGNORECASE),
    re.compile(r"\badd\s+(?:a\s+)?new\s+file", re.IGNORECASE),
    re.compile(r"\bnew\s+module\b", re.IGNORECASE),
    re.compile(r"\bscaffold\b", re.IGNORECASE),
)

_MULTI_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmulti[- ]?file\b", re.IGNORECASE),
    re.compile(r"\bacross\s+(?:multiple|several)\s+files?\b", re.IGNORECASE),
    re.compile(r"\bin\s+(?:multiple|several|both|all)\s+files?\b", re.IGNORECASE),
    re.compile(r"\brefactor\b", re.IGNORECASE),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def estimate_task_size(prompt: str) -> int:
    """Estimate how many lines of code a task will produce.

    Uses simple text heuristics on the prompt — keyword presence, code-block
    markers, and overall length.  Returns an integer >= 1 (never 0).
    """
    prompt_lower = prompt.lower()
    words = prompt_lower.split()

    # Base estimate from prompt length — longer prompts tend to mean bigger tasks
    line_estimate = max(1, len(prompt.splitlines()))

    # Code-block markers: each ``` pair implies a code block of substance
    code_block_count = prompt.count("```") // 2
    line_estimate += code_block_count * 5

    # Large-work keywords push the estimate up
    large_hits = sum(1 for kw in _LARGE_KEYWORDS if kw in words)
    line_estimate += large_hits * 4

    # Small-work keywords pull the estimate down
    small_hits = sum(1 for kw in _SMALL_KEYWORDS if kw in words)
    line_estimate = max(1, line_estimate - small_hits * 3)

    return line_estimate


def classify_complexity(prompt: str) -> str:
    """Classify task complexity as trivial / simple / moderate / complex."""
    prompt_lower = prompt.lower()
    words = prompt_lower.split()
    code_block_count = prompt.count("```") // 2
    prompt_lines = len(prompt.splitlines())

    has_large = any(kw in words for kw in _LARGE_KEYWORDS)
    has_small = any(kw in words for kw in _SMALL_KEYWORDS)

    # Trivial: only small keywords, no code blocks, very short
    if has_small and not has_large and code_block_count == 0 and prompt_lines <= 5:
        return "trivial"

    # Complex: multiple code blocks, long prompt, or structural keywords
    if code_block_count >= 2 or prompt_lines > 20 or has_large:
        return "complex"

    # Moderate: some code blocks or medium length
    if code_block_count >= 1 or prompt_lines > 10:
        return "moderate"

    # Simple: single small change, no code blocks, short
    return "simple"


def is_new_file_task(prompt: str) -> bool:
    """Return True if the task likely requires creating new files."""
    return any(pat.search(prompt) for pat in _NEW_FILE_PATTERNS)


def is_multi_file_task(prompt: str) -> bool:
    """Return True if the task likely spans multiple files."""
    return any(pat.search(prompt) for pat in _MULTI_FILE_PATTERNS)


def route_task(metadata: TaskMetadata) -> str:
    """Make the routing decision: light-coding-agent or heavy-coding-agent.

    Light agent: estimated ≤20 lines, not complex, no new file creation.
    Everything else goes to the heavy agent.
    """
    if (
        metadata.estimated_lines <= 20
        and metadata.estimated_complexity != "complex"
        and not metadata.has_new_file_creation
    ):
        return "light-coding-agent"
    return "heavy-coding-agent"
