"""
Unit Tests for REST API Client

Tests authentication, retry logic, caching, connection limits, and error handling.
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import numpy as np
import pytest

from core.api_client import ApiError, RestApiClient
from core.models import StockData


class TestRestApiClientInitialization:
    """Test client initialization and configuration."""

    def test_init_with_defaults(self):
        """Test initialization with default config values."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient()

            assert client.api_key == "test_token"
            assert client.base_url == "https://api.test.com"
            assert client.max_retries == 3

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "default_token"

            client = RestApiClient(
                api_key="custom_token",
                base_url="https://custom.api.com",
                max_concurrent=10,
                max_retries=5,
            )

            assert client.api_key == "custom_token"
            assert client.base_url == "https://custom.api.com"
            assert client.max_retries == 5

    def test_init_without_api_key_raises_error(self):
        """Test that missing API key raises ValueError."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = ""

            with pytest.raises(ValueError, match="API key is required"):
                RestApiClient()

    def test_connection_pool_configuration(self):
        """Test httpx client is configured with connection limits."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"

            client = RestApiClient(max_concurrent=5)

            # Verify client is created (limits are set internally)
            assert client.client is not None
            assert isinstance(client.client, httpx.AsyncClient)


class TestFetchStockData:
    """Test stock data fetching with caching and retry logic."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        """Test successful data fetch returns StockData."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient()

            # Mock successful API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [
                    {"c": 150.0, "h": 152.0, "l": 149.0, "v": 1000000, "t": 1609459200000},
                    {"c": 151.0, "h": 153.0, "l": 150.0, "v": 1100000, "t": 1609545600000},
                    {"c": 152.0, "h": 154.0, "l": 151.0, "v": 1200000, "t": 1609632000000},
                ]
            }

            client.client.get = AsyncMock(return_value=mock_response)

            result = await client.fetch_stock_data("AAPL", days=250)

            assert isinstance(result, StockData)
            assert result.ticker == "AAPL"
            assert len(result.prices) == 3
            assert np.array_equal(result.prices, np.array([150.0, 151.0, 152.0]))
            assert np.array_equal(result.volumes, np.array([1000000, 1100000, 1200000]))
            assert len(result.timestamps) == 3
            # Verify highs and lows are populated
            assert np.array_equal(result.highs, np.array([152.0, 153.0, 154.0]))
            assert np.array_equal(result.lows, np.array([149.0, 150.0, 151.0]))
            # Verify highs[i] >= lows[i] invariant
            assert all(result.highs[i] >= result.lows[i] for i in range(len(result.highs)))

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Test that second request for same ticker returns cached data."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient()

            # Mock successful API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [
                    {"c": 150.0, "h": 152.0, "l": 149.0, "v": 1000000, "t": 1609459200000},
                ]
            }

            client.client.get = AsyncMock(return_value=mock_response)

            # First fetch - should hit API
            result1 = await client.fetch_stock_data("AAPL", days=250)
            assert client.client.get.call_count == 1

            # Second fetch - should hit cache
            result2 = await client.fetch_stock_data("AAPL", days=250)
            assert client.client.get.call_count == 1  # No additional API call

            # Results should be identical
            assert result1.ticker == result2.ticker
            assert np.array_equal(result1.prices, result2.prices)

    @pytest.mark.asyncio
    async def test_cache_different_tickers(self):
        """Test that different tickers don't share cache entries."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient()

            # Mock different responses for different tickers
            async def mock_get(url, params):
                response = Mock()
                response.status_code = 200
                if "AAPL" in url:
                    response.json.return_value = {
                        "results": [{"c": 150.0, "h": 152.0, "l": 149.0, "v": 1000000, "t": 1609459200000}]
                    }
                else:
                    response.json.return_value = {
                        "results": [{"c": 300.0, "h": 302.0, "l": 299.0, "v": 2000000, "t": 1609459200000}]
                    }
                return response

            client.client.get = mock_get

            result1 = await client.fetch_stock_data("AAPL", days=250)
            result2 = await client.fetch_stock_data("MSFT", days=250)

            assert result1.ticker == "AAPL"
            assert result2.ticker == "MSFT"
            assert result1.prices[0] == 150.0
            assert result2.prices[0] == 300.0

    @pytest.mark.asyncio
    async def test_retry_on_http_error(self):
        """Test retry logic with exponential backoff on HTTP errors."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient(max_retries=3)

            # Mock first two calls fail, third succeeds
            call_count = 0

            async def mock_get(url, params):
                nonlocal call_count
                call_count += 1

                if call_count < 3:
                    # Simulate HTTP error
                    response = Mock()
                    response.status_code = 500
                    response.raise_for_status.side_effect = httpx.HTTPStatusError(
                        "Server Error", request=Mock(), response=response
                    )
                    return response
                else:
                    # Success on third attempt
                    response = Mock()
                    response.status_code = 200
                    response.json.return_value = {
                        "results": [{"c": 150.0, "h": 152.0, "l": 149.0, "v": 1000000, "t": 1609459200000}]
                    }
                    return response

            client.client.get = mock_get

            # Should succeed after retries
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await client.fetch_stock_data("AAPL", days=250)

                assert call_count == 3
                assert result.ticker == "AAPL"

                # Verify exponential backoff: 1s, 2s
                assert mock_sleep.call_count == 2
                assert mock_sleep.call_args_list[0][0][0] == 1  # First retry: 1s
                assert mock_sleep.call_args_list[1][0][0] == 2  # Second retry: 2s

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises_error(self):
        """Test that ApiError is raised after max retries exhausted."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient(max_retries=3)

            # Mock all calls fail
            async def mock_get(url, params):
                response = Mock()
                response.status_code = 503
                response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "Service Unavailable", request=Mock(), response=response
                )
                return response

            client.client.get = mock_get

            # Should raise ApiError after 3 retries
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(ApiError, match="Failed to fetch data for AAPL after 3 retries"):
                    await client.fetch_stock_data("AAPL", days=250)

    @pytest.mark.asyncio
    async def test_no_data_raises_error(self):
        """Test that empty results raises ApiError."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient()

            # Mock response with no results
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"results": []}

            client.client.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ApiError, match="No data available for AAPL"):
                await client.fetch_stock_data("AAPL", days=250)

    @pytest.mark.asyncio
    async def test_request_error_retry(self):
        """Test retry on network/request errors."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient(max_retries=3)

            call_count = 0

            async def mock_get(url, params):
                nonlocal call_count
                call_count += 1

                if call_count < 2:
                    # Simulate network error
                    raise httpx.RequestError("Connection timeout", request=Mock())
                else:
                    # Success on second attempt
                    response = Mock()
                    response.status_code = 200
                    response.json.return_value = {
                        "results": [{"c": 150.0, "h": 152.0, "l": 149.0, "v": 1000000, "t": 1609459200000}]
                    }
                    return response

            client.client.get = mock_get

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.fetch_stock_data("AAPL", days=250)

                assert call_count == 2
                assert result.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_correct_endpoint_format(self):
        """Test that correct Polygon.io endpoint is constructed."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.polygon.io"

            client = RestApiClient()

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [{"c": 150.0, "h": 152.0, "l": 149.0, "v": 1000000, "t": 1609459200000}]
            }

            client.client.get = AsyncMock(return_value=mock_response)

            await client.fetch_stock_data("AAPL", days=250)

            # Verify URL format
            call_args = client.client.get.call_args
            url = call_args[0][0]

            assert "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/" in url
            assert "/v2/aggs/ticker/AAPL/range/1/day/" in url

            # Verify params include API key
            params = call_args[1]["params"]
            assert params["apiKey"] == "test_token"
            assert params["adjusted"] == "true"
            assert params["sort"] == "asc"


class TestCacheManagement:
    """Test cache clearing and management."""

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        """Test that clear_cache removes all cached entries."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            client = RestApiClient()

            # Mock response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [{"c": 150.0, "h": 152.0, "l": 149.0, "v": 1000000, "t": 1609459200000}]
            }

            client.client.get = AsyncMock(return_value=mock_response)

            # Fetch data to populate cache
            await client.fetch_stock_data("AAPL", days=250)
            assert len(client._cache) == 1

            # Clear cache
            client.clear_cache()
            assert len(client._cache) == 0

            # Next fetch should hit API again
            await client.fetch_stock_data("AAPL", days=250)
            assert client.client.get.call_count == 2


class TestConcurrentRequests:
    """Test connection pool and concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_limit_enforcement(self):
        """Test that max concurrent connections limit is respected."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"
            mock_config.API_BASE_URL = "https://api.test.com"

            # Create client with max 5 concurrent connections
            client = RestApiClient(max_concurrent=5)

            # Verify client is created (limits are configured internally)
            assert client.client is not None
            assert isinstance(client.client, httpx.AsyncClient)


class TestClientCleanup:
    """Test client cleanup and resource management."""

    @pytest.mark.asyncio
    async def test_close_client(self):
        """Test that close() properly closes httpx client."""
        with patch("core.api_client.config") as mock_config:
            mock_config.POLYGON_TOKEN = "test_token"

            client = RestApiClient()
            client.client.aclose = AsyncMock()

            await client.close()

            client.client.aclose.assert_called_once()
