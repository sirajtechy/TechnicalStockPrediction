"""Route-level tests for GET /api/v1/intelligence/{ticker}."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import api.intel_endpoints as intel_ep
from main import app


def _all_failing_client():
    """A MassiveDataClient-shaped mock whose every fetcher returns None."""
    c = AsyncMock()
    for m in (
        "get_news",
        "get_insider_trades",
        "get_short_interest",
        "get_short_volume",
        "get_dividends",
        "get_macro",
        "get_analyst_consensus",
        "get_analyst_insights",
        "get_earnings",
        "get_fundamentals",
    ):
        getattr(c, m).return_value = None
    c.close = AsyncMock()
    return c


def test_intelligence_returns_200_even_when_everything_fails():
    with patch.object(intel_ep, "_client", return_value=_all_failing_client()):
        resp = TestClient(app).get("/api/v1/intelligence/aapl")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"
    # Every section degraded → all listed in unavailable, none crash the route
    assert set(body["unavailable"]) == {
        "news",
        "insider_trades",
        "short_interest",
        "short_volume",
        "dividends",
        "macro",
        "analyst",
        "analyst_insights",
        "earnings",
        "fundamentals",
    }
    # List sections still serialize as [] (stable schema)
    assert body["news"] == [] and body["short_interest"] is None


def test_intelligence_ok_when_entitled_sections_present():
    c = _all_failing_client()
    c.get_news.return_value = [{"title": "T", "sentiment": "positive"}]
    c.get_short_interest.return_value = {"days_to_cover": 2.5}
    with patch.object(intel_ep, "_client", return_value=c):
        resp = TestClient(app).get("/api/v1/intelligence/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["news"][0]["sentiment"] == "positive"
    assert body["short_interest"]["days_to_cover"] == 2.5
    assert "news" not in body["unavailable"]
    c.close.assert_awaited()  # client always closed
