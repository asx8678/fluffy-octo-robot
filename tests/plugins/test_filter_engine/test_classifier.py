"""Tests for the command classifier."""

import pytest

from code_muse.plugins.filter_engine.classifier import CommandClassifier


class TestClassifierGit:
    """Git command classification."""

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git log --oneline",
            "git diff --stat",
            "git add file.py",
            "git commit -m 'fix'",
            "git push origin main",
            "git pull",
            "git fetch --all",
            "git branch -a",
            "git checkout feature/foo",
            "git merge main",
            "git rebase -i HEAD~3",
            "git stash list",
            "git reset --hard HEAD",
            "git tag v1.0",
            "git clone https://example.com/repo.git",
            "  git status",  # leading whitespace
        ],
    )
    def test_git_commands(self, command: str) -> None:
        assert CommandClassifier.classify(command) == "git"


class TestClassifierTest:
    """Test command classification."""

    @pytest.mark.parametrize(
        "command",
        [
            "pytest",
            "python -m pytest",
            "python -m pytest tests/",
            "vitest",
            "jest --watch",
            "cargo test",
            "rspec spec/models",
            "go test ./...",
            "npm test",
            "yarn test",
            "npx jest",
            "npx vitest",
            "python -m unittest discover",
            "mvn test",
            "gradle test",
            "tox",
            "nox",
        ],
    )
    def test_test_commands(self, command: str) -> None:
        assert CommandClassifier.classify(command) == "test"


class TestClassifierLint:
    """Lint command classification."""

    @pytest.mark.parametrize(
        "command",
        [
            "ruff check .",
            "eslint src/",
            "tsc --noEmit",
            "golangci-lint run",
            "rubocop",
            "flake8 app.py",
            "mypy src/",
            "pyright",
            "cargo clippy",
            "shellcheck script.sh",
            "markdownlint docs/",
            "pylint app.py",
            "black --check .",
            "isort --check .",
            "prettier --check .",
        ],
    )
    def test_lint_commands(self, command: str) -> None:
        assert CommandClassifier.classify(command) == "lint"


class TestClassifierCode:
    """Code / read command classification."""

    @pytest.mark.parametrize(
        "command,expected",
        [
            ("cat file.py", "read"),
            ("head -20 file.py", "read"),
            ("tail -f log.txt", "read"),
            ("less file.txt", "read"),
            ("bat file.py", "read"),
            ("sed 's/foo/bar/' file.py", "code"),
            ("awk '{print $1}' file.txt", "code"),
            ("grep -r TODO .", "code"),
            ("rg 'def ' src/", "code"),
            ("find . -name '*.py'", "code"),
            ("ls -la", "code"),
            ("tree", "code"),
            ("wc -l file.py", "code"),
            ("sort file.txt", "code"),
            ("uniq file.txt", "code"),
            ("xargs rm < files.txt", "code"),
            ("diff a.txt b.txt", "code"),
        ],
    )
    def test_code_and_read_commands(self, command: str, expected: str) -> None:
        assert CommandClassifier.classify(command) == expected


class TestClassifierUnknown:
    """Unknown command fallback."""

    @pytest.mark.parametrize(
        "command",
        [
            "",
            "   ",
            "make build",
            "docker ps",
            "kubectl get pods",
            "echo hello",
            "python script.py",
            "node server.js",
            "./run.sh",
        ],
    )
    def test_unknown_commands(self, command: str) -> None:
        assert CommandClassifier.classify(command) == "unknown"
