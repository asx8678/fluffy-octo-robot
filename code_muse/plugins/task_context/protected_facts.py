"""Protected facts — user-anchored information that must survive compaction.

ProtectedFact dataclass and ProtectedFactManager that manages fact lifecycle,
budget enforcement (15% cap of context window), and integrates with
compaction bypass, semantic compression preservation, and truncation detection.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Default max budget fraction for protected facts (15% of context window)
_DEFAULT_PROTECTED_FACT_BUDGET_FRACTION = 0.15

# Max number of protected facts before eviction
_MAX_PROTECTED_FACTS = 50


@dataclass(frozen=True)
class ProtectedFact:
    """A single user-anchored fact that must survive compaction and summarization.

    Attributes:
        content: The exact fact text (e.g. "Name: Amina" or "Budget: 4500 MAD").
        category: Category like "name", "date", "budget", "constraint", "preference".
        priority: Priority level (0=critical, 1=high, 2=normal, 3=low).
        token_cost: Estimated token cost of this fact in the context window.
        source_turn: Optional turn number where this fact was established.
        immutable: If True, cannot be evicted (reserved for system-injected facts).
    """

    content: str
    category: str = "general"
    priority: int = 2
    token_cost: int = 0
    source_turn: int | None = None
    immutable: bool = False


class ProtectedFactManager:
    """Manages lifecycle of protected facts.

    Handles:
    - Adding/removing facts
    - Budget enforcement (15% of context window max)
    - Priority-based eviction when budget exceeded
    - Serialization for integration with compaction and summarization
    """

    def __init__(
        self,
        budget_fraction: float = _DEFAULT_PROTECTED_FACT_BUDGET_FRACTION,
    ):
        self._facts: dict[str, ProtectedFact] = {}  # keyed by content hash for dedup
        self._budget_fraction = budget_fraction
        self._context_window: int = 128_000  # updated via update_context_window

    def update_context_window(self, context_window: int) -> None:
        """Update the context window size for budget calculations."""
        if context_window > 0:
            self._context_window = context_window

    @property
    def max_budget_tokens(self) -> int:
        """Maximum tokens allowed for protected facts."""
        return max(512, int(self._context_window * self._budget_fraction))

    @property
    def used_tokens(self) -> int:
        """Current token usage of all protected facts."""
        return sum(f.token_cost for f in self._facts.values())

    @property
    def budget_remaining(self) -> int:
        """Remaining token budget for protected facts."""
        return max(0, self.max_budget_tokens - self.used_tokens)

    @property
    def budget_used_pct(self) -> float:
        """Percentage of budget used."""
        if self.max_budget_tokens <= 0:
            return 0.0
        return self.used_tokens / self.max_budget_tokens

    def add_fact(self, fact: ProtectedFact) -> tuple[bool, str | None]:
        """Add a protected fact. Returns (success, eviction_warning).

        If budget would be exceeded, evicts lowest-priority non-immutable facts
        first, then oldest if still over budget.
        """
        from code_muse.agents._history import estimate_tokens

        # Calculate token cost if not provided
        if fact.token_cost <= 0:
            token_cost = estimate_tokens(fact.content)
            fact = ProtectedFact(
                content=fact.content,
                category=fact.category,
                priority=fact.priority,
                token_cost=max(1, token_cost),
                source_turn=fact.source_turn,
                immutable=fact.immutable,
            )

        # Generate key from content hash
        content_key = _fact_content_key(fact.content)

        # Dedup: if already exists, update priority if higher
        if content_key in self._facts:
            existing = self._facts[content_key]
            if fact.priority < existing.priority:  # lower number = higher priority
                self._facts[content_key] = fact
            return True, None

        # Check if we can fit within budget
        if self.used_tokens + fact.token_cost > self.max_budget_tokens:
            evicted = self._evict_to_make_room(fact.token_cost)
            if evicted is None:
                logger.warning(
                    "Cannot add protected fact '%s': "
                    "budget exhausted and cannot evict.",
                    fact.content[:50],
                )
                return (
                    False,
                    "Protected fact budget exhausted. "
                    "Increase budget or evict lower-priority facts.",
                )

        # Check max count
        if len(self._facts) >= _MAX_PROTECTED_FACTS:
            # Try to evict lowest-priority non-immutable
            evict_candidates = [
                (k, f) for k, f in self._facts.items() if not f.immutable
            ]
            if not evict_candidates:
                return (
                    False,
                    "Maximum protected fact count reached with all immutable facts.",
                )
            # Evict lowest priority (highest number)
            evict_candidates.sort(key=lambda x: (-x[1].priority, x[1].token_cost))
            to_evict = evict_candidates[0][0]
            del self._facts[to_evict]
            logger.info(
                "Evicted protected fact to maintain max count: %s",
                to_evict[:40],
            )

        self._facts[content_key] = fact
        logger.debug(
            "Added protected fact: %s (category=%s, priority=%d)",
            fact.content[:50],
            fact.category,
            fact.priority,
        )
        return True, None

    def _evict_to_make_room(self, needed_tokens: int) -> str | None:
        """Evict lowest-priority non-immutable facts to free `needed_tokens`.

        Returns the content key of the first evicted fact for dedup, or None if
        not enough can be freed.
        """
        evictable = [(k, f) for k, f in self._facts.items() if not f.immutable]
        evictable.sort(key=lambda x: (-x[1].priority, x[1].token_cost))

        freed = 0
        evicted_key = None
        for key, fact in evictable:
            if freed >= needed_tokens:
                break
            freed += fact.token_cost
            del self._facts[key]
            if evicted_key is None:
                evicted_key = key
            logger.info(
                "Evicted protected fact: %s (priority=%d)",
                fact.content[:50],
                fact.priority,
            )

        if freed < needed_tokens:
            return None
        return evicted_key

    def remove_fact(self, content: str) -> bool:
        """Remove a protected fact by content. Returns True if found and removed."""
        key = _fact_content_key(content)
        if key in self._facts:
            del self._facts[key]
            return True
        return False

    def get_all_facts(self) -> list[ProtectedFact]:
        """Get all protected facts, sorted by priority then insertion order."""
        return list(self._facts.values())

    def get_facts_by_category(self, category: str) -> list[ProtectedFact]:
        """Get protected facts for a specific category."""
        return [f for f in self._facts.values() if f.category == category]

    def get_prompt_block(self) -> str | None:
        """Return a formatted block of facts to inject into system prompt,
        or None if no facts exist.
        """
        if not self._facts:
            return None
        lines = []
        for fact in self.get_all_facts():
            lines.append(f"- [{fact.category}] {fact.content}")

        if not lines:
            return None

        budget_pct = self.budget_used_pct * 100
        header = f"\n## Protected User Facts (budget: {budget_pct:.0f}% used)\n"
        return header + "\n".join(lines)

    def clear(self) -> None:
        """Clear all non-immutable protected facts."""
        self._facts = {k: f for k, f in self._facts.items() if f.immutable}

    def has_fact(self, content: str) -> bool:
        """Check if a fact exists by content."""
        return _fact_content_key(content) in self._facts


def _fact_content_key(content: str) -> str:
    """Generate a stable key for deduplication."""
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _extract_message_text(message: Any) -> str:
    """Extract all text from a message for content matching."""
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


# Module-level singleton
_fact_manager: ProtectedFactManager | None = None


def get_protected_fact_manager() -> ProtectedFactManager:
    """Get the singleton ProtectedFactManager."""
    global _fact_manager
    if _fact_manager is None:
        _fact_manager = ProtectedFactManager()
    return _fact_manager


def reset_protected_fact_manager() -> None:
    """Reset the singleton (useful in tests)."""
    global _fact_manager
    _fact_manager = None
