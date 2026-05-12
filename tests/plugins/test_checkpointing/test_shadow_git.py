"""Tests for shadow_git.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from code_muse.plugins.checkpointing.shadow_git import ShadowGit


def test_shadow_git_init_creates_repo(mock_project_root: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        sg = ShadowGit(str(mock_project_root))
        assert sg.repo_path.exists()
        mock_run.assert_called_once()


def test_shadow_git_init_skips_existing_repo(mock_project_root: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        sg = ShadowGit(str(mock_project_root))
        # second init should not call git init again
        mock_run.reset_mock()
        sg2 = ShadowGit(str(mock_project_root))
        assert sg2.repo_path == sg.repo_path
        mock_run.assert_not_called()


def test_create_checkpoint_success(mock_project_root: Path) -> None:
    with patch("subprocess.run") as mock_run:

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "add" in cmd or "commit" in cmd:
                m.stdout = ""
                m.stderr = ""
            elif "rev-parse" in cmd:
                m.stdout = "abc123def456\n"
                m.stderr = ""
            return m

        mock_run.side_effect = side_effect
        sg = ShadowGit(str(mock_project_root))
        commit = sg.create_checkpoint("write_file", ["foo.py"])
        assert commit == "abc123def456"


def test_create_checkpoint_git_add_failure(mock_project_root: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        sg = ShadowGit(str(mock_project_root))
        commit = sg.create_checkpoint("write_file", ["foo.py"])
        assert commit is None


def test_create_checkpoint_git_commit_nothing(mock_project_root: Path) -> None:
    with patch("subprocess.run") as mock_run:

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "add" in cmd:
                m.returncode = 0
                m.stdout = ""
                m.stderr = ""
            elif "commit" in cmd:
                m.returncode = 0
                m.stdout = "nothing to commit"
                m.stderr = ""
            elif "rev-parse" in cmd:
                m.returncode = 0
                m.stdout = "abc123\n"
                m.stderr = ""
            return m

        mock_run.side_effect = side_effect
        sg = ShadowGit(str(mock_project_root))
        commit = sg.create_checkpoint("write_file", ["foo.py"])
        assert commit == "abc123"


def test_create_checkpoint_exception(mock_project_root: Path) -> None:
    with patch("subprocess.run", side_effect=RuntimeError("boom")):
        sg = ShadowGit(str(mock_project_root))
        commit = sg.create_checkpoint("write_file", ["foo.py"])
        assert commit is None
