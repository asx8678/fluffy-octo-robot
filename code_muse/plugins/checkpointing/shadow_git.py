"""Shadow git repository for checkpointing file snapshots."""

import hashlib
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ShadowGit:
    """Manages a bare shadow git repository for project checkpointing."""

    def __init__(self, project_root: str) -> None:
        self.project_root = Path(project_root).resolve()
        project_hash = hashlib.sha256(str(self.project_root).encode()).hexdigest()
        self.repo_path = Path.home() / ".muse" / "history" / project_hash
        self._init_repo()

    def _init_repo(self) -> None:
        if not self.repo_path.exists():
            try:
                self.repo_path.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["git", "init", "--bare", str(self.repo_path)],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                logger.info(f"Initialized shadow git repo at {self.repo_path}")
            except Exception as exc:
                logger.warning(f"Failed to init shadow git repo: {exc}")

    def create_checkpoint(
        self, tool_name: str, affected_files: list[str] | None = None
    ) -> str | None:
        """Create a git checkpoint and return the commit hash."""
        timestamp = datetime.now(UTC).isoformat()
        message = f"checkpoint: {tool_name} {timestamp}"
        if affected_files:
            files_str = ", ".join(affected_files)
            message += f" ({files_str})"

        try:
            # Stage everything in the project root
            add_result = subprocess.run(
                ["git", "-C", str(self.project_root), "add", "-A"],
                capture_output=True,
                text=True,
            )
            if add_result.returncode != 0:
                logger.warning(f"git add failed: {add_result.stderr}")
                return None

            # Commit
            commit_result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "commit",
                    "--allow-empty",
                    "-m",
                    message,
                ],
                capture_output=True,
                text=True,
            )
            if commit_result.returncode != 0:
                # No changes to commit is acceptable
                if "nothing to commit" in commit_result.stdout.lower():
                    pass
                else:
                    logger.warning(f"git commit failed: {commit_result.stderr}")
                    return None

            # Get commit hash
            hash_result = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            commit_hash = hash_result.stdout.strip()
            logger.info(f"Created checkpoint {commit_hash} for {tool_name}")
            return commit_hash
        except Exception as exc:
            logger.warning(f"Checkpoint creation failed: {exc}")
            return None
