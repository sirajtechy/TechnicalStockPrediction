"""
Integration Tests: Trade Engine Pipeline (Orchestrator → TradeEngine)

Tests the full orchestrator-to-trade-engine pipeline with mocked external APIs.
Verifies that:
  1. BUY candidates get trade_plan populated; non-candidates get null
  2. Trade plan JSON conforms to TradePlan schema (all 22 fields, correct types)
  3. All hard-filter failures → zero trade plans
  4. Massive unavailable → valid core plans with vol_source "historical"
  5. Massive calls batched only for candidate set (verified via mock call counts)

Per Requirement 17.1.
"""

from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pytest

from api.models import IndicatorSignals, ScanRequest, TradePlanResponse
from core.indicator_calculator import IndicatorCalculator
from core.models import StockData
from core.orchestrator import ScanOrchestrator
from core.ranking_service import RankingService
from core.regime_analyzer import MarketRegimeAnalyzer
from core.scoring_engine import ScoringEngine
from core.universe_builder import UniverseBuilder

N = 260  # Enough bars for all indicators (252+ needed for 52-week)


def _stock(ticker: str, prices: np.ndarray, highs=None, lows=None) -> StockData:
    """Create a StockData instance with proper highs/lows."""
    if highs is None:
        highs = prices * 1.02  # 2% above close
    if lows is None:
        lows = prices * 0.98  # 2% below close
    return StockData(
        ticker=ticker,
        prices=prices,
        volumes=np.full(len(prices), 1_000_000.0),
        timestamps=np.arange(len(prices), dtype=np.int64),
        highs=highs,
        lows=lows,
    )


def _uptrend(ticker: str, start=50.0, end=150.0, n=N) -> StockData:
    """Strong uptrend with highs/lows → passes Minervini hard filters."""
    prices = np.linspace(start, end, n)
    return _stock(ticker, prices)


def _downtrend(ticker: str, start=150.0, end=100.0, n=N) -> StockData:
    """Downtrend → price below SMA200 → fails hard filters."""
    prices = np.linspace(start, end, n)
    return _stock(ticker, prices)


def _make_orchestrator(data_by_ticker: dict):
    """Build orchestrator with real components and mocked api_client."""
    api_client = Mock()
    api_client.clear_cache = Mock()

    async def _fetch(ticker, days=365, as_of_date=None):
        return data_by_ticker[ticker]

    api_client.fetch_stock_data = AsyncMock(side_effect=_fetch)

    return ScanOrchestrator(
        api_client=api_client,
        universe_builder=UniverseBuilder(),
        regime_analyzer=MarketRegimeAnalyzer(api_client),
        indicator_calc=IndicatorCalculator(),
        scoring_engine=ScoringEngine(),
        ranking_service=RankingService(),
    )


def _make_orchestrator_with_forced_score(data_by_ticker: dict, forced_score: int = 80):
    """Build orchestrator that forces a specific score for tickers that pass hard filters.

    This allows testing trade plan integration without relying on the scoring engine
    producing a specific score from synthetic data.
    """
    api_client = Mock()
    api_client.clear_cache = Mock()

    async def _fetch(ticker, days=365, as_of_date=None):
        return data_by_ticker[ticker]

    api_client.fetch_stock_data = AsyncMock(side_effect=_fetch)

    # Create a scoring engine that returns a controlled score
    scoring_engine = ScoringEngine()
    original_calculate = scoring_engine.calculate_enhanced_score

    def _forced_score_fn(*args, **kwargs):
        score, signals, stage, pattern = original_calculate(*args, **kwargs)
        # Override the score to force candidacy
        return (forced_score, signals, stage, pattern)

    scoring_engine.calculate_enhanced_score = _forced_score_fn

    return ScanOrchestrator(
        api_client=api_client,
        universe_builder=UniverseBuilder(),
        regime_analyzer=MarketRegimeAnalyzer(api_client),
        indicator_calc=IndicatorCalculator(),
        scoring_engine=scoring_engine,
        ranking_service=RankingService(),
    )


def _mock_massive_client():
    """Create a mocked MassiveDataClient instance that returns None for all calls."""
    mock_instance = AsyncMock()
    mock_instance.get_earnings = AsyncMock(return_value=None)
    mock_instance.get_options_iv = AsyncMock(return_value=None)
    mock_instance.get_analyst_consensus = AsyncMock(return_value=None)
    mock_instance.close = AsyncMock()
    return mock_instance


# ============================================================================
# IT-1: BUY candidates have trade_plan populated; non-candidates have null
# ============================================================================


@pytest.mark.asyncio
async def test_buy_candidates_have_trade_plan_non_candidates_null():
    """A scan returns trade_plan for BUY candidates and null for non-candidates."""
    data = {
        "SPY": _uptrend("SPY", 90.0, 110.0),
        "STRONG": _uptrend("STRONG", 40.0, 160.0),  # passes filters
        "WEAK": _downtrend("WEAK"),  # fails hard filters
    }
    # Force high score so STRONG becomes a candidate
    orch = _make_orchestrator_with_forced_score(data, forced_score=80)

    mock_massive = _mock_massive_client()
    with patch("core.massive_client.MassiveDataClient", return_value=mock_massive):
        resp = await orch.execute_scan(
            ScanRequest(tickers=["STRONG", "WEAK"], include_all=True),
            apply_signal_gate=False,
        )

    by_ticker = {t.ticker: t for t in resp.ranked_tickers}
    assert "STRONG" in by_ticker
    assert "WEAK" in by_ticker

    # STRONG should be a candidate with a trade plan
    strong = by_ticker["STRONG"]
    assert strong.is_candidate is True
    assert strong.trade_plan is not None

    # WEAK failed hard filters → not a candidate → null trade plan
    weak = by_ticker["WEAK"]
    assert weak.is_candidate is False
    assert weak.trade_plan is None


# ============================================================================
# IT-2: Trade plan conforms to TradePlanResponse schema (all 22 fields)
# ============================================================================


@pytest.mark.asyncio
async def test_trade_plan_conforms_to_schema():
    """Trade plan on candidate has all required fields with correct types."""
    data = {
        "SPY": _uptrend("SPY", 90.0, 110.0),
        "AAPL": _uptrend("AAPL", 40.0, 160.0),
    }
    orch = _make_orchestrator_with_forced_score(data, forced_score=80)

    mock_massive = _mock_massive_client()
    with patch("core.massive_client.MassiveDataClient", return_value=mock_massive):
        resp = await orch.execute_scan(
            ScanRequest(tickers=["AAPL"]), apply_signal_gate=False
        )

    candidates = [t for t in resp.ranked_tickers if t.is_candidate and t.trade_plan is not None]
    assert len(candidates) > 0, "Expected at least one candidate with trade plan"

    plan = candidates[0].trade_plan
    # Verify it's a TradePlanResponse instance
    assert isinstance(plan, TradePlanResponse)

    # All 22 fields must be present with correct types
    assert isinstance(plan.entry, float)
    assert isinstance(plan.stop, float)
    assert isinstance(plan.stop_pct, float)
    assert isinstance(plan.target1, float)
    assert isinstance(plan.target1_pct, float)
    assert isinstance(plan.target2, float)
    assert isinstance(plan.target2_pct, float)
    assert isinstance(plan.risk_per_share, float)
    assert plan.reward_risk is None or isinstance(plan.reward_risk, float)
    assert isinstance(plan.low_rr, bool)
    assert isinstance(plan.data_unavailable, bool)
    assert plan.expected_move_pct is None or isinstance(plan.expected_move_pct, float)
    assert isinstance(plan.vol_source, str)
    assert plan.vol_source in ("options_iv", "historical")
    assert isinstance(plan.resistance, float)
    assert isinstance(plan.target_above_resistance, bool)
    assert isinstance(plan.resistance_data_limited, bool)
    assert plan.earnings_in_window is None or isinstance(plan.earnings_in_window, str)
    assert plan.prob_hit_target1 is None or isinstance(plan.prob_hit_target1, float)
    assert isinstance(plan.calibration_available, bool)
    assert plan.analyst_target is None or isinstance(plan.analyst_target, float)
    assert plan.analyst_low is None or isinstance(plan.analyst_low, float)
    assert plan.analyst_high is None or isinstance(plan.analyst_high, float)


# ============================================================================
# IT-3: All tickers fail hard filters → zero trade plans
# ============================================================================


@pytest.mark.asyncio
async def test_all_fail_hard_filters_zero_trade_plans():
    """When all tickers fail hard filters, no trade plans are produced."""
    data = {
        "SPY": _uptrend("SPY", 90.0, 110.0),  # bullish market
        "WEAK1": _downtrend("WEAK1"),
        "WEAK2": _downtrend("WEAK2"),
        "WEAK3": _downtrend("WEAK3"),
    }
    orch = _make_orchestrator(data)

    resp = await orch.execute_scan(
        ScanRequest(tickers=["WEAK1", "WEAK2", "WEAK3"], include_all=True),
        apply_signal_gate=False,
    )

    # All tickers should have null trade_plan
    for ticker_score in resp.ranked_tickers:
        assert ticker_score.trade_plan is None, (
            f"{ticker_score.ticker} should have null trade_plan"
        )


# ============================================================================
# IT-4: Massive unavailable → valid core plans with vol_source "historical"
# ============================================================================


@pytest.mark.asyncio
async def test_massive_unavailable_returns_core_plans_historical_vol():
    """When Massive enhancement data is unavailable, core plans are still valid."""
    data = {
        "SPY": _uptrend("SPY", 90.0, 110.0),
        "AAPL": _uptrend("AAPL", 40.0, 160.0),
    }
    orch = _make_orchestrator_with_forced_score(data, forced_score=80)

    # MassiveDataClient returns None for all calls (simulating unavailability)
    mock_massive = _mock_massive_client()
    with patch("core.massive_client.MassiveDataClient", return_value=mock_massive):
        resp = await orch.execute_scan(
            ScanRequest(tickers=["AAPL"]), apply_signal_gate=False
        )

    candidates = [t for t in resp.ranked_tickers if t.is_candidate and t.trade_plan is not None]
    assert len(candidates) > 0, "Expected at least one candidate with trade plan"

    plan = candidates[0].trade_plan
    # Should fall back to historical volatility
    assert plan.vol_source == "historical"
    # Analyst fields should be null
    assert plan.analyst_target is None
    assert plan.analyst_low is None
    assert plan.analyst_high is None
    # Core plan fields should still be valid
    assert plan.stop < plan.entry
    assert plan.target1 > plan.entry
    assert plan.risk_per_share > 0


# ============================================================================
# IT-5: Massive calls batched only for candidate set (mock call counts)
# ============================================================================


@pytest.mark.asyncio
async def test_massive_calls_only_for_candidates():
    """Massive API calls happen only for BUY candidates, not the full universe."""
    data = {
        "SPY": _uptrend("SPY", 90.0, 110.0),
        "CANDIDATE": _uptrend("CANDIDATE", 40.0, 160.0),  # passes → candidate
        "FAIL1": _downtrend("FAIL1"),  # fails hard filters
        "FAIL2": _downtrend("FAIL2"),  # fails hard filters
    }
    orch = _make_orchestrator_with_forced_score(data, forced_score=80)

    mock_massive = _mock_massive_client()
    with patch("core.massive_client.MassiveDataClient", return_value=mock_massive):
        resp = await orch.execute_scan(
            ScanRequest(tickers=["CANDIDATE", "FAIL1", "FAIL2"], include_all=True),
            apply_signal_gate=False,
        )

    # Count how many candidates got trade plans
    candidates = [t for t in resp.ranked_tickers if t.is_candidate]
    num_candidates = len(candidates)
    assert num_candidates > 0, "Expected at least one candidate"

    # Massive calls should only have been made for candidates (not FAIL1, FAIL2)
    # Each candidate gets 3 calls: get_earnings, get_options_iv, get_analyst_consensus
    earnings_calls = mock_massive.get_earnings.call_count
    options_calls = mock_massive.get_options_iv.call_count
    analyst_calls = mock_massive.get_analyst_consensus.call_count

    assert earnings_calls == num_candidates, (
        f"Expected {num_candidates} earnings calls, got {earnings_calls}"
    )
    assert options_calls == num_candidates, (
        f"Expected {num_candidates} options calls, got {options_calls}"
    )
    assert analyst_calls == num_candidates, (
        f"Expected {num_candidates} analyst calls, got {analyst_calls}"
    )
