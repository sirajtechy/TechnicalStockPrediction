"""
Unit Tests for MassiveDataClient

Tests earnings, options IV, and analyst consensus endpoints.
Tests retry logic with exponential backoff.
All tests use httpx mock transport — zero network access.

Requirements: 16.2
"""

import json

import httpx
import pytest

from core.massive_client import MassiveDataClient


# --- Helpers ---


def _make_client(handler) -> MassiveDataClient:
    """Create MassiveDataClient backed by a mock transport handler.

    The handler receives (request: httpx.Request) and returns httpx.Response.
    """
    transport = httpx.MockTransport(handler)
    client = MassiveDataClient(
        api_key="test_key",
        base_url="https://api.polygon.io",
        timeout=5.0,
        max_retries=3,
    )
    # Replace the real AsyncClient with one using our mock transport
    client.client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return client


def _json_response(data, status_code: int = 200) -> httpx.Response:
    """Build an httpx.Response with JSON body."""
    return httpx.Response(
        status_code=status_code,
        json=data,
    )


# --- Earnings Endpoint Tests ---


class TestGetEarnings:
    """Tests for MassiveDataClient.get_earnings()."""

    @pytest.mark.asyncio
    async def test_parse_valid_response_multiple_dates(self):
        """Earnings: parse valid JSON response with multiple earnings dates, return list."""

        earnings_data = [
            {"date": "2024-02-01", "ticker": "AAPL", "eps": 1.50},
            {"date": "2024-02-15", "ticker": "AAPL", "eps": None},
            {"date": "2024-03-01", "ticker": "AAPL", "eps": 2.00},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            assert "benzinga/v1/earnings" in str(request.url)
            assert "apiKey=test_key" in str(request.url)
            return _json_response(earnings_data)

        client = _make_client(handler)
        try:
            result = await client.get_earnings("AAPL", "2024-01-01", "2024-03-31")

            assert result is not None
            assert isinstance(result, list)
            assert len(result) == 3
            assert result[0]["date"] == "2024-02-01"
            assert result[1]["date"] == "2024-02-15"
            assert result[2]["date"] == "2024-03-01"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_list(self):
        """Earnings: empty response returns empty list."""

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response([])

        client = _make_client(handler)
        try:
            result = await client.get_earnings("AAPL", "2024-01-01", "2024-03-31")

            assert result is not None
            assert isinstance(result, list)
            assert len(result) == 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [403, 404, 500])
    async def test_http_error_returns_none(self, status_code: int):
        """Earnings: HTTP 403/404/500 returns None (logged, no exception)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=status_code, json={"error": "fail"})

        client = _make_client(handler)
        try:
            result = await client.get_earnings("AAPL", "2024-01-01", "2024-03-31")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_network_timeout_returns_none(self):
        """Earnings: network timeout returns None."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout(
                "Read timed out", request=request
            )

        client = _make_client(handler)
        # Use max_retries=1 to speed up test (timeout will trigger on each retry)
        client.max_retries = 1
        try:
            result = await client.get_earnings("AAPL", "2024-01-01", "2024-03-31")

            assert result is None
        finally:
            await client.close()


# --- Options Endpoint Tests ---


class TestGetOptionsIV:
    """Tests for MassiveDataClient.get_options_iv()."""

    @pytest.mark.asyncio
    async def test_parse_response_with_5_atm_contracts_returns_weighted_iv(self):
        """Options: parse response with at least 5 ATM contracts, return volume-weighted IV."""

        # 6 contracts with valid IV, strikes within 5% of entry_price=100.0
        contracts = [
            {"greeks": {"implied_volatility": 0.30}, "day": {"volume": 100}},
            {"greeks": {"implied_volatility": 0.32}, "day": {"volume": 200}},
            {"greeks": {"implied_volatility": 0.28}, "day": {"volume": 150}},
            {"greeks": {"implied_volatility": 0.35}, "day": {"volume": 300}},
            {"greeks": {"implied_volatility": 0.29}, "day": {"volume": 250}},
            {"greeks": {"implied_volatility": 0.31}, "day": {"volume": 100}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            assert "snapshot/options/AAPL" in str(request.url)
            return _json_response({"results": contracts})

        client = _make_client(handler)
        try:
            result = await client.get_options_iv("AAPL", 100.0, "2024-02-01", "2024-03-15")

            assert result is not None
            assert isinstance(result, float)
            assert result > 0

            # Verify volume-weighted average calculation
            total_volume = 100 + 200 + 150 + 300 + 250 + 100
            expected_iv = (
                0.30 * 100 + 0.32 * 200 + 0.28 * 150 +
                0.35 * 300 + 0.29 * 250 + 0.31 * 100
            ) / total_volume
            assert abs(result - expected_iv) < 1e-10
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_fewer_than_5_valid_contracts_returns_none(self):
        """Options: fewer than 5 valid contracts returns None (fallback)."""

        # Only 3 contracts with valid IV
        contracts = [
            {"greeks": {"implied_volatility": 0.30}, "day": {"volume": 100}},
            {"greeks": {"implied_volatility": 0.32}, "day": {"volume": 200}},
            {"greeks": {"implied_volatility": 0.28}, "day": {"volume": 150}},
            {"greeks": {"implied_volatility": None}, "day": {"volume": 50}},  # invalid
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"results": contracts})

        client = _make_client(handler)
        try:
            result = await client.get_options_iv("AAPL", 100.0, "2024-02-01", "2024-03-15")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        """Options: HTTP error returns None."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=500, json={"error": "internal"})

        client = _make_client(handler)
        try:
            result = await client.get_options_iv("AAPL", 100.0, "2024-02-01", "2024-03-15")

            assert result is None
        finally:
            await client.close()


# --- Consensus Endpoint Tests ---


class TestGetAnalystConsensus:
    """Tests for MassiveDataClient.get_analyst_consensus()."""

    @pytest.mark.asyncio
    async def test_parse_valid_response_with_price_targets(self):
        """Consensus: parse the real Benzinga schema (Massive already aggregates)."""

        # Real documented schema: a single results[] record with pre-aggregated fields.
        record = {
            "ticker": "AAPL",
            "consensus_price_target": 195.0,
            "low_price_target": 180.0,
            "high_price_target": 210.0,
            "consensus_rating": "buy",
            "consensus_rating_value": 4.14,
            "price_target_contributors": 15,
            "buy_ratings": 6,
            "hold_ratings": 3,
            "sell_ratings": 0,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert "consensus-ratings/AAPL" in str(request.url)
            return _json_response({"results": [record]})

        client = _make_client(handler)
        try:
            result = await client.get_analyst_consensus("AAPL")

            assert result is not None
            assert result["target"] == 195.0
            assert result["low"] == 180.0
            assert result["high"] == 210.0
            assert result["rating"] == "buy"
            assert result["analyst_count"] == 15.0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_empty_result_returns_none(self):
        """Consensus: empty result returns None."""

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"ratings": []})

        client = _make_client(handler)
        try:
            result = await client.get_analyst_consensus("AAPL")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        """Consensus: timeout returns None."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out", request=request)

        client = _make_client(handler)
        client.max_retries = 1
        try:
            result = await client.get_analyst_consensus("AAPL")

            assert result is None
        finally:
            await client.close()


# --- Retry Behavior Tests ---


class TestRetryBehavior:
    """Tests for retry logic: 5xx triggers retry, 4xx does not."""

    @pytest.mark.asyncio
    async def test_5xx_triggers_retry_up_to_3_attempts(self):
        """Retry: 5xx triggers retry (up to 3 attempts), succeeds on last."""

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # First two attempts return 503
                return httpx.Response(status_code=503, json={"error": "unavailable"})
            else:
                # Third attempt succeeds
                return _json_response([{"date": "2024-02-01", "ticker": "AAPL"}])

        client = _make_client(handler)
        try:
            result = await client.get_earnings("AAPL", "2024-01-01", "2024-03-31")

            # Should succeed on 3rd attempt
            assert call_count == 3
            assert result is not None
            assert len(result) == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_4xx_does_not_retry(self):
        """Retry: 4xx does not trigger retry — returns None immediately."""

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(status_code=403, json={"error": "forbidden"})

        client = _make_client(handler)
        try:
            result = await client.get_earnings("AAPL", "2024-01-01", "2024-03-31")

            # Should NOT retry on 4xx — only 1 call
            assert call_count == 1
            assert result is None
        finally:
            await client.close()
