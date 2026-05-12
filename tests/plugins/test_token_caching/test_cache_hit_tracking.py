"""Tests for cache_hit_tracking.py."""

from code_muse.plugins.token_caching.cache_hit_tracking import (
    CacheUsage,
    SessionCacheStats,
    _session_stats,
    extract_cache_usage,
)


class TestExtractCacheUsage:
    def test_full_response(self) -> None:
        response = {
            "id": "msg_123",
            "type": "message",
            "usage": {
                "input_tokens": 1500,
                "output_tokens": 300,
                "cache_read_input_tokens": 1200,
                "cache_creation_input_tokens": 300,
            },
        }
        usage = extract_cache_usage(response)
        assert usage is not None
        assert usage.input_tokens == 1500
        assert usage.output_tokens == 300
        assert usage.cache_read_tokens == 1200
        assert usage.cache_write_tokens == 300

    def test_missing_cache_fields(self) -> None:
        response = {
            "usage": {
                "input_tokens": 500,
                "output_tokens": 100,
            },
        }
        usage = extract_cache_usage(response)
        assert usage is not None
        assert usage.cache_read_tokens == 0
        assert usage.cache_write_tokens == 0
        assert usage.input_tokens == 500
        assert usage.output_tokens == 100

    def test_no_usage_block(self) -> None:
        response = {"id": "msg_456", "type": "message"}
        assert extract_cache_usage(response) is None

    def test_non_dict_response(self) -> None:
        assert extract_cache_usage("not a dict") is None
        assert extract_cache_usage(None) is None

    def test_invalid_field_types(self) -> None:
        response = {
            "usage": {
                "input_tokens": "not_a_number",
                "cache_read_input_tokens": None,
            },
        }
        usage = extract_cache_usage(response)
        assert usage is not None
        assert usage.input_tokens == 0
        assert usage.cache_read_tokens == 0


class TestSessionCacheStats:
    def test_initial_state(self) -> None:
        stats = SessionCacheStats()
        assert stats.total_read_tokens == 0
        assert stats.total_write_tokens == 0
        assert stats.total_input_tokens == 0
        assert stats.total_output_tokens == 0
        assert stats.hit_rate == 0.0
        assert stats.estimated_savings_usd == 0.0

    def test_record_usage_accumulates(self) -> None:
        stats = SessionCacheStats()
        stats.record_usage(CacheUsage(cache_read_tokens=100, input_tokens=50))
        stats.record_usage(CacheUsage(cache_write_tokens=20, output_tokens=30))

        assert stats.total_read_tokens == 100
        assert stats.total_write_tokens == 20
        assert stats.total_input_tokens == 50
        assert stats.total_output_tokens == 30

    def test_hit_rate(self) -> None:
        stats = SessionCacheStats()
        assert stats.hit_rate == 0.0

        stats.record_usage(CacheUsage(cache_read_tokens=900, input_tokens=100))
        # 900 / (900 + 100) = 0.9
        assert stats.hit_rate == 0.9

    def test_hit_rate_zero_denominator(self) -> None:
        stats = SessionCacheStats()
        assert stats.hit_rate == 0.0

    def test_estimated_savings(self) -> None:
        stats = SessionCacheStats()

        # 1M read tokens, 0 write tokens
        stats.record_usage(
            CacheUsage(cache_read_tokens=1_000_000, cache_write_tokens=0)
        )
        # savings = 1_000_000 * 0.1 * (3/1M) - 0 = 0.30
        assert stats.estimated_savings_usd == 0.30

    def test_estimated_savings_with_write_cost(self) -> None:
        stats = SessionCacheStats()

        # 1M read, 200k write
        # savings = 1_000_000 * 0.1 * (3/1M) - 200_000 * 1.25 * (3/1M)
        #         = 0.30 - 0.75 = -0.45 → clamped to 0
        stats.record_usage(
            CacheUsage(cache_read_tokens=1_000_000, cache_write_tokens=200_000)
        )
        assert stats.estimated_savings_usd == 0.0

    def test_reset(self) -> None:
        stats = SessionCacheStats()
        stats.record_usage(CacheUsage(cache_read_tokens=100, input_tokens=50))
        stats.reset()
        assert stats.total_read_tokens == 0
        assert stats.total_input_tokens == 0
        assert stats.hit_rate == 0.0

    def test_thread_safety(self) -> None:
        import threading

        stats = SessionCacheStats()
        errors = []

        def worker() -> None:
            try:
                for _ in range(100):
                    stats.record_usage(
                        CacheUsage(
                            cache_read_tokens=1,
                            cache_write_tokens=1,
                            input_tokens=1,
                            output_tokens=1,
                        )
                    )
                    _ = stats.hit_rate
                    _ = stats.estimated_savings_usd
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert stats.total_read_tokens == 1000
        assert stats.total_write_tokens == 1000
        assert stats.total_input_tokens == 1000
        assert stats.total_output_tokens == 1000


class TestSessionStatsSingleton:
    def test_singleton_exists(self) -> None:
        assert isinstance(_session_stats, SessionCacheStats)

    def test_singleton_shared_state(self) -> None:
        # Reset before test to avoid cross-test pollution
        _session_stats.reset()
        _session_stats.record_usage(CacheUsage(cache_read_tokens=42))
        assert _session_stats.total_read_tokens == 42
        _session_stats.reset()
