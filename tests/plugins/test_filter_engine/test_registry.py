"""Tests for the strategy registry."""

from unittest.mock import MagicMock

from code_muse.plugins.filter_engine.registry import StrategyRegistry


class TestRegistryBasics:
    """Basic registration and retrieval."""

    def test_register_and_get(self) -> None:
        registry = StrategyRegistry()
        fn = MagicMock()
        registry.register("git", fn)
        assert registry.get_strategy("git") is fn

    def test_list_categories(self) -> None:
        registry = StrategyRegistry()
        assert "unknown" in registry.list_categories()
        fn = MagicMock()
        registry.register("git", fn)
        assert "git" in registry.list_categories()
        assert "unknown" in registry.list_categories()

    def test_get_unknown_category(self) -> None:
        registry = StrategyRegistry()
        assert registry.get_strategy("nonexistent") is None

    def test_passthrough_returns_none(self) -> None:
        registry = StrategyRegistry()
        passthrough = registry.get_strategy("unknown")
        assert passthrough is not None
        result = passthrough("cmd", "out", "err", 0, None)
        assert result is None


class TestRegistryPriority:
    """Priority-based override behaviour."""

    def test_higher_priority_wins(self) -> None:
        registry = StrategyRegistry()
        fn1 = MagicMock()
        fn2 = MagicMock()
        registry.register("git", fn1, priority=0)
        registry.register("git", fn2, priority=1)
        assert registry.get_strategy("git") is fn2

    def test_lower_priority_ignored(self) -> None:
        registry = StrategyRegistry()
        fn1 = MagicMock()
        fn2 = MagicMock()
        registry.register("git", fn1, priority=5)
        registry.register("git", fn2, priority=3)
        assert registry.get_strategy("git") is fn1

    def test_equal_priority_ignored(self) -> None:
        registry = StrategyRegistry()
        fn1 = MagicMock()
        fn2 = MagicMock()
        registry.register("git", fn1, priority=2)
        registry.register("git", fn2, priority=2)
        # First registration should win because equal priority is not >
        assert registry.get_strategy("git") is fn1
