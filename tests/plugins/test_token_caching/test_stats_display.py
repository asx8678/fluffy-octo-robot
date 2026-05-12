"""Tests for stats_display.py."""

from code_muse.plugins.token_caching.cache_hit_tracking import (
    CacheUsage,
    SessionCacheStats,
)
from code_muse.plugins.token_caching.stats_display import format_cache_stats


def test_no_activity() -> None:
    stats = SessionCacheStats()
    assert format_cache_stats(stats) == "Cache: no activity this session"


def test_with_reads_and_writes() -> None:
    stats = SessionCacheStats()
    stats.record_usage(
        CacheUsage(
            cache_read_tokens=12_500,
            cache_write_tokens=1_200,
            input_tokens=3_500,
            output_tokens=800,
        )
    )
    text = format_cache_stats(stats)
    assert "12,500 tokens read" in text
    assert "1,200 tokens written" in text
    assert "hit rate 78.1%" in text
    assert "est. savings" in text


def test_only_writes() -> None:
    stats = SessionCacheStats()
    stats.record_usage(CacheUsage(cache_write_tokens=1_000, input_tokens=500))
    text = format_cache_stats(stats)
    assert "0 tokens read" in text
    assert "1,000 tokens written" in text
    assert "hit rate 0.0%" in text


def test_only_reads() -> None:
    stats = SessionCacheStats()
    stats.record_usage(CacheUsage(cache_read_tokens=5_000, input_tokens=0))
    text = format_cache_stats(stats)
    assert "5,000 tokens read" in text
    assert "0 tokens written" in text
    assert "hit rate 100.0%" in text
