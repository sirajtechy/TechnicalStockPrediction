"""
Tests for the Stock Intelligence fetchers + aggregator.

Uses a fake MassiveDataClient (no network) to verify parsing of the entitled
endpoints and graceful degradation when a section returns None (403/error).
"""

from unittest.mock import AsyncMock

import pytest

from core.massive_client import _insider_action, _num
from core.stock_intelligence import gather_intelligence


def _fake_client(**overrides):
    """A MassiveDataClient-shaped mock; each method is an AsyncMock."""
    client = AsyncMock()
    client.get_news.return_value = [
        {"title": "Apple pops", "publisher": "X", "sentiment": "positive"}
    ]
    client.get_insider_trades.return_value = [{"owner_name": "CEO", "action": "buy"}]
    client.get_short_interest.return_value = {"days_to_cover": 1.9}
    client.get_dividends.return_value = [{"ex_dividend_date": "2026-05-01", "cash_amount": 0.24}]
    client.get_macro.return_value = {"yield_10y": 4.2, "cpi": 320.1}
    client.get_analyst_consensus.return_value = {"target": 250.0}
    client.get_earnings.return_value = [{"date": "2026-07-30"}]
    client.get_fundamentals.return_value = {"pe_ratio": 30.0}
    client.get_short_volume.return_value = {"short_volume_ratio": 25.0, "date": "2026-06-30"}
    client.get_analyst_insights.return_value = [{"firm": "Needham", "rating": "buy", "rating_action": "maintains", "price_target": 55.0, "insight": "Strong app-driven GMS growth.", "date": "2026-06-01"}]
    for name, value in overrides.items():
        getattr(client, name).return_value = value
    return client


@pytest.mark.asyncio
async def test_gather_all_sections_present():
    intel = await gather_intelligence(_fake_client(), "aapl")
    assert intel["ticker"] == "AAPL"
    assert intel["news"] and intel["news"][0]["sentiment"] == "positive"
    assert intel["insider_trades"][0]["action"] == "buy"
    assert intel["short_interest"]["days_to_cover"] == 1.9
    assert intel["analyst"]["target"] == 250.0
    assert intel["earnings"][0]["date"] == "2026-07-30"
    assert intel["fundamentals"]["pe_ratio"] == 30.0
    assert intel["unavailable"] == []


@pytest.mark.asyncio
async def test_premium_unavailable_listed_not_faked():
    # Simulate 403 on the premium feeds → methods return None
    client = _fake_client(get_analyst_consensus=None, get_earnings=None, get_fundamentals=None)
    intel = await gather_intelligence(client, "AAPL")
    assert intel["analyst"] is None
    assert intel["fundamentals"] is None
    assert set(intel["unavailable"]) == {"analyst", "earnings", "fundamentals"}
    # Entitled sections still present
    assert intel["news"]
    assert intel["short_interest"]["days_to_cover"] == 1.9


@pytest.mark.asyncio
async def test_section_exception_does_not_break_bundle():
    client = _fake_client()
    client.get_news.side_effect = RuntimeError("boom")
    intel = await gather_intelligence(client, "AAPL")
    assert "news" in intel["unavailable"]  # failed section degrades
    assert intel["macro"]["cpi"] == 320.1  # others unaffected


def test_num_coercion():
    assert _num("5.5") == 5.5
    assert _num(None) is None
    assert _num("") is None
    assert _num("x") is None
    assert _num(0) == 0.0  # zero is a real value, not "missing"


def test_insider_action_mapping():
    assert _insider_action("P", "A") == "buy"
    assert _insider_action("S", "D") == "sell"
    assert _insider_action("M", None) == "exercise"
    assert _insider_action(None, None) is None
    assert _insider_action("Z", "A") == "acquire"


# ─── HTTP-level parsing (mocked httpx) for the new client fetchers ──────────
from unittest.mock import MagicMock, patch

from core.massive_client import MassiveDataClient


def _resp(json_body, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body
    return r


@pytest.mark.asyncio
async def test_get_news_parses_sentiment_insight():
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    body = {
        "results": [
            {
                "title": "T",
                "article_url": "u",
                "published_utc": "2026-06-30",
                "publisher": {"name": "Investing"},
                "description": "d",
                "insights": [
                    {"ticker": "AAPL", "sentiment": "positive", "sentiment_reasoning": "why"}
                ],
            }
        ]
    }
    with patch.object(client, "_request_with_retry", AsyncMock(return_value=_resp(body))):
        out = await client.get_news("AAPL")
    assert out[0]["sentiment"] == "positive"
    assert out[0]["publisher"] == "Investing"
    await client.close()


@pytest.mark.asyncio
async def test_get_short_interest_parses():
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    body = {
        "results": [{"settlement_date": "2026-06-15", "short_interest": 100, "days_to_cover": 2.5}]
    }
    with patch.object(client, "_request_with_retry", AsyncMock(return_value=_resp(body))):
        out = await client.get_short_interest("AAPL")
    assert out["days_to_cover"] == 2.5 and out["short_interest"] == 100.0
    await client.close()


@pytest.mark.asyncio
async def test_fetcher_returns_none_on_unavailable():
    # _request_with_retry returns None on 4xx (incl 403) → fetcher returns None
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    with patch.object(client, "_request_with_retry", AsyncMock(return_value=None)):
        assert await client.get_news("AAPL") is None
        assert await client.get_short_interest("AAPL") is None
        assert await client.get_fundamentals("AAPL") is None
    await client.close()


# ─── Additional coverage (from strict review) ──────────────────────────────


@pytest.mark.asyncio
async def test_empty_list_section_not_marked_unavailable():
    """Entitled-but-empty ([]) stays [] and is NOT listed in unavailable."""
    client = _fake_client(get_news=[], get_dividends=[])
    intel = await gather_intelligence(client, "AAPL")
    assert intel["news"] == [] and "news" not in intel["unavailable"]
    assert intel["dividends"] == [] and "dividends" not in intel["unavailable"]


def test_insider_action_all_codes():
    assert _insider_action("A", "A") == "grant"
    assert _insider_action("G", None) == "gift"
    assert _insider_action("F", None) == "tax"
    assert _insider_action("?", "D") == "dispose"
    assert _insider_action("?", None) == "other"


@pytest.mark.asyncio
async def test_get_insider_trades_parses_fields():
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    body = {"results": [{
        "owner_name": "Jane", "is_officer": True, "transaction_date": "2026-06-24",
        "transaction_code": "P", "transaction_acquired_disposed": "A",
        "transaction_shares": "100", "transaction_price_per_share": "44.25",
        "transaction_value": "4425",
    }]}
    spy = AsyncMock(return_value=_resp(body))
    with patch.object(client, "_request_with_retry", spy):
        out = await client.get_insider_trades("AAPL")
    t = out[0]
    assert t["action"] == "buy" and t["shares"] == 100.0 and t["value"] == 4425.0
    # Form-4 filters by `tickers` (array-contains); `ticker` is silently ignored
    # by the endpoint and would return market-wide filings. Guard against regressing.
    endpoint, params = spy.call_args.args[0], spy.call_args.args[1]
    assert endpoint == "/stocks/filings/vX/form-4"
    assert params.get("tickers") == "AAPL" and "ticker" not in params
    await client.close()


@pytest.mark.asyncio
async def test_get_macro_partial_yields_only():
    """Only yields available (inflation empty) → still returns a macro dict, cpi None."""
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    yields = _resp({"results": [{"date": "2026-06-29", "yield_10_year": 4.4}]})
    empty = _resp({"results": []})
    with patch.object(client, "_request_with_retry", AsyncMock(side_effect=[yields, empty])):
        out = await client.get_macro()
    assert out["yield_10y"] == 4.4 and out["cpi"] is None and out["as_of"] == "2026-06-29"
    await client.close()


@pytest.mark.asyncio
async def test_get_fundamentals_first_alias_fallback():
    """_first picks the aliased key (pe vs pe_ratio vs price_to_earnings)."""
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    with patch.object(client, "_request_with_retry", AsyncMock(return_value=_resp({"results": [{"pe": 30.0}]}))):
        out = await client.get_fundamentals("AAPL")
    assert out["pe_ratio"] == 30.0
    await client.close()


@pytest.mark.asyncio
async def test_get_short_interest_empty_returns_none():
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    with patch.object(client, "_request_with_retry", AsyncMock(return_value=_resp({"results": []}))):
        assert await client.get_short_interest("AAPL") is None
    await client.close()


@pytest.mark.asyncio
async def test_results_filters_non_dict_rows():
    """A stray non-dict row must not break parsing (never-raise contract)."""
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    body = {"results": [{"title": "ok"}, "junk", None, 42]}
    with patch.object(client, "_request_with_retry", AsyncMock(return_value=_resp(body))):
        out = await client.get_news("AAPL")
    assert len(out) == 1 and out[0]["title"] == "ok"
    await client.close()


@pytest.mark.asyncio
async def test_get_short_volume_parses():
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    body = {"results": [{"date": "2026-06-30", "short_volume": 181219, "total_volume": 574084, "short_volume_ratio": 31.57}]}
    with patch.object(client, "_request_with_retry", AsyncMock(return_value=_resp(body))):
        out = await client.get_short_volume("AAPL")
    assert out["short_volume_ratio"] == 31.57 and out["date"] == "2026-06-30"
    await client.close()


@pytest.mark.asyncio
async def test_gather_includes_short_volume():
    client = _fake_client(get_short_volume={"short_volume_ratio": 30.0, "date": "2026-06-30"})
    intel = await gather_intelligence(client, "AAPL")
    assert intel["short_volume"]["short_volume_ratio"] == 30.0
    assert "short_volume" not in intel["unavailable"]


@pytest.mark.asyncio
async def test_get_analyst_insights_parses():
    client = MassiveDataClient(api_key="k", base_url="https://api.massive.com")
    body = {"results": [
        {"date": "2025-05-01", "firm": "Needham", "rating": "buy",
         "rating_action": "maintains", "price_target": 55, "insight": "Buy rating, $55 PT."}
    ]}
    with patch.object(client, "_request_with_retry", AsyncMock(return_value=_resp(body))):
        out = await client.get_analyst_insights("ETSY")
    assert out[0]["firm"] == "Needham" and out[0]["price_target"] == 55.0
    assert out[0]["rating_action"] == "maintains"
    await client.close()


@pytest.mark.asyncio
async def test_gather_includes_analyst_insights():
    intel = await gather_intelligence(_fake_client(), "AAPL")
    assert intel["analyst_insights"][0]["firm"] == "Needham"
    assert "analyst_insights" not in intel["unavailable"]
