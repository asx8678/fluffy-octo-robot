"""Comprehensive test coverage for http_utils.py.

Tests HTTP utilities including:
- Proxy configuration resolution
- SSL/TLS certificate handling
- HTTP/2 support detection
- Async client creation and configuration
- Rate limit handling and retries
- Environment variable processing
"""

import asyncio
import os
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from code_muse.http_utils import ProxyConfig


class TestProxyConfigClass:
    """Test ProxyConfig dataclass."""

    def test_proxy_config_creation(self):
        """Test creating a ProxyConfig instance."""
        config = ProxyConfig(
            verify=True,
            trust_env=False,
            proxy_url=None,
            disable_retry=False,
            http2_enabled=False,
        )
        assert config.verify is True
        assert config.trust_env is False
        assert config.proxy_url is None
        assert config.disable_retry is False
        assert config.http2_enabled is False

    def test_proxy_config_with_url(self):
        """Test ProxyConfig with proxy URL."""
        config = ProxyConfig(
            verify=True,
            trust_env=True,
            proxy_url="http://proxy.example.com:8080",
            disable_retry=False,
            http2_enabled=True,
        )
        assert config.proxy_url == "http://proxy.example.com:8080"
        assert config.trust_env is True
        assert config.http2_enabled is True

    def test_proxy_config_with_cert_path(self):
        """Test ProxyConfig with SSL certificate path."""
        config = ProxyConfig(
            verify="/path/to/ca-bundle.crt",
            trust_env=False,
            proxy_url=None,
            disable_retry=False,
            http2_enabled=False,
        )
        assert config.verify == "/path/to/ca-bundle.crt"

    def test_proxy_config_ssl_disabled(self):
        """Test ProxyConfig with SSL disabled."""
        config = ProxyConfig(
            verify=False,
            trust_env=False,
            proxy_url=None,
            disable_retry=False,
            http2_enabled=False,
        )
        assert config.verify is False


class TestResolveProxyConfig:
    """Test proxy configuration resolution."""

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_no_proxy_no_env(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test proxy resolution with no proxy environment variables."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            config = _resolve_proxy_config()
            assert config.proxy_url is None
            assert config.trust_env is False
            assert config.disable_retry is False

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_with_https_proxy(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test proxy resolution with HTTPS_PROXY environment variable."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = None

        with patch.dict(os.environ, {"HTTPS_PROXY": "https://proxy.example.com:3128"}):
            config = _resolve_proxy_config()
            assert config.proxy_url == "https://proxy.example.com:3128"
            assert config.trust_env is True

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_with_http_proxy(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test proxy resolution with HTTP_PROXY environment variable."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = None

        with patch.dict(os.environ, {"HTTP_PROXY": "http://proxy.example.com:3128"}):
            config = _resolve_proxy_config()
            assert config.proxy_url == "http://proxy.example.com:3128"
            assert config.trust_env is True

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_https_proxy_priority(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test HTTPS_PROXY has priority over HTTP_PROXY."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = None

        env_vars = {
            "HTTP_PROXY": "http://http-proxy.example.com:3128",
            "HTTPS_PROXY": "https://https-proxy.example.com:3128",
        }
        with patch.dict(os.environ, env_vars):
            config = _resolve_proxy_config()
            assert config.proxy_url == "https://https-proxy.example.com:3128"

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_lowercase_proxy_env_vars(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test lowercase proxy environment variables are recognized."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = None

        with patch.dict(os.environ, {"https_proxy": "https://proxy.example.com:3128"}):
            config = _resolve_proxy_config()
            assert config.proxy_url == "https://proxy.example.com:3128"

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_disable_retry_transport(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test disable retry transport flag does NOT disable TLS."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = "/path/to/ca-bundle.crt"

        with patch.dict(os.environ, {"MUSE_DISABLE_RETRY_TRANSPORT": "1"}):
            config = _resolve_proxy_config()
            assert config.disable_retry is True
            assert config.verify == "/path/to/ca-bundle.crt"  # TLS still on

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_disable_retry_transport_case_insensitive(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test disable retry transport flag is case insensitive."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = None

        for value in ["1", "true", "yes", "True", "YES"]:
            with patch.dict(os.environ, {"MUSE_DISABLE_RETRY_TRANSPORT": value}):
                config = _resolve_proxy_config()
                assert config.disable_retry is True

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_explicit_disable_tls_verify_sets_verify_false(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test MUSE_DISABLE_TLS_VERIFY explicitly disables TLS."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = "/path/to/ca-bundle.crt"

        with patch.dict(os.environ, {"MUSE_DISABLE_TLS_VERIFY": "1"}):
            config = _resolve_proxy_config()
            assert config.verify is False

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_proxy_env_sets_trust_env_without_disabling_verify(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test proxy env sets trust_env=True without touching verify."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = "/path/to/ca-bundle.crt"

        with patch.dict(
            os.environ,
            {"HTTPS_PROXY": "https://proxy.example.com:3128"},
        ):
            config = _resolve_proxy_config()
            assert config.trust_env is True
            assert config.proxy_url == "https://proxy.example.com:3128"
            assert config.verify == "/path/to/ca-bundle.crt"

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_http2_enabled(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test HTTP/2 enabled flag."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = True
        mock_get_cert.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            config = _resolve_proxy_config()
            assert config.http2_enabled is True

    @patch("code_muse.http_utils.get_cert_bundle_path")
    @patch("code_muse.http_utils.get_http2")
    def test_resolve_custom_verify_path(
        self,
        mock_get_http2,
        mock_get_cert,
    ):
        """Test custom certificate bundle path."""
        from code_muse.http_utils import _resolve_proxy_config

        mock_get_http2.return_value = False
        mock_get_cert.return_value = "/path/to/ca-bundle.crt"

        with patch.dict(os.environ, {}, clear=True):
            config = _resolve_proxy_config()
            assert config.verify == "/path/to/ca-bundle.crt"


class TestCreateAsyncClient:
    """Test async HTTP client creation."""

    @patch("code_muse.http_utils._resolve_proxy_config")
    def test_create_async_client_basic(
        self,
        mock_resolve_proxy,
    ):
        """Test basic async client creation."""
        from code_muse.http_utils import create_async_client

        mock_resolve_proxy.return_value = ProxyConfig(
            verify=True,
            trust_env=False,
            proxy_url=None,
            disable_retry=False,
            http2_enabled=False,
        )

        client = create_async_client()
        assert client is not None

    @patch("code_muse.http_utils._resolve_proxy_config")
    def test_create_async_client_with_headers(
        self,
        mock_resolve_proxy,
    ):
        """Test async client creation with custom headers."""
        from code_muse.http_utils import create_async_client

        mock_resolve_proxy.return_value = ProxyConfig(
            verify=True,
            trust_env=False,
            proxy_url=None,
            disable_retry=False,
            http2_enabled=False,
        )

        headers = {"X-Custom-Header": "value"}
        client = create_async_client(headers=headers)
        assert client is not None

    @patch("code_muse.http_utils._resolve_proxy_config")
    def test_create_async_client_with_verify_false(
        self,
        mock_resolve_proxy,
    ):
        """Test async client creation with verify=False."""
        from code_muse.http_utils import create_async_client

        mock_resolve_proxy.return_value = ProxyConfig(
            verify=False,
            trust_env=False,
            proxy_url=None,
            disable_retry=False,
            http2_enabled=False,
        )

        client = create_async_client(verify=False)
        assert client is not None

    def test_creates_retrying_by_default(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("code_muse.http_utils.get_http2", return_value=False),
        ):
            from code_muse.http_utils import RetryingAsyncClient, create_async_client

            client = create_async_client()
            assert isinstance(client, RetryingAsyncClient)

    def test_creates_plain_when_retry_disabled(self):
        env = {"MUSE_DISABLE_RETRY_TRANSPORT": "1"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("code_muse.http_utils.get_http2", return_value=False),
        ):
            from code_muse.http_utils import RetryingAsyncClient, create_async_client

            client = create_async_client()
            assert not isinstance(client, RetryingAsyncClient)


class TestRetryingAsyncClientCerebras:
    """Test Cerebras-specific rate limit handling."""

    def test_cerebras_ignores_retry_headers(self):
        """Test that Cerebras models ignore Retry-After headers."""
        from code_muse.http_utils import RetryingAsyncClient

        # Cerebras model should ignore headers
        client = RetryingAsyncClient(model_name="cerebras-test-model")
        assert client._ignore_retry_headers is True
        assert "cerebras" in client.model_name

    def test_non_cerebras_uses_retry_headers(self):
        """Test that non-Cerebras models respect Retry-After headers."""
        from code_muse.http_utils import RetryingAsyncClient

        # Non-Cerebras model should use headers
        client = RetryingAsyncClient(model_name="gpt-4")
        assert client._ignore_retry_headers is False

        # Empty model name should also use headers
        client2 = RetryingAsyncClient()
        assert client2._ignore_retry_headers is False

    def test_cerebras_case_insensitive(self):
        """Test that Cerebras detection is case-insensitive."""
        from code_muse.http_utils import RetryingAsyncClient

        for name in [
            "cerebras-glm",
            "CEREBRAS-GLM",
            "Cerebras-test-model",
            "my-cerebras-model",
        ]:
            client = RetryingAsyncClient(model_name=name)
            assert client._ignore_retry_headers is True, f"Failed for {name}"


class TestFindAvailablePort:
    """Test port availability detection."""

    def test_find_available_port_returns_int(self):
        """Test find_available_port returns an integer."""
        from code_muse.http_utils import find_available_port

        port = find_available_port()
        assert isinstance(port, int)
        assert port > 0

    def test_find_available_port_in_valid_range(self):
        """Test find_available_port returns port in valid range."""
        from code_muse.http_utils import find_available_port

        port = find_available_port()
        assert 1024 <= port <= 65535  # Typical unprivileged port range

    def test_find_available_port_with_start_port(self):
        """Test find_available_port with start port."""
        from code_muse.http_utils import find_available_port

        port = find_available_port(start_port=8000)
        assert port >= 8000

    def test_find_available_port_multiple_calls(self):
        """Test multiple calls to find_available_port."""
        from code_muse.http_utils import find_available_port

        port1 = find_available_port()
        port2 = find_available_port()
        # Both should be valid ports
        assert isinstance(port1, int) and isinstance(port2, int)
        assert port1 > 0 and port2 > 0

    def test_finds_port(self):
        from code_muse.http_utils import find_available_port

        port = find_available_port(start_port=49000, end_port=49010)
        assert port is not None
        assert 49000 <= port <= 49010

    def test_returns_none_when_all_busy(self):
        from code_muse.http_utils import find_available_port

        # Use a very narrow range and bind to all ports
        socks = []
        try:
            for p in range(49900, 49903):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", p))
                socks.append(s)
            result = find_available_port(start_port=49900, end_port=49902)
            assert result is None
        finally:
            for s in socks:
                s.close()


class TestRetryingAsyncClient:
    @pytest.mark.anyio
    async def test_successful_request(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await client.send(MagicMock(spec=httpx.Request))
            assert result.status_code == 200

    @pytest.mark.anyio
    async def test_retry_on_429(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(max_retries=1)

        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.aclose = AsyncMock()

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200

        with (
            patch.object(
                httpx.AsyncClient,
                "send",
                new_callable=AsyncMock,
                side_effect=[resp_429, resp_200],
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await client.send(MagicMock(spec=httpx.Request))
            assert result.status_code == 200

    @pytest.mark.anyio
    async def test_retry_with_retry_after_header(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(max_retries=1)

        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "2"}
        resp_429.aclose = AsyncMock()

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200

        with (
            patch.object(
                httpx.AsyncClient,
                "send",
                new_callable=AsyncMock,
                side_effect=[resp_429, resp_200],
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await client.send(MagicMock(spec=httpx.Request))
            assert result.status_code == 200

    @pytest.mark.anyio
    async def test_retry_with_http_date_retry_after(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(max_retries=1)

        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "Thu, 01 Jan 2099 00:00:00 GMT"}
        resp_429.aclose = AsyncMock()

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200

        with (
            patch.object(
                httpx.AsyncClient,
                "send",
                new_callable=AsyncMock,
                side_effect=[resp_429, resp_200],
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await client.send(MagicMock(spec=httpx.Request))
            assert result.status_code == 200

    @pytest.mark.anyio
    async def test_retry_with_invalid_retry_after(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(max_retries=1)

        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "not-a-number-or-date"}
        resp_429.aclose = AsyncMock()

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200

        with (
            patch.object(
                httpx.AsyncClient,
                "send",
                new_callable=AsyncMock,
                side_effect=[resp_429, resp_200],
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await client.send(MagicMock(spec=httpx.Request))
            assert result.status_code == 200

    @pytest.mark.anyio
    async def test_exhausted_retries_returns_last_response(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(max_retries=1)

        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.aclose = AsyncMock()

        with (
            patch.object(
                httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp_429
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await client.send(MagicMock(spec=httpx.Request))
            assert result.status_code == 429

    @pytest.mark.anyio
    async def test_connection_error_retries(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(max_retries=1)

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200

        with (
            patch.object(
                httpx.AsyncClient,
                "send",
                new_callable=AsyncMock,
                side_effect=[httpx.ConnectError("fail"), resp_200],
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await client.send(MagicMock(spec=httpx.Request))
            assert result.status_code == 200

    @pytest.mark.anyio
    async def test_connection_error_exhausted(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(max_retries=0)

        with (
            patch.object(
                httpx.AsyncClient,
                "send",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("fail"),
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(httpx.ConnectError),
        ):
            await client.send(MagicMock(spec=httpx.Request))

    @pytest.mark.anyio
    async def test_non_retryable_exception_raises(self):
        from code_muse.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(max_retries=3)

        with (
            patch.object(
                httpx.AsyncClient,
                "send",
                new_callable=AsyncMock,
                side_effect=ValueError("bad"),
            ),
            pytest.raises(ValueError),
        ):
            await client.send(MagicMock(spec=httpx.Request))


class TestGetCertBundlePath:
    def test_returns_none_when_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            from code_muse.http_utils import get_cert_bundle_path

            assert get_cert_bundle_path() is None

    def test_returns_path_when_env_exists(self, tmp_path):
        cert_file = tmp_path / "cert.pem"
        cert_file.write_text("cert")
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(cert_file)}):
            from code_muse.http_utils import get_cert_bundle_path

            assert get_cert_bundle_path() == str(cert_file)

    def test_returns_none_when_env_path_missing(self):
        with patch.dict(os.environ, {"SSL_CERT_FILE": "/nonexistent/cert.pem"}):
            from code_muse.http_utils import get_cert_bundle_path

            assert get_cert_bundle_path() is None


class TestCreateClient:
    def test_create_client_default(self):
        with (
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("code_muse.http_utils.get_http2", return_value=False),
        ):
            from code_muse.http_utils import create_client

            client = create_client()
            assert isinstance(client, httpx.Client)
            client.close()

    def test_create_client_with_headers(self):
        with (
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("code_muse.http_utils.get_http2", return_value=False),
        ):
            from code_muse.http_utils import create_client

            client = create_client(headers={"X-Custom": "val"})
            assert isinstance(client, httpx.Client)
            client.close()


class TestCreateHttpxClient:
    def test_create_client_default(self):
        with (
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("httpx.Client") as mock_client,
        ):
            from code_muse.http_utils import create_httpx_client

            create_httpx_client()
            mock_client.assert_called_once_with(verify=None)

    def test_create_client_with_headers(self):
        with (
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("httpx.Client"),
        ):
            from code_muse.http_utils import create_httpx_client

            client = create_httpx_client(headers={"X-Key": "val"})
            client.headers.update.assert_called_once_with({"X-Key": "val"})

    def test_create_client_with_verify(self):
        with patch("httpx.Client") as mock_client:
            from code_muse.http_utils import create_httpx_client

            create_httpx_client(verify="/path/to/cert")
            mock_client.assert_called_once_with(verify="/path/to/cert")


class TestAuthHeaders:
    def test_create_auth_headers(self):
        from code_muse.http_utils import create_auth_headers

        headers = create_auth_headers("my-key")
        assert headers == {"Authorization": "Bearer my-key"}

    def test_create_auth_headers_custom_name(self):
        from code_muse.http_utils import create_auth_headers

        headers = create_auth_headers("key", "X-Api-Key")
        assert headers == {"X-Api-Key": "Bearer key"}


class TestResolveEnvVarInHeader:
    def test_resolves_env_vars(self):
        with patch.dict(os.environ, {"MY_KEY": "secret"}):
            from code_muse.http_utils import resolve_env_var_in_header

            result = resolve_env_var_in_header({"Authorization": "Bearer $MY_KEY"})
            assert result["Authorization"] == "Bearer secret"

    def test_passthrough_non_string(self):
        from code_muse.http_utils import resolve_env_var_in_header

        result = resolve_env_var_in_header({"key": 123})
        assert result["key"] == 123


class TestCreateReopenableAsyncClient:
    def test_with_reopenable_available(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("code_muse.http_utils.get_http2", return_value=False),
            patch("code_muse.http_utils.ReopenableAsyncClient") as mock_reopen,
        ):
            mock_reopen.return_value = MagicMock()
            from code_muse.http_utils import create_reopenable_async_client

            create_reopenable_async_client()
            mock_reopen.assert_called_once()

    def test_with_reopenable_none_falls_back(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("code_muse.http_utils.get_http2", return_value=False),
            patch("code_muse.http_utils.ReopenableAsyncClient", None),
        ):
            from code_muse.http_utils import (
                RetryingAsyncClient,
                create_reopenable_async_client,
            )

            client = create_reopenable_async_client()
            assert isinstance(client, RetryingAsyncClient)

    def test_with_reopenable_none_retry_disabled(self):
        env = {"MUSE_DISABLE_RETRY_TRANSPORT": "1"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("code_muse.http_utils.get_http2", return_value=False),
            patch("code_muse.http_utils.ReopenableAsyncClient", None),
        ):
            from code_muse.http_utils import (
                RetryingAsyncClient,
                create_reopenable_async_client,
            )

            client = create_reopenable_async_client()
            assert isinstance(client, httpx.AsyncClient)
            assert not isinstance(client, RetryingAsyncClient)

    def test_with_reopenable_retry_disabled(self):
        env = {"MUSE_DISABLE_RETRY_TRANSPORT": "1"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("code_muse.http_utils.get_cert_bundle_path", return_value=None),
            patch("code_muse.http_utils.get_http2", return_value=False),
            patch("code_muse.http_utils.ReopenableAsyncClient") as mock_reopen,
        ):
            mock_reopen.return_value = MagicMock()
            from code_muse.http_utils import create_reopenable_async_client

            create_reopenable_async_client()
            # Should not pass retry_status_codes/model_name
            call_kwargs = mock_reopen.call_args[1]
            assert "retry_status_codes" not in call_kwargs


class TestIsCertBundleAvailable:
    def test_returns_false_no_cert(self):
        with patch("code_muse.http_utils.get_cert_bundle_path", return_value=None):
            from code_muse.http_utils import is_cert_bundle_available

            assert is_cert_bundle_available() is False

    def test_returns_true_with_valid_cert(self, tmp_path):
        cert = tmp_path / "cert.pem"
        cert.write_text("cert")
        with patch("code_muse.http_utils.get_cert_bundle_path", return_value=str(cert)):
            from code_muse.http_utils import is_cert_bundle_available

            assert is_cert_bundle_available() is True

    def test_returns_false_with_directory(self, tmp_path):
        with patch(
            "code_muse.http_utils.get_cert_bundle_path", return_value=str(tmp_path)
        ):
            from code_muse.http_utils import is_cert_bundle_available

            assert is_cert_bundle_available() is False
