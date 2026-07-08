"""
Unit tests for TradeEngine (core/trade_engine.py).

Covers all 24 test cases per Requirement 16.1.
All tests use synthetic OHLC data — no network access required.
"""

import math

import numpy as np
import pytest

from config import Config
from core.trade_calibration import CalibrationRow, CalibrationTable
from core.trade_engine import TradeEngine, TradePlan


# ─── Helpers ──────────────────────────────────────────────────────────────────


def make_config(**overrides) -> Config:
    """Create a Config instance with optional overrides."""
    cfg = Config()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def make_ohlc(n: int = 30, base_price: float = 100.0):
    """Generate synthetic OHLC data with known volatility.

    Returns highs, lows, closes arrays of length n.
    """
    rng = np.random.default_rng(42)
    closes = base_price + np.cumsum(rng.normal(0, 1, n))
    highs = closes + rng.uniform(0.5, 2.0, n)
    lows = closes - rng.uniform(0.5, 2.0, n)
    return highs, lows, closes


def make_known_ohlc():
    """Create OHLC data with hand-calculable ATR.

    15 bars: constant high=105, low=95, close=100.
    True range for bars 1-14: max(105-95, |105-100|, |95-100|) = 10
    ATR(14) = mean of 14 values of 10 = 10.0
    """
    n = 15
    highs = np.full(n, 105.0)
    lows = np.full(n, 95.0)
    closes = np.full(n, 100.0)
    return highs, lows, closes


def make_calibration_table(buckets: dict[str, float] | None = None) -> CalibrationTable:
    """Create a CalibrationTable with known buckets."""
    if buckets is None:
        buckets = {"high_tight": 0.65, "mid_normal": 0.55}
    rows = {}
    for bucket_id, prob in buckets.items():
        rows[bucket_id] = CalibrationRow(
            bucket_id=bucket_id,
            sample_size=50,
            realized_hit_rate=prob,
            mean_expectancy_r=0.25,
            prob_hit_target1=prob,
        )
    return CalibrationTable(rows=rows)


# ─── Test 1: ATR computation correctness ─────────────────────────────────────


class TestATRComputation:
    """Tests for TradeEngine.compute_atr()."""

    def test_atr_known_ohlc(self):
        """ATR computation correctness on known OHLC data (hand-calculated)."""
        highs, lows, closes = make_known_ohlc()
        # All true ranges = max(10, 5, 5) = 10
        atr = TradeEngine.compute_atr(highs, lows, closes, n=14)
        assert atr == pytest.approx(10.0, abs=1e-10)

    def test_atr_varying_true_ranges(self):
        """ATR with varying true ranges computes mean correctly."""
        # 15 bars where last 14 true ranges are known
        closes = np.array([100.0] * 15)
        highs = np.array([100.0] + [100.0 + i for i in range(1, 15)])
        lows = np.array([100.0] + [100.0 - i for i in range(1, 15)])
        # True range for bar i (1-14): high-low = 2*i
        # ATR = mean([2, 4, 6, ..., 28]) = mean of 14 values = (2+28)*14/2 / 14 = 15.0
        atr = TradeEngine.compute_atr(highs, lows, closes, n=14)
        expected = np.mean([2 * i for i in range(1, 15)])
        assert atr == pytest.approx(expected, abs=1e-10)

    def test_atr_fewer_than_15_bars_raises(self):
        """ATR with fewer than 15 bars raises ValueError."""
        highs = np.array([105.0] * 14)
        lows = np.array([95.0] * 14)
        closes = np.array([100.0] * 14)
        with pytest.raises(ValueError, match="Insufficient OHLC data"):
            TradeEngine.compute_atr(highs, lows, closes, n=14)

    def test_atr_exactly_15_bars(self):
        """ATR with exactly 15 bars works (minimum required)."""
        highs, lows, closes = make_known_ohlc()
        assert len(highs) == 15
        atr = TradeEngine.compute_atr(highs, lows, closes, n=14)
        assert atr > 0


# ─── Test 3-4: Stop price computation ────────────────────────────────────────


class TestStopPrice:
    """Tests for stop price computation in build_plan."""

    def test_stop_equals_entry_minus_atr_mult_times_atr(self):
        """Stop = entry - atr_mult × ATR when not capped."""
        cfg = make_config()
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        entry = 150.0  # ATR=10, stop = 150 - 2*10 = 130; floor = 150*0.9 = 135
        # stop=130 < floor=135, so it will be capped
        # Use a higher entry where ATR stop won't be capped
        entry = 200.0  # stop = 200 - 2*10 = 180; floor = 200*0.9 = 180
        # Still capped at boundary. Use lower ATR mult
        cfg2 = make_config(TRADE_ATR_MULT=1.0)
        engine2 = TradeEngine(cfg2)
        # stop = 200 - 1*10 = 190; floor = 200*0.9 = 180 → not capped
        plan = engine2.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes, score=75
        )
        expected_stop = entry - 1.0 * 10.0  # 190.0
        assert plan.stop == pytest.approx(expected_stop, abs=0.01)

    def test_stop_capped_at_max_loss_pct(self):
        """Stop capped at entry × (1 - MAX_LOSS_PCT) when ATR stop exceeds floor."""
        cfg = make_config(TRADE_ATR_MULT=3.0, TRADE_MAX_LOSS_PCT=0.05)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        entry = 100.0
        # ATR = 10, stop_raw = 100 - 3*10 = 70
        # floor = 100 * (1 - 0.05) = 95
        # stop_raw(70) < floor(95), so capped at 95
        plan = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes, score=75
        )
        expected_floor = entry * (1.0 - 0.05)
        assert plan.stop == pytest.approx(expected_floor, abs=0.01)


# ─── Test 5-6: risk_per_share ─────────────────────────────────────────────────


class TestRiskPerShare:
    """Tests for risk_per_share computation."""

    def test_risk_per_share_positive(self):
        """risk_per_share > 0 for valid inputs."""
        cfg = make_config()
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.risk_per_share > 0

    def test_risk_per_share_rejection_when_entry_at_stop(self):
        """risk_per_share rejection when entry equals stop (ATR=0 scenario).

        If all bars are identical (no volatility), ATR=0 and stop=entry,
        leading to risk_per_share=0 which must be rejected.
        """
        cfg = make_config()
        engine = TradeEngine(cfg)
        # Create bars where ATR will be 0: all same values
        n = 15
        highs = np.full(n, 100.0)
        lows = np.full(n, 100.0)
        closes = np.full(n, 100.0)
        with pytest.raises(ValueError, match="Invalid risk"):
            engine.build_plan(
                entry=100.0, highs=highs, lows=lows, closes=closes, score=75
            )


# ─── Test 7-8: Targets at R-multiples ────────────────────────────────────────


class TestTargets:
    """Tests for target1 and target2 computation."""

    def test_targets_at_correct_r_multiples(self):
        """target1 and target2 at correct R-multiples of risk."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        entry = 200.0
        plan = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes, score=75
        )
        # ATR=10, atr_mult=1.0, stop=190, risk=10
        # target1 = 200 + TARGET1_MULT(1.5)*10 = 215
        # target2 = 200 + TARGET2_MULT(2.5)*10 = 225
        assert plan.target1 == pytest.approx(200 + cfg.TRADE_TARGET1_MULT * 10, abs=0.01)
        assert plan.target2 == pytest.approx(200 + cfg.TRADE_TARGET2_MULT * 10, abs=0.01)

    def test_target1_less_than_target2(self):
        """target1 < target2 invariant holds."""
        cfg = make_config()
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.target1 < plan.target2

    def test_target1_mult_gte_target2_mult_rejected(self):
        """TARGET1_MULT >= TARGET2_MULT configuration rejected with error."""
        # Config.validate() checks class-level attributes; override them temporarily
        original_t1 = Config.TRADE_TARGET1_MULT
        original_t2 = Config.TRADE_TARGET2_MULT
        try:
            Config.TRADE_TARGET1_MULT = 3.0
            Config.TRADE_TARGET2_MULT = 2.0
            with pytest.raises(ValueError, match="TRADE_TARGET1_MULT"):
                Config.validate()
        finally:
            Config.TRADE_TARGET1_MULT = original_t1
            Config.TRADE_TARGET2_MULT = original_t2


# ─── Test 10-11: Reward:Risk ──────────────────────────────────────────────────


class TestRewardRisk:
    """Tests for reward_risk and low_rr flag."""

    def test_reward_risk_equals_target1_mult(self):
        """reward_risk equals TARGET1_MULT (within epsilon) before earnings."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.reward_risk == pytest.approx(
            cfg.TRADE_TARGET1_MULT, abs=0.01
        )

    def test_low_rr_flag_below_threshold(self):
        """low_rr set True when reward_risk < MIN_REWARD_RISK."""
        # Set TARGET1_MULT=1.0 so reward_risk=1.0 < default MIN_REWARD_RISK=1.5
        cfg = make_config(TRADE_ATR_MULT=1.0, TRADE_TARGET1_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.reward_risk == pytest.approx(1.0, abs=0.01)
        assert plan.low_rr is True

    def test_low_rr_flag_above_threshold(self):
        """low_rr set False when reward_risk >= MIN_REWARD_RISK."""
        # TARGET1_MULT=2.0, MIN_REWARD_RISK=1.5 → reward_risk=2.0 >= 1.5
        cfg = make_config(TRADE_ATR_MULT=1.0, TRADE_TARGET1_MULT=2.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.reward_risk == pytest.approx(2.0, abs=0.01)
        assert plan.low_rr is False

    def test_low_rr_flag_at_exact_threshold(self):
        """low_rr False when reward_risk == MIN_REWARD_RISK (boundary)."""
        # Set TARGET1_MULT=1.5 to match MIN_REWARD_RISK=1.5
        cfg = make_config(TRADE_ATR_MULT=1.0, TRADE_TARGET1_MULT=1.5)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.reward_risk == pytest.approx(1.5, abs=0.01)
        assert plan.low_rr is False  # not less than threshold


# ─── Test 12-14: Expected move and vol_source ─────────────────────────────────


class TestExpectedMove:
    """Tests for expected_move_pct and vol_source."""

    def test_expected_move_historical_formula(self):
        """expected_move_pct = daily_sigma × sqrt(horizon) × 100 for historical."""
        cfg = make_config(TRADE_ATR_MULT=1.0, TRADE_HORIZON_DAYS=21)
        engine = TradeEngine(cfg)
        # Need enough data for historical sigma (21+ bars)
        n = 30
        rng = np.random.default_rng(123)
        closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        highs = closes + 2.0
        lows = closes - 2.0
        entry = float(closes[-1])

        plan = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes, score=75
        )

        # Verify formula: expected_move_pct = sigma * sqrt(horizon) * 100
        daily_sigma = TradeEngine.compute_historical_sigma(closes, lookback=20)
        assert daily_sigma is not None
        expected = round(daily_sigma * math.sqrt(21) * 100, 2)
        assert plan.expected_move_pct == pytest.approx(expected, abs=0.01)
        assert plan.vol_source == "historical"

    def test_vol_source_options_iv(self):
        """vol_source set to 'options_iv' when valid options_iv supplied."""
        cfg = make_config(TRADE_ATR_MULT=1.0, TRADE_HORIZON_DAYS=21)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        entry = 200.0

        plan = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes,
            score=75, options_iv=0.30
        )
        assert plan.vol_source == "options_iv"
        # daily_sigma = 0.30 / sqrt(252)
        daily_sigma = 0.30 / math.sqrt(252)
        expected = round(daily_sigma * math.sqrt(21) * 100, 2)
        assert plan.expected_move_pct == pytest.approx(expected, abs=0.01)

    def test_vol_source_historical_when_options_iv_none(self):
        """vol_source 'historical' when options_iv is None."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        n = 30
        rng = np.random.default_rng(99)
        closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        highs = closes + 2.0
        lows = closes - 2.0
        entry = float(closes[-1])

        plan = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes,
            score=75, options_iv=None
        )
        assert plan.vol_source == "historical"

    def test_none_options_iv_never_raises(self):
        """None options_iv never raises, falls back to historical."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        # Should not raise even with None
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes,
            score=75, options_iv=None
        )
        assert plan.vol_source == "historical"

    def test_invalid_options_iv_falls_back(self):
        """Invalid options_iv (0, negative, >5.0) falls back to historical."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        n = 30
        rng = np.random.default_rng(77)
        closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        highs = closes + 2.0
        lows = closes - 2.0
        entry = float(closes[-1])

        for invalid_iv in [0.0, -0.5, 6.0]:
            plan = engine.build_plan(
                entry=entry, highs=highs, lows=lows, closes=closes,
                score=75, options_iv=invalid_iv
            )
            assert plan.vol_source == "historical"


# ─── Test 15-17: Resistance ───────────────────────────────────────────────────


class TestResistance:
    """Tests for resistance computation and annotation."""

    def test_resistance_max_of_60d_and_252d_high(self):
        """Resistance equals max of 60-day high and 252-day high."""
        # Create 260 bars: first 200 bars peak at 150, last 60 peak at 130
        highs = np.full(260, 110.0)
        highs[50] = 150.0  # 252-day high (within trailing 252 bars)
        highs[220] = 130.0  # 60-day high (within last 60 bars)

        resistance, data_limited = TradeEngine.compute_resistance(highs)
        assert resistance == pytest.approx(150.0, abs=0.01)
        assert data_limited is False

    def test_resistance_60d_higher_than_252d(self):
        """When 60-day high > 252-day high, resistance = 60-day high."""
        highs = np.full(260, 100.0)
        highs[250] = 200.0  # Within last 60 bars and within 252 bars

        resistance, data_limited = TradeEngine.compute_resistance(highs)
        assert resistance == pytest.approx(200.0, abs=0.01)

    def test_resistance_data_limited_flag(self):
        """resistance_data_limited True when < 60 bars."""
        highs = np.full(50, 100.0)
        highs[10] = 120.0

        resistance, data_limited = TradeEngine.compute_resistance(highs)
        assert resistance == pytest.approx(120.0, abs=0.01)
        assert data_limited is True

    def test_target_above_resistance_true(self):
        """target_above_resistance True iff target1 > resistance."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        # Use low resistance so target1 > resistance
        n = 30
        highs = np.full(n, 105.0)  # resistance = 105
        lows = np.full(n, 95.0)
        closes = np.full(n, 100.0)
        # ATR=10, entry=200, stop=190, risk=10, target1=220
        # resistance=105 < target1=220 → target_above_resistance=True
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.target_above_resistance is True
        assert plan.target1 > plan.resistance

    def test_target_above_resistance_false(self):
        """target_above_resistance False when target1 <= resistance."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        # Use very high resistance so target1 < resistance
        n = 30
        highs = np.full(n, 500.0)  # resistance = 500
        lows = np.full(n, 95.0)
        closes = np.full(n, 100.0)
        # entry=200, target1=220, resistance=500 → False
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.target_above_resistance is False
        assert plan.target1 <= plan.resistance

    def test_resistance_never_mutates_targets(self):
        """Resistance never mutates target1 or target2."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()
        entry = 200.0

        plan = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes, score=75
        )
        # Verify targets are purely formula-based (not affected by resistance)
        risk = plan.risk_per_share
        expected_t1 = entry + cfg.TRADE_TARGET1_MULT * risk
        expected_t2 = entry + cfg.TRADE_TARGET2_MULT * risk
        assert plan.target1 == pytest.approx(expected_t1, abs=0.01)
        assert plan.target2 == pytest.approx(expected_t2, abs=0.01)


# ─── Test 18-20: Earnings ─────────────────────────────────────────────────────


class TestEarnings:
    """Tests for earnings_in_window and target widening."""

    def test_earnings_in_window_set_when_provided(self):
        """earnings_in_window set when earnings_date within horizon."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        n = 30
        rng = np.random.default_rng(55)
        closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        highs = closes + 2.0
        lows = closes - 2.0
        entry = float(closes[-1])

        plan = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes,
            score=75, earnings_date="2024-03-15"
        )
        assert plan.earnings_in_window == "2024-03-15"

    def test_earnings_in_window_null_when_none(self):
        """earnings_in_window null when earnings_date is None."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()

        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes,
            score=75, earnings_date=None
        )
        assert plan.earnings_in_window is None

    def test_earnings_widen_target2_and_expected_move(self):
        """Earnings widen: expected_move_pct increases, target1 unchanged.

        When earnings are present, expected_move_pct is multiplied by
        EARNINGS_WIDEN_FACTOR and target2 is recomputed from the widened move.
        target2 = entry * (1 + widened_expected_move_pct/100).
        """
        cfg = make_config(TRADE_ATR_MULT=1.0, TRADE_HORIZON_DAYS=21)
        engine = TradeEngine(cfg)
        n = 30
        rng = np.random.default_rng(88)
        closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        highs = closes + 2.0
        lows = closes - 2.0
        entry = float(closes[-1])

        # Without earnings
        plan_no_earnings = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes,
            score=75, earnings_date=None
        )

        # With earnings
        plan_with_earnings = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes,
            score=75, earnings_date="2024-03-15"
        )

        # target1 unchanged
        assert plan_with_earnings.target1 == pytest.approx(
            plan_no_earnings.target1, abs=0.01
        )
        # expected_move_pct widened by factor
        assert plan_with_earnings.expected_move_pct is not None
        assert plan_no_earnings.expected_move_pct is not None
        assert plan_with_earnings.expected_move_pct == pytest.approx(
            plan_no_earnings.expected_move_pct * cfg.TRADE_EARNINGS_WIDEN_FACTOR,
            abs=0.01,
        )
        # target2 is recomputed from widened move:
        # target2 = entry * (1 + widened_expected_move_pct / 100)
        expected_t2 = entry * (1.0 + plan_with_earnings.expected_move_pct / 100.0)
        assert plan_with_earnings.target2 == pytest.approx(expected_t2, abs=0.01)


# ─── Test 21-23: Probability ──────────────────────────────────────────────────


class TestProbability:
    """Tests for prob_hit_target1 and calibration."""

    def test_prob_reduced_when_earnings_set(self):
        """prob_hit_target1 reduced when earnings_in_window set, floored at 0.05."""
        cal = make_calibration_table({"high_tight": 0.65})
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg, calibration=cal)
        highs, lows, closes = make_known_ohlc()
        entry = 200.0

        # Without earnings
        plan_no = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes,
            score=75, earnings_date=None
        )
        # With earnings
        plan_yes = engine.build_plan(
            entry=entry, highs=highs, lows=lows, closes=closes,
            score=75, earnings_date="2024-03-15"
        )

        assert plan_yes.prob_hit_target1 is not None
        assert plan_no.prob_hit_target1 is not None
        assert plan_yes.prob_hit_target1 <= plan_no.prob_hit_target1
        assert plan_yes.prob_hit_target1 >= 0.05

    def test_prob_floor_at_005(self):
        """prob_hit_target1 floored at 0.05 even with heavy discount."""
        # score=75 → "high", ATR=10 on entry=200 → atr_pct=5% → "normal"
        # bucket = "high_normal"
        cal = make_calibration_table({"high_normal": 0.06})
        cfg = make_config(
            TRADE_ATR_MULT=1.0,
            TRADE_EARNINGS_CONFIDENCE_DISCOUNT=0.5
        )
        engine = TradeEngine(cfg, calibration=cal)
        highs, lows, closes = make_known_ohlc()

        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes,
            score=75, earnings_date="2024-03-15"
        )
        # 0.06 * 0.5 = 0.03 → floored to 0.05
        assert plan.prob_hit_target1 == pytest.approx(0.05, abs=0.01)

    def test_prob_from_calibration_table(self):
        """prob_hit_target1 lookup from calibration table with known bucket."""
        # score=75 → "high", ATR=10 on entry=200 → atr_pct=5% → "normal"
        # bucket = "high_normal"
        cal = make_calibration_table({"high_normal": 0.58})
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg, calibration=cal)
        highs, lows, closes = make_known_ohlc()

        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.prob_hit_target1 == pytest.approx(0.58, abs=0.01)
        assert plan.calibration_available is True

    def test_prob_defaults_050_when_bucket_missing(self):
        """prob_hit_target1 defaults to 0.50 when calibration not available."""
        # Use a calibration table without the needed bucket
        cal = make_calibration_table({"low_wide": 0.40})
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg, calibration=cal)
        highs, lows, closes = make_known_ohlc()

        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.prob_hit_target1 == pytest.approx(0.50, abs=0.01)
        assert plan.calibration_available is False

    def test_prob_defaults_050_when_no_calibration(self):
        """prob_hit_target1 defaults to 0.50 when no CalibrationTable."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg, calibration=None)
        highs, lows, closes = make_known_ohlc()

        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes, score=75
        )
        assert plan.prob_hit_target1 == pytest.approx(0.50, abs=0.01)
        assert plan.calibration_available is False


# ─── Test 24: Analyst fields ──────────────────────────────────────────────────


class TestAnalystFields:
    """Tests for analyst field passthrough."""

    def test_analyst_fields_pass_through(self):
        """Analyst fields pass through when supplied."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()

        analyst = {"target": 250.0, "low": 180.0, "high": 300.0}
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes,
            score=75, analyst=analyst
        )
        assert plan.analyst_target == 250.0
        assert plan.analyst_low == 180.0
        assert plan.analyst_high == 300.0

    def test_analyst_fields_null_when_not_supplied(self):
        """Analyst fields null when not supplied."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()

        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes,
            score=75, analyst=None
        )
        assert plan.analyst_target is None
        assert plan.analyst_low is None
        assert plan.analyst_high is None

    def test_analyst_partial_fields(self):
        """Analyst with partial fields passes through available, None for missing."""
        cfg = make_config(TRADE_ATR_MULT=1.0)
        engine = TradeEngine(cfg)
        highs, lows, closes = make_known_ohlc()

        analyst = {"target": 250.0}  # low and high missing
        plan = engine.build_plan(
            entry=200.0, highs=highs, lows=lows, closes=closes,
            score=75, analyst=analyst
        )
        assert plan.analyst_target == 250.0
        assert plan.analyst_low is None
        assert plan.analyst_high is None
