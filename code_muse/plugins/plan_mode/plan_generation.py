"""Plan document generation and persistence.

Produces markdown plan files with YAML front-matter and saves them to a
local ``plans/`` directory.
"""

from datetime import UTC, datetime
from pathlib import Path


def generate_plan_md(
    goal: str,
    research_notes: str,
    discussion: str,
    steps: list[str],
) -> str:
    """Generate a markdown plan document with YAML front-matter.

    Args:
        goal: Short title/summary of the plan.
        research_notes: Analysis and context gathered during planning.
        discussion: Reasoning and trade-offs considered.
        steps: Ordered list of implementation steps.

    Returns:
        A fully formatted markdown string.
    """
    ts = datetime.now(UTC).isoformat()
    numbered_steps = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
    return f"""---
goal: "{goal}"
created_at: "{ts}"
status: draft
---

# Plan: {goal}

## Analysis
{research_notes}

## Discussion
{discussion}

## Implementation Steps
{numbered_steps}

## Risks
- (placeholder)
"""


def save_plan(content: str, plans_dir: Path = Path("plans")) -> Path:
    """Save plan markdown to ``plans/plan_{timestamp}.md``.

    Creates the directory if it does not exist.

    Args:
        content: Markdown content to save.
        plans_dir: Target directory (default: ``plans/`` in cwd).

    Returns:
        The path to the written file.
    """
    plans_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = plans_dir / f"plan_{ts}.md"
    file_path.write_text(content, encoding="utf-8")
    return file_path
