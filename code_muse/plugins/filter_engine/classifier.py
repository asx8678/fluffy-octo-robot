"""Command classifier for the filter engine.

Uses pre-compiled regex patterns to classify shell commands into categories
that determine which compression strategy is applied.
"""

import re
from typing import ClassVar


class CommandClassifier:
    """Classify shell commands into categories using regex patterns."""

    # Pre-compiled pattern sets for each category
    PATTERNS: ClassVar[dict[str, list[re.Pattern[str]]]] = {
        "git": [
            re.compile(r"^\s*git\s+status"),
            re.compile(r"^\s*git\s+log"),
            re.compile(r"^\s*git\s+diff"),
            re.compile(r"^\s*git\s+add"),
            re.compile(r"^\s*git\s+commit"),
            re.compile(r"^\s*git\s+push"),
            re.compile(r"^\s*git\s+pull"),
            re.compile(r"^\s*git\s+fetch"),
            re.compile(r"^\s*git\s+branch"),
            re.compile(r"^\s*git\s+checkout"),
            re.compile(r"^\s*git\s+merge"),
            re.compile(r"^\s*git\s+rebase"),
            re.compile(r"^\s*git\s+show"),
            re.compile(r"^\s*git\s+blame"),
            re.compile(r"^\s*git\s+stash"),
            re.compile(r"^\s*git\s+reset"),
            re.compile(r"^\s*git\s+tag"),
            re.compile(r"^\s*git\s+clone"),
            re.compile(r"^\s*git\s+init"),
            re.compile(r"^\s*git\s+remote"),
            re.compile(r"^\s*git\s+config"),
            re.compile(r"^\s*git\s+\S"),  # catch-all for any other git command
        ],
        "test": [
            re.compile(r"^\s*pytest\b"),
            re.compile(r"^\s*python\s+-m\s+pytest\b"),
            re.compile(r"^\s*vitest\b"),
            re.compile(r"^\s*jest\b"),
            re.compile(r"^\s*cargo\s+test\b"),
            re.compile(r"^\s*rspec\b"),
            re.compile(r"^\s*go\s+test\b"),
            re.compile(r"^\s*npm\s+test\b"),
            re.compile(r"^\s*yarn\s+test\b"),
            re.compile(r"^\s*npx\s+jest\b"),
            re.compile(r"^\s*npx\s+vitest\b"),
            re.compile(r"^\s*python\s+-m\s+unittest\b"),
            re.compile(r"^\s*mvn\s+test\b"),
            re.compile(r"^\s*gradle\s+test\b"),
            re.compile(r"^\s*tox\b"),
            re.compile(r"^\s*nox\b"),
        ],
        "lint": [
            re.compile(r"^\s*ruff\b"),
            re.compile(r"^\s*eslint\b"),
            re.compile(r"^\s*tsc\b"),
            re.compile(r"^\s*golangci-lint\b"),
            re.compile(r"^\s*rubocop\b"),
            re.compile(r"^\s*flake8\b"),
            re.compile(r"^\s*mypy\b"),
            re.compile(r"^\s*pyright\b"),
            re.compile(r"^\s*cargo\s+clippy\b"),
            re.compile(r"^\s*clippy\b"),
            re.compile(r"^\s*shellcheck\b"),
            re.compile(r"^\s*markdownlint\b"),
            re.compile(r"^\s*pylint\b"),
            re.compile(r"^\s*black\s+--check\b"),
            re.compile(r"^\s*isort\s+--check\b"),
            re.compile(r"^\s*prettier\s+--check\b"),
        ],
        "code": [
            re.compile(r"^\s*cat\b"),
            re.compile(r"^\s*head\b"),
            re.compile(r"^\s*tail\b"),
            re.compile(r"^\s*less\b"),
            re.compile(r"^\s*bat\b"),
            re.compile(r"^\s*nl\b"),
            re.compile(r"^\s*sed\b"),
            re.compile(r"^\s*awk\b"),
            re.compile(r"^\s*grep\b"),
            re.compile(r"^\s*rg\b"),
            re.compile(r"^\s*find\b"),
            re.compile(r"^\s*ls\b"),
            re.compile(r"^\s*tree\b"),
            re.compile(r"^\s*wc\b"),
            re.compile(r"^\s*sort\b"),
            re.compile(r"^\s*uniq\b"),
            re.compile(r"^\s*xargs\b"),
            re.compile(r"^\s*cut\b"),
            re.compile(r"^\s*tr\b"),
            re.compile(r"^\s*dd\b"),
            re.compile(r"^\s*diff\b"),
            re.compile(r"^\s*cmp\b"),
        ],
        "json": [
            re.compile(r"\.json\b"),
            re.compile(r"^\s*curl\b"),
            re.compile(r"^\s*wget\b"),
            re.compile(r"^\s*http\b"),
            re.compile(r"^\s*jq\b"),
            re.compile(r"^\s*python\s+-m\s+json\.tool\b"),
        ],
        "read": [
            re.compile(r"^\s*cat\b"),
            re.compile(r"^\s*head\b"),
            re.compile(r"^\s*tail\b"),
            re.compile(r"^\s*less\b"),
            re.compile(r"^\s*bat\b"),
        ],
    }

    @classmethod
    def classify(cls, command: str) -> str:
        """Classify a shell command into a category.

        Categories are checked in priority order: git, test, lint, json, read, code.
        The ``read`` category is a subset of ``code``; if a command matches both,
        it is classified as ``read`` because read is more specific.

        Args:
            command: The raw shell command string.

        Returns:
            One of ``git``, ``test``, ``lint``, ``json``, ``code``,
            ``read``, or ``unknown``.
        """
        if not command or not command.strip():
            return "unknown"

        stripped = command.strip()

        # Check git first (most specific)
        for pattern in cls.PATTERNS["git"]:
            if pattern.search(stripped):
                return "git"

        # Check test
        for pattern in cls.PATTERNS["test"]:
            if pattern.search(stripped):
                return "test"

        # Check lint
        for pattern in cls.PATTERNS["lint"]:
            if pattern.search(stripped):
                return "lint"

        # Check json (before read so `cat package.json` → json)
        for pattern in cls.PATTERNS["json"]:
            if pattern.search(stripped):
                return "json"

        # Check read (subset of code, checked before code)
        for pattern in cls.PATTERNS["read"]:
            if pattern.search(stripped):
                return "read"

        # Check code
        for pattern in cls.PATTERNS["code"]:
            if pattern.search(stripped):
                return "code"

        return "unknown"
