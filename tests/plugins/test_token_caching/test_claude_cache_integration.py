"""Tests for cache usage extraction in claude_cache_client.py."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from code_muse.claude_cache_client import ClaudeCacheAsyncClient
from code_muse.plugins.token_caching.cache_hit_tracking import _session_stats


class TestCacheExtractionInSendFlow:
    @pytest.fixture(autouse=True)
    def _reset_stats(self):
        _session_stats.reset()
        yield
        _session_stats.reset()

    @pytest.mark.asyncio
    async def test_extracts_cache_usage_on_messages_200(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}
        resp.aread = AsyncMock()
        resp.json.return_value = {
            "id": "msg_123",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 200,
                "cache_read_input_tokens": 800,
                "cache_creation_input_tokens": 200,
            },
        }

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request(
                "POST",
                "https://api.com/v1/messages",
                content=b'{"model": "claude-3"}',
            )
            result = await c.send(req)
            assert result.status_code == 200

        assert _session_stats.total_read_tokens == 800
        assert _session_stats.total_write_tokens == 200
        assert _session_stats.total_input_tokens == 1000
        assert _session_stats.total_output_tokens == 200

    @pytest.mark.asyncio
    async def test_no_extraction_on_non_messages_endpoint(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request("GET", "https://api.com/v1/models")
            result = await c.send(req)
            assert result.status_code == 200

        assert _session_stats.total_read_tokens == 0
        assert _session_stats.total_write_tokens == 0

    @pytest.mark.asyncio
    async def test_no_extraction_on_non_200(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 429
        resp.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request(
                "POST",
                "https://api.com/v1/messages",
                content=b'{"model": "claude-3"}',
            )
            result = await c.send(req)
            assert result.status_code == 429

        assert _session_stats.total_read_tokens == 0

    @pytest.mark.asyncio
    async def test_extraction_exception_swallowed(self):
        """If response.json() raises, cache extraction must not propagate."""
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}
        resp.aread = AsyncMock()
        resp.json.side_effect = ValueError("bad json")

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request(
                "POST",
                "https://api.com/v1/messages",
                content=b'{"model": "claude-3"}',
            )
            result = await c.send(req)
            assert result.status_code == 200

        assert _session_stats.total_read_tokens == 0

    @pytest.mark.asyncio
    async def test_extraction_no_usage_block(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}
        resp.aread = AsyncMock()
        resp.json.return_value = {"id": "msg_456", "type": "message"}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request(
                "POST",
                "https://api.com/v1/messages",
                content=b'{"model": "claude-3"}',
            )
            result = await c.send(req)
            assert result.status_code == 200

        assert _session_stats.total_read_tokens == 0
