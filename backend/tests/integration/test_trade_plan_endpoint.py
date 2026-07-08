"""
Integration Tests: Trade Plan API Endpoint

Tests the POST /scan endpoint's trade plan functionality via FastAPI TestClient.
Verifies that:
  1. POST /scan with valid tickers returns 200 with trade_plan on candidates
  2. Trade plan JSON includes all required fields
  3. Trade plan numeric fields are within valid ranges
  4. include_all=true shows non-candidates with trade_plan as null
  5. Error responses do not expose trade plan internal errors

Per Requirement 17.2.
"""

from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.models import (
    IndicatorSignals,
    MarketRegime,
    ScanMetadata,
    ScanResponse,
    TickerScore,
    TradePlanResponse,
)
from main import app

N = 260


def _make_scan_response_with_trade_plan(include_non_candidate=False):
    """Create a mock ScanResponse with a candidate that has a trade plan."""
    from datetime import datetime

    plan = TradePlanResponse(
        entry=150.0,
        stop=143.0,
        stop_pct=-4.67,
        target1=164.0,
        target1_pct=9.33,
        target2=171.0,
        target2_pct=14.0,
        risk_per_share=7.0,
        reward_risk=2.0,
        low_rr=False,
        data_unavailable=False,
        expected_move_pct=8.5,
        vol_source="historical",
        resistance=155.0,
        target_above_resistance=True,
        resistance_data_limited=False,
        earnings_in_window=None,
        prob_hit_target1=0.55,
        calibration_available=True,
        analyst_target=165.0,
        analyst_low=140.0,
        analyst_high=180.0,
    )

    signals = IndicatorSignals(
        price_above_sma50=True,
        price_above_ema20=True,
        macd_above_signal=True,
        macd_histogram_positive=True,
        volume_above_average=True,
        relative_strength_positive=True,
    )

    candidate = TickerScore(
        ticker="AAPL",
        bullish_score=80,
        signals=signals,
        current_price=150.0,
        indicators={
            "sma_50": 145.0,
            "ema_20": 148.0,
            "macd_line": 1.5,
            "macd_signal": 1.0,
            "macd_histogram": 0.5,
            "avg_volume_20": 50000000.0,
            "relative_strength": 3.0,
        },
        passed_hard_filters=True,
        is_candidate=True,
        trade_plan=plan,
    )

    tickers = [candidate]

    if include_non_candidate:
        non_candidate = TickerScore(
            ticker="WEAK",
            bullish_score=0,
            signals=IndicatorSignals(
                price_above_sma50=False,
                price_above_ema20=False,
                macd_above_signal=False,
                macd_histogram_positive=False,
                volume_above_average=False,
                relative_strength_positive=False,
            ),
            current_price=100.0,
            indicators={
                "sma_50": 110.0,
                "ema_20": 105.0,
                "macd_line": -0.5,
                "macd_signal": 0.0,
                "macd_histogram": -0.5,
                "avg_volume_20": 1000000.0,
                "relative_strength": -1.0,
            },
            passed_hard_filters=False,
            is_candidate=False,
            trade_plan=None,
        )
        tickers.append(non_candidate)

    return ScanResponse(
        scan_id="test-uuid-1234",
        market_regime=MarketRegime.BULLISH,
        ranked_tickers=tickers,
        metadata=ScanMetadata(
            timestamp=datetime.utcnow(),
            ticker_count=len(tickers),
            duration_seconds=1.0,
        ),
        score_threshold=65,
    )


@pytest.fixture
def client():
    """Create FastAPI test client."""
    return TestClient(app)


# ============================================================================
# Test 1: POST /scan with valid tickers returns 200 with trade_plan on candidates
# ============================================================================


def test_scan_returns_200_with_trade_plan_on_candidates(client):
    """POST /scan with valid tickers returns 200 with trade_plan fields on candidates."""
    mock_response = _make_scan_response_with_trade_plan()

    from api.endpoints import get_orchestrator, get_scan_store

    # Mock orchestrator that returns our controlled response
    mock_orch = AsyncMock()
    mock_orch.execute_scan = AsyncMock(return_value=mock_response)

    # Mock scan_store to avoid DB operations
    mock_store = AsyncMock()
    mock_store.save = AsyncMock()

    app.dependency_overrides[get_orchestrator] = lambda: mock_orch
    app.dependency_overrides[get_scan_store] = lambda: mock_store

    try:
        response = client.post("/api/v1/scan", json={"tickers": ["AAPL"]})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert "ranked_tickers" in data

    # The candidate should have trade_plan populated
    candidates_with_plan = [
        t for t in data["ranked_tickers"] if t.get("trade_plan") is not None
    ]
    assert len(candidates_with_plan) > 0, "Expected at least one ticker with trade_plan"
    plan = candidates_with_plan[0]["trade_plan"]
    assert "entry" in plan
    assert "stop" in plan
    assert "target1" in plan


# ============================================================================
# Test 2: Trade plan JSON includes all required fields
# ============================================================================


REQUIRED_TRADE_PLAN_FIELDS = [
    "entry",
    "stop",
    "stop_pct",
    "target1",
    "target1_pct",
    "target2",
    "target2_pct",
    "risk_per_share",
    "reward_risk",
    "low_rr",
    "data_unavailable",
    "expected_move_pct",
    "vol_source",
    "resistance",
    "target_above_resistance",
    "resistance_data_limited",
    "earnings_in_window",
    "prob_hit_target1",
    "calibration_available",
    "analyst_target",
    "analyst_low",
    "analyst_high",
]


def test_trade_plan_json_has_all_required_fields(client):
    """The trade_plan JSON includes all required fields per schema."""
    mock_response = _make_scan_response_with_trade_plan()

    from api.endpoints import get_orchestrator, get_scan_store

    mock_orch = AsyncMock()
    mock_orch.execute_scan = AsyncMock(return_value=mock_response)
    app.dependency_overrides[get_orchestrator] = lambda: mock_orch

    mock_store = AsyncMock()
    mock_store.save = AsyncMock()
    app.dependency_overrides[get_scan_store] = lambda: mock_store

    try:
        response = client.post("/api/v1/scan", json={"tickers": ["AAPL"]})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    resp_data = response.json()

    candidates_with_plan = [
        t for t in resp_data["ranked_tickers"] if t.get("trade_plan") is not None
    ]
    assert len(candidates_with_plan) > 0

    plan = candidates_with_plan[0]["trade_plan"]
    for field in REQUIRED_TRADE_PLAN_FIELDS:
        assert field in plan, f"Missing field '{field}' in trade_plan JSON"


# ============================================================================
# Test 3: Trade plan numeric fields within valid ranges
# ============================================================================


def test_trade_plan_numeric_fields_valid_ranges(client):
    """Trade plan numeric fields are within expected ranges."""
    mock_response = _make_scan_response_with_trade_plan()

    from api.endpoints import get_orchestrator, get_scan_store

    mock_orch = AsyncMock()
    mock_orch.execute_scan = AsyncMock(return_value=mock_response)
    app.dependency_overrides[get_orchestrator] = lambda: mock_orch

    mock_store = AsyncMock()
    mock_store.save = AsyncMock()
    app.dependency_overrides[get_scan_store] = lambda: mock_store

    try:
        response = client.post("/api/v1/scan", json={"tickers": ["AAPL"]})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    resp_data = response.json()

    candidates_with_plan = [
        t for t in resp_data["ranked_tickers"] if t.get("trade_plan") is not None
    ]
    assert len(candidates_with_plan) > 0

    plan = candidates_with_plan[0]["trade_plan"]

    # stop < entry
    assert plan["stop"] < plan["entry"], "stop should be less than entry"
    # targets > entry
    assert plan["target1"] > plan["entry"], "target1 should be greater than entry"
    assert plan["target2"] > plan["entry"], "target2 should be greater than entry"
    # target1 < target2
    assert plan["target1"] < plan["target2"], "target1 should be less than target2"
    # risk_per_share positive
    assert plan["risk_per_share"] > 0, "risk_per_share should be positive"
    # reward_risk positive (when not null)
    if plan["reward_risk"] is not None:
        assert plan["reward_risk"] > 0, "reward_risk should be positive"
    # prob between 0 and 1 (when not null)
    if plan["prob_hit_target1"] is not None:
        assert 0 <= plan["prob_hit_target1"] <= 1.0, (
            "prob_hit_target1 should be between 0 and 1"
        )
    # stop_pct should be negative
    assert plan["stop_pct"] < 0, "stop_pct should be negative"
    # target1_pct should be positive
    assert plan["target1_pct"] > 0, "target1_pct should be positive"
    # vol_source valid
    assert plan["vol_source"] in ("options_iv", "historical")


# ============================================================================
# Test 4: include_all=true → non-candidates show trade_plan as null
# ============================================================================


def test_include_all_non_candidates_have_null_trade_plan(client):
    """When include_all is true, non-candidate tickers show trade_plan as null."""
    mock_response = _make_scan_response_with_trade_plan(include_non_candidate=True)

    from api.endpoints import get_orchestrator, get_scan_store

    mock_orch = AsyncMock()
    mock_orch.execute_scan = AsyncMock(return_value=mock_response)
    app.dependency_overrides[get_orchestrator] = lambda: mock_orch

    mock_store = AsyncMock()
    mock_store.save = AsyncMock()
    app.dependency_overrides[get_scan_store] = lambda: mock_store

    try:
        response = client.post(
            "/api/v1/scan", json={"tickers": ["AAPL", "WEAK"], "include_all": True}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    resp_data = response.json()

    tickers_map = {t["ticker"]: t for t in resp_data["ranked_tickers"]}

    # WEAK failed hard filters → should have null trade_plan
    assert "WEAK" in tickers_map
    assert tickers_map["WEAK"].get("trade_plan") is None, (
        "Non-candidate WEAK should have null trade_plan"
    )
    assert tickers_map["WEAK"].get("is_candidate") is False

    # AAPL is a candidate → should have trade_plan
    assert "AAPL" in tickers_map
    assert tickers_map["AAPL"].get("trade_plan") is not None


# ============================================================================
# Test 5: Error responses do not expose trade plan internal errors
# ============================================================================


def test_error_response_no_internal_trade_plan_details(client):
    """Invalid ticker requests return clean errors without trade plan internals."""
    response = client.post("/api/v1/scan", json={"tickers": []})

    # Empty tickers → 422 validation error
    assert response.status_code == 422
    error_data = response.json()

    # Should not contain trade plan implementation details
    error_str = str(error_data)
    assert "TradePlan" not in error_str
    assert "trade_engine" not in error_str
    assert "build_plan" not in error_str
    assert "risk_per_share" not in error_str


def test_invalid_ticker_error_does_not_expose_trade_plan(client):
    """Scan errors for invalid tickers don't leak trade plan details."""
    from api.endpoints import get_orchestrator, get_scan_store

    mock_orch = AsyncMock()
    mock_orch.execute_scan = AsyncMock(
        side_effect=Exception("All tickers failed to process")
    )
    app.dependency_overrides[get_orchestrator] = lambda: mock_orch

    mock_store = AsyncMock()
    mock_store.save = AsyncMock()
    app.dependency_overrides[get_scan_store] = lambda: mock_store

    try:
        response = client.post("/api/v1/scan", json={"tickers": ["INVALID"]})
    finally:
        app.dependency_overrides.clear()

    # Should get an error response (500)
    assert response.status_code == 500
    error_data = response.json()
    assert "detail" in error_data
    # Should not contain internal trade plan error details
    error_detail = error_data["detail"]
    assert "TradePlan" not in error_detail
    assert "ATR" not in error_detail
    assert "risk_per_share" not in error_detail
