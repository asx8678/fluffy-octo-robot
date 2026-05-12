"""Tests for cacheable_prefix_detection.py."""

from code_muse.plugins.token_caching.cacheable_prefix_detection import (
    detect_cache_breakpoint,
)


def test_empty_messages() -> None:
    assert detect_cache_breakpoint([]) == 0


def test_system_only() -> None:
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    assert detect_cache_breakpoint(messages) == 0


def test_system_and_user() -> None:
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    assert detect_cache_breakpoint(messages) == 0


def test_system_assistant_user() -> None:
    messages = [
        {"role": "system", "content": "Sys"},
        {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "Hello!"},
    ]
    assert detect_cache_breakpoint(messages) == 1


def test_multiple_static_prefixes() -> None:
    messages = [
        {"role": "system", "content": "Sys1"},
        {"role": "system", "content": "Sys2"},
        {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hey!"},
        {"role": "user", "content": "Bye!"},
    ]
    assert detect_cache_breakpoint(messages) == 2


def test_user_first() -> None:
    messages = [
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi!"},
    ]
    assert detect_cache_breakpoint(messages) == 0


def test_no_user_all_static() -> None:
    messages = [
        {"role": "system", "content": "Sys1"},
        {"role": "assistant", "content": "A1"},
        {"role": "assistant", "content": "A2"},
    ]
    assert detect_cache_breakpoint(messages) == 2


def test_non_dict_messages_ignored() -> None:
    """Messages without a 'role' key don't count as user messages."""
    messages = [
        {"content": "no role"},
        {"role": "user", "content": "Hello!"},
    ]
    assert detect_cache_breakpoint(messages) == 0
