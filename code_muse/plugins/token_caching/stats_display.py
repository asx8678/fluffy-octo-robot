"""Format cache stats for human and LLM display."""

from code_muse.plugins.token_caching.cache_hit_tracking import SessionCacheStats


def format_cache_stats(stats: SessionCacheStats) -> str:
    """Return a compact, human-readable summary of cache stats.

    Example:
        ``"Cache: 42 hits (12,500 tokens read) · 3 writes (1,200 tokens written) · hit rate 78.3% · est. savings $0.12"``

    If there has been no cache activity this session, returns:
        ``"Cache: no activity this session"``
    """
    reads = stats.total_read_tokens
    writes = stats.total_write_tokens
    hits = stats.hit_rate

    if reads == 0 and writes == 0:
        return "Cache: no activity this session"

    savings = stats.estimated_savings_usd

    # Format numbers with commas
    reads_str = f"{reads:,}"
    writes_str = f"{writes:,}"
    hit_rate_str = f"{hits * 100:.1f}%"
    savings_str = f"${savings:.2f}"

    return (
        f"Cache: {reads_str} tokens read"
        f" · {writes_str} tokens written"
        f" · hit rate {hit_rate_str}"
        f" · est. savings {savings_str}"
    )
