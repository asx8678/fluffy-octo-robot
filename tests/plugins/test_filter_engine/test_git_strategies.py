"""Tests for git compression strategies."""

from code_muse.plugins.filter_engine.strategies.git import (
    compress_git_diff,
    compress_git_log,
    compress_git_mutation,
    compress_git_status,
)

from code_muse.plugins.filter_engine.verbosity import VerbosityLevel


class TestGitStatus:
    """``git status`` compression."""

    SAMPLE = (
        "## main...origin/main [ahead 2, behind 1]\n"
        " M modified.py\n"
        " A added.py\n"
        " D deleted.py\n"
        "?? untracked.py\n"
        "?? another_untracked.md\n"
    )

    def test_compact_summary(self) -> None:
        out = compress_git_status(self.SAMPLE, "", VerbosityLevel.COMPACT)
        assert out.success is True
        assert "branch:main" in out.stdout
        assert "↑2" in out.stdout
        assert "↓1" in out.stdout
        assert "M:1" in out.stdout or "M:" in out.stdout
        assert "A:1" in out.stdout or "A:" in out.stdout
        assert "D:1" in out.stdout or "D:" in out.stdout
        assert "??2" in out.stdout or "??" in out.stdout

    def test_verbose_includes_file_lists(self) -> None:
        out = compress_git_status(self.SAMPLE, "", VerbosityLevel.VERBOSE)
        assert "modified.py" in out.stdout
        assert "added.py" in out.stdout

    def test_no_branch_line(self) -> None:
        sample = " M file.py\n?? other.py\n"
        out = compress_git_status(sample, "", VerbosityLevel.COMPACT)
        assert "branch:unknown" in out.stdout

    def test_plain_format_on_branch(self) -> None:
        sample = (
            "On branch feature-x\n"
            "Your branch is ahead of 'origin/feature-x' by 3 commits.\n\n"
            "Changes to be committed:\n"
            '  (use "git restore --staged <file>..." to unstage)\n'
            "\tmodified:   src/core.py\n"
            "\tnew file:   src/helper.py\n\n"
            "Changes not staged for commit:\n"
            '  (use "git add <file>..." to update what will be committed)\n'
            "\tmodified:   README.md\n\n"
            "Untracked files:\n"
            '  (use "git add <file>..." to include in what will be committed)\n'
            "\tnotes.txt\n"
            "\tscratch/\n"
        )
        out = compress_git_status(sample, "", VerbosityLevel.COMPACT)
        assert out.success is True
        assert "branch:feature-x" in out.stdout
        assert "staged:2" in out.stdout
        assert "unstaged:1" in out.stdout
        assert "untracked:2" in out.stdout

    def test_plain_format_nothing_to_commit(self) -> None:
        sample = (
            "On branch main\n"
            "Your branch is up to date with 'origin/main'.\n\n"
            "nothing to commit, working tree clean\n"
        )
        out = compress_git_status(sample, "", VerbosityLevel.COMPACT)
        assert out.success is True
        assert "branch:main" in out.stdout
        assert "staged:0" in out.stdout
        assert "unstaged:0" in out.stdout
        assert "untracked:0" in out.stdout

    def test_plain_format_verbose_includes_raw(self) -> None:
        sample = "On branch main\nnothing to commit, working tree clean\n"
        out = compress_git_status(sample, "", VerbosityLevel.VERBOSE)
        assert "branch:main" in out.stdout
        assert "nothing to commit" in out.stdout


class TestGitLog:
    """``git log`` compression."""

    SAMPLE = (
        "abc1234 fix: bug in parser\n"
        "def5678 feat: new compression\n"
        "ghi9012 chore: deps\n"
    )

    def test_compact_summary(self) -> None:
        out = compress_git_log(self.SAMPLE, "", VerbosityLevel.COMPACT)
        assert "3 commits" in out.stdout
        assert "abc1234" in out.stdout
        assert "ghi9012" in out.stdout
        assert "fix: bug" in out.stdout

    def test_verbose_lists_all(self) -> None:
        out = compress_git_log(self.SAMPLE, "", VerbosityLevel.VERBOSE)
        assert "abc1234" in out.stdout
        assert "def5678" in out.stdout
        assert "ghi9012" in out.stdout

    def test_empty_log(self) -> None:
        out = compress_git_log("", "", VerbosityLevel.COMPACT)
        assert "0 commits" in out.stdout


class TestGitDiff:
    """``git diff`` compression."""

    STAT_SAMPLE = (
        " src/core.py | 10 ++++++----\n"
        " tests/test_core.py | 5 +++++\n"
        " README.md | 2 +-\n"
        " 3 files changed, 12 insertions(+), 5 deletions(-)\n"
    )

    RAW_SAMPLE = (
        "diff --git a/src/core.py b/src/core.py\n"
        "--- a/src/core.py\n"
        "+++ b/src/core.py\n"
        "@@ -1,3 +1,5 @@\n"
        "+def new_func():\n"
        "+    pass\n"
    )

    def test_stat_parsing(self) -> None:
        out = compress_git_diff(self.STAT_SAMPLE, "", VerbosityLevel.COMPACT)
        assert "3 files changed" in out.stdout
        assert "12 insertions(+)" in out.stdout
        assert "5 deletions(-)" in out.stdout

    def test_raw_diff_fallback(self) -> None:
        out = compress_git_diff(self.RAW_SAMPLE, "", VerbosityLevel.COMPACT)
        assert "files changed" in out.stdout

    def test_verbose_returns_full_diff(self) -> None:
        out = compress_git_diff(self.RAW_SAMPLE, "", VerbosityLevel.VERBOSE)
        assert out.stdout == self.RAW_SAMPLE


class TestGitMutation:
    """Mutating git command compression."""

    def test_success_with_hash(self) -> None:
        stdout = "[main abc1234] fix: bug\n 1 file changed, 2 insertions(+)\n"
        out = compress_git_mutation(stdout, "", VerbosityLevel.COMPACT)
        assert out.success is True
        assert "ok abc1234" in out.stdout

    def test_success_no_hash(self) -> None:
        out = compress_git_mutation("Everything up-to-date", "", VerbosityLevel.COMPACT)
        assert out.stdout == "ok"

    def test_error_detected(self) -> None:
        stderr = "error: merge conflict in file.py\n"
        out = compress_git_mutation("", stderr, VerbosityLevel.COMPACT)
        assert out.success is False
        assert "ERROR:" in out.stderr
        assert "merge conflict" in out.stderr

    def test_fatal_detected(self) -> None:
        stderr = "fatal: not a git repository\n"
        out = compress_git_mutation("", stderr, VerbosityLevel.COMPACT)
        assert out.success is False

    def test_verbose_includes_stdout(self) -> None:
        stdout = "[main abc1234] fix: bug\n"
        out = compress_git_mutation(stdout, "", VerbosityLevel.VERBOSE)
        assert "ok abc1234" in out.stdout
        assert "fix: bug" in out.stdout
