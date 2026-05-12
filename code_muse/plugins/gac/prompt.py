"""Prompt building for the GAC plugin.

Constructs the full prompt (system instructions + git context + execution
instructions) that is sent to the agent when a ``/gac`` command is issued.
"""

from code_muse.plugins.gac.git_ops import (
    get_current_branch,
    get_diff_stat,
    get_git_status,
    get_repo_root,
    get_staged_diff,
)

GAC_SYSTEM_INSTRUCTIONS = """
<role>
You are an expert git commit message generator acting as GAC (Git Auto Commit).
Your task: analyze code changes, generate a conventional commit message,
then execute the commit using git shell commands.
</role>

<conventions>
You MUST start your commit message with a conventional commit prefix:
- feat: A new feature or functionality
- fix: A bug fix
- docs: Documentation only
- style: Code style/formatting (no logic change)
- refactor: Code restructuring (no behavior change)
- perf: Performance improvement
- test: Adding/modifying tests
- build: Build system/dependencies
- ci: CI configuration
- chore: Miscellaneous

Check file types FIRST:
- If ALL changes are docs (*.md, *.rst, *.txt in docs/, README*, CHANGELOG*), "
  "use 'docs:'
- If mixed, use the prefix for the PRIMARY purpose

FORMAT:
- First line: type: concise summary (present tense, max 50 chars ideal)
- Line 2: BLANK
- Lines 3+: bullet points explaining WHAT and WHY
- DO NOT use markdown headers, code blocks, or formatting
</conventions>

<examples>
Good:
feat: add OAuth2 integration with Google and GitHub
fix: resolve race condition in user session management
docs: add troubleshooting section for installation
refactor: extract validation logic into reusable utilities

Bad:
fix stuff
update code
WIP: still working on this
Fixed bug
</examples>
"""

EXECUTION_INSTRUCTIONS = """
<execution>
After generating the commit message, you MUST execute these shell commands:

STEP 1 — Stage all changes (if nothing is staged):
  git add -A

STEP 2 — Commit with the generated message:
  git commit -m "YOUR GENERATED MESSAGE"

{extra_steps}

CRITICAL:
- Use the EXACT commit message you generated. No modifications.
- Do NOT include reasoning, preamble, or explanations in your response — "
  "just the commit message and confirmation.
- If nothing to commit, report that.
</execution>
"""

EXECUTION_INSTRUCTIONS_PUSH = """
STEP 3 — Push to remote:
  git push
"""

EXECUTION_INSTRUCTIONS_BUMP = """
STEP 0 — Bump version FIRST (before staging):
  Find the version file (__version__.py, pyproject.toml, package.json, Cargo.toml, etc.)
  Determine the current version
  Increment the PATCH version (e.g., 1.2.3 → 1.2.4)
  Update the version file in place

STEP 1 — Stage the version change:
  git add <version_file>

STEP 2 — Commit the bump:
  git commit -m "chore: bump version to X.Y.Z"
"""


def build_gac_prompt(push: bool = False, bump: bool = False) -> str | None:
    """Build the full GAC prompt for the agent.

    Args:
        push: Include ``git push`` instructions.
        bump: Include version-bump instructions.

    Returns:
        The complete prompt string, or ``None`` when there is nothing to commit.
    """
    status = get_git_status()
    diff_stat = get_diff_stat()
    diff = get_staged_diff(context_lines=5)
    branch = get_current_branch()
    repo_root = get_repo_root()

    if not bump and not push and not diff and not diff_stat:
        return None

    extra_steps = ""
    if bump:
        extra_steps = EXECUTION_INSTRUCTIONS_BUMP
    if push:
        extra_steps = extra_steps + "\n" + EXECUTION_INSTRUCTIONS_PUSH

    execution = EXECUTION_INSTRUCTIONS.format(extra_steps=extra_steps)

    parts = [
        GAC_SYSTEM_INSTRUCTIONS.strip(),
        "",
        "--- Git context ---",
        f"Repository: {repo_root or 'unknown'}",
        f"Branch:     {branch or 'unknown'}",
        "",
        "<git_status>",
        status,
        "</git_status>",
        "",
        "<git_diff_stat>",
        diff_stat,
        "</git_diff_stat>",
        "",
        "<git_diff>",
        diff,
        "</git_diff>",
        "",
        execution.strip(),
    ]

    return "\n".join(parts)


def build_gac_prompt_for_message_only() -> str | None:
    """Build a prompt that only generates the commit message (no execution).

    Returns:
        The prompt string, or ``None`` when there is nothing to commit.
    """
    status = get_git_status()
    diff_stat = get_diff_stat()
    diff = get_staged_diff(context_lines=5)
    branch = get_current_branch()
    repo_root = get_repo_root()

    if not diff and not diff_stat:
        return None

    parts = [
        GAC_SYSTEM_INSTRUCTIONS.strip(),
        "",
        "--- Git context ---",
        f"Repository: {repo_root or 'unknown'}",
        f"Branch:     {branch or 'unknown'}",
        "",
        "<git_status>",
        status,
        "</git_status>",
        "",
        "<git_diff_stat>",
        diff_stat,
        "</git_diff_stat>",
        "",
        "<git_diff>",
        diff,
        "</git_diff>",
        "",
        "Generate ONLY the commit message. No shell commands. No preamble.",
    ]

    return "\n".join(parts)
