"""Tests for Universal Critic routing heuristics."""

from code_muse.plugins.universal_critic.models import TaskMetadata
from code_muse.plugins.universal_critic.routing import (
    classify_complexity,
    estimate_task_size,
    is_multi_file_task,
    is_new_file_task,
    route_task,
)

# ---------------------------------------------------------------------------
# estimate_task_size
# ---------------------------------------------------------------------------


class TestEstimateTaskSize:
    """Tests for estimate_task_size."""

    def test_empty_prompt_returns_at_least_one(self):
        assert estimate_task_size("") >= 1

    def test_short_prompt_returns_at_least_one(self):
        assert estimate_task_size("fix typo") >= 1

    def test_code_blocks_increase_estimate(self):
        without_blocks = estimate_task_size("create a function")
        with_blocks = estimate_task_size(
            "create a function:\n```python\ndef foo():\n    pass\n```"
        )
        assert with_blocks > without_blocks

    def test_large_keywords_increase_estimate(self):
        small = estimate_task_size("update the config")
        large = estimate_task_size("implement a new authentication module")
        assert large > small

    def test_small_keywords_keep_estimate_low(self):
        result = estimate_task_size("fix typo in README")
        assert result <= 5

    def test_never_returns_zero(self):
        assert estimate_task_size("") != 0
        assert estimate_task_size("a") != 0


# ---------------------------------------------------------------------------
# classify_complexity
# ---------------------------------------------------------------------------


class TestClassifyComplexity:
    """Tests for classify_complexity."""

    def test_short_small_keyword_is_trivial(self):
        assert classify_complexity("fix typo") == "trivial"

    def test_single_code_block_is_moderate_or_higher(self):
        prompt = "```python\ndef foo():\n    pass\n```"
        assert classify_complexity(prompt) in ("moderate", "complex")

    def test_multiple_code_blocks_and_keywords_is_complex(self):
        prompt = (
            "implement a new module:\n"
            "```python\nclass Foo:\n    pass\n```\n"
            "```python\ndef bar():\n    pass\n```"
        )
        assert classify_complexity(prompt) == "complex"

    def test_medium_prompt_no_blocks_is_simple(self):
        prompt = "update the version number in the config"
        assert classify_complexity(prompt) in ("simple", "trivial")

    def test_structural_keyword_is_complex(self):
        assert classify_complexity("implement OAuth2 support") == "complex"

    def test_valid_complexity_values(self):
        valid = {"trivial", "simple", "moderate", "complex"}
        for p in ["fix typo", "create module", "```py\nx=1\n```", ""]:
            assert classify_complexity(p) in valid


# ---------------------------------------------------------------------------
# is_new_file_task
# ---------------------------------------------------------------------------


class TestIsNewFileTask:
    """Tests for is_new_file_task."""

    def test_create_new_file(self):
        assert is_new_file_task("create a new file called foo.py") is True

    def test_add_new_module(self):
        assert is_new_file_task("add a new module") is True

    def test_update_existing_file(self):
        assert is_new_file_task("update existing file") is False

    def test_fix_bug(self):
        assert is_new_file_task("fix bug in bar.py") is False

    def test_scaffold_project(self):
        assert is_new_file_task("scaffold the project structure") is True


# ---------------------------------------------------------------------------
# is_multi_file_task
# ---------------------------------------------------------------------------


class TestIsMultiFileTask:
    """Tests for is_multi_file_task."""

    def test_across_multiple_files(self):
        assert is_multi_file_task("refactor across multiple files") is True

    def test_update_single_module(self):
        assert is_multi_file_task("update the foo module") is False

    def test_several_files(self):
        assert is_multi_file_task("implement feature in several files") is True

    def test_fix_typo_single_file(self):
        assert is_multi_file_task("fix typo in bar.py") is False

    def test_refactor_implies_multi_file(self):
        assert is_multi_file_task("refactor the authentication system") is True


# ---------------------------------------------------------------------------
# route_task
# ---------------------------------------------------------------------------


class TestRouteTask:
    """Tests for route_task."""

    def test_small_task_routes_to_light(self):
        meta = TaskMetadata(
            original_prompt="fix typo",
            estimated_lines=5,
            estimated_complexity="trivial",
            has_new_file_creation=False,
        )
        assert route_task(meta) == "light-coding-agent"

    def test_large_task_routes_to_heavy(self):
        meta = TaskMetadata(
            original_prompt="implement auth",
            estimated_lines=50,
            estimated_complexity="complex",
        )
        assert route_task(meta) == "heavy-coding-agent"

    def test_complex_routes_to_heavy(self):
        meta = TaskMetadata(
            original_prompt="refactor module",
            estimated_lines=10,
            estimated_complexity="complex",
            has_new_file_creation=False,
        )
        assert route_task(meta) == "heavy-coding-agent"

    def test_new_file_routes_to_heavy(self):
        meta = TaskMetadata(
            original_prompt="create new file",
            estimated_lines=8,
            estimated_complexity="simple",
            has_new_file_creation=True,
        )
        assert route_task(meta) == "heavy-coding-agent"

    def test_multi_file_routes_to_heavy(self):
        meta_heavy = TaskMetadata(
            original_prompt="update across files",
            estimated_lines=25,
            estimated_complexity="moderate",
            has_multi_file_changes=True,
        )
        assert route_task(meta_heavy) == "heavy-coding-agent"

    def test_boundary_exactly_20_is_light(self):
        meta = TaskMetadata(
            original_prompt="small tweak",
            estimated_lines=20,
            estimated_complexity="simple",
            has_new_file_creation=False,
        )
        assert route_task(meta) == "light-coding-agent"
