"""
Property-based tests for the Trade Engine.

Tests correctness properties P1, P2, P3, P4, P9 from the design document
using hypothesis to generate random valid inputs and verify universal invariants.
"""

import sys
from pathlib import Path

import numpy as np
from hypothesis import given, settings, assume, Phase
from hypothesis import strategies as st

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import Config
from core.trade_engine import TradeEngine, TradePlan


# ─── Custom Hypothesis Strategies ────────────────────────────────────────────


@st.composite
def st_valid_ohlc(draw, min_bars: int = 15, max_bars: int = 30):
    """Generate valid OHLC arrays with highs >= lows, closes between high and low,
    all positive prices, and at least min_bars bars.

    Uses a single draw of a flat list of floats and reshapes them, avoiding
    per-element draws for performance.
    """
    n_bars = draw(st.integers(min_value=min_bars, max_value=max_bars))

    # Draw base prices and spreads as flat arrays
    base_list = draw(
        st.lists(
            st.floats(min_value=20.0, max_value=400.0, allow_nan=False, allow_infinity=False),
            min_size=n_bars,
            max_size=n_bars,
        )
    )
    spread_list = draw(
        st.lists(
            st.floats(min_value=0.5, max_value=15.0, allow_nan=False, allow_infinity=False),
            min_size=n_bars,
            max_size=n_bars,
        )
    )
    close_fracs = draw(
        st.lists(
            st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False),
            min_size=n_bars,
            max_size=n_bars,
        )
    )

    bases = np.array(base_list, dtype=np.float64)
    spreads = np.array(spread_list, dtype=np.float64)
    fracs = np.array(close_fracs, dtype=np.float64)

    highs = bases + spreads / 2.0
    lows = bases - spreads / 2.0
    # Ensure lows are positive
    lows = np.maximum(lows, 0.5)
    # Ensure highs > lows
    highs = np.maximum(highs, lows + 0.01)
    # Closes between low and high
    closes = lows + fracs * (highs - lows)

    return (highs, lows, closes)


def make_config(
    atr_mult: float = 2.0,
    max_loss_pct: float = 0.10,
    target1_mult: float = 2.0,
    target2_mult: float = 3.0,
    min_reward_risk: float = 1.5,
    horizon_days: int = 21,
    sigma_lookback: int = 20,
) -> Config:
    """Create a Config instance with custom trade engine parameters."""
    cfg = Config()
    cfg.TRADE_ATR_MULT = atr_mult
    cfg.TRADE_MAX_LOSS_PCT = max_loss_pct
    cfg.TRADE_TARGET1_MULT = target1_mult
    cfg.TRADE_TARGET2_MULT = target2_mult
    cfg.TRADE_MIN_REWARD_RISK = min_reward_risk
    cfg.TRADE_HORIZON_DAYS = horizon_days
    cfg.TRADE_SIGMA_LOOKBACK = sigma_lookback
    return cfg


# ─── Property 1: Stop-Risk Invariant ─────────────────────────────────────────


class TestStopRiskInvariant:
    """
    Feature: trade-engine, Property 1: Stop-Risk Invariant

    For all valid OHLC inputs (≥15 bars, highs >= lows, all positive), the computed
    stop SHALL be strictly less than entry AND risk_per_share SHALL be > 0 AND stop
    SHALL never be below entry × (1 − max_loss_pct).

    **Validates: Requirements 1.1, 1.2, 1.3**
    """

    @given(
        ohlc=st_valid_ohlc(),
        entry=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        atr_mult=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        max_loss_pct=st.floats(min_value=0.01, max_value=0.25, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_stop_less_than_entry_and_risk_positive_and_stop_above_floor(
        self, ohlc, entry, atr_mult, max_loss_pct
    ):
        """P1: stop < entry AND risk > 0 AND stop >= entry * (1 - max_loss_pct)"""
        highs, lows, closes = ohlc
        cfg = make_config(atr_mult=atr_mult, max_loss_pct=max_loss_pct)
        engine = TradeEngine(cfg)

        try:
            plan = engine.build_plan(
                entry=entry,
                highs=highs,
                lows=lows,
                closes=closes,
                score=70,
            )
        except ValueError:
            # ValueError means risk_per_share <= 0 or insufficient data,
            # which is a valid rejection — property does not apply to rejected plans
            return

        # P1a: stop < entry
        assert plan.stop < entry, (
            f"Stop ({plan.stop}) must be strictly less than entry ({entry})"
        )

        # P1b: risk_per_share > 0
        assert plan.risk_per_share > 0, (
            f"risk_per_share ({plan.risk_per_share}) must be strictly positive"
        )

        # P1c: stop >= entry * (1 - max_loss_pct)
        # Account for rounding to 2 decimal places in the implementation:
        # stop is rounded via round(stop, 2) after the floor cap, so it may be
        # up to 0.005 below the exact floor value.
        floor = entry * (1.0 - max_loss_pct)
        assert plan.stop >= floor - 0.01, (
            f"Stop ({plan.stop}) must not be below floor "
            f"({floor} = entry * (1 - {max_loss_pct})), "
            f"allowing 0.01 for 2dp rounding"
        )


# ─── Property 2: Target R-Multiple Correctness ───────────────────────────────


class TestTargetRMultipleCorrectness:
    """
    Feature: trade-engine, Property 2: Target R-Multiple Correctness

    For all valid trade plans, target1 == entry + TARGET1_MULT × risk (within ε)
    AND target2 == entry + TARGET2_MULT × risk (within ε)
    AND target1 < target2 AND reward_risk == TARGET1_MULT (within ε).

    **Validates: Requirements 2.1, 2.2, 2.4, 5.1**
    """

    @given(
        ohlc=st_valid_ohlc(),
        entry=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        target1_mult=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_targets_follow_r_multiple_formula(self, ohlc, entry, target1_mult):
        """P2: target1 = entry + T1*risk, target2 = entry + T2*risk, target1 < target2,
        reward_risk = T1_MULT (within ε)"""
        highs, lows, closes = ohlc

        # Ensure target2_mult > target1_mult
        target2_mult = target1_mult + 1.0

        cfg = make_config(target1_mult=target1_mult, target2_mult=target2_mult)
        engine = TradeEngine(cfg)

        try:
            plan = engine.build_plan(
                entry=entry,
                highs=highs,
                lows=lows,
                closes=closes,
                score=70,
            )
        except ValueError:
            return

        risk = plan.risk_per_share
        epsilon = 0.02  # Account for rounding to 2 decimal places

        # P2a: target1 == entry + T1_MULT * risk (within ε)
        expected_t1 = entry + target1_mult * risk
        assert abs(plan.target1 - expected_t1) <= epsilon, (
            f"target1 ({plan.target1}) != entry + T1*risk ({expected_t1}), "
            f"diff={abs(plan.target1 - expected_t1)}"
        )

        # P2b: target2 == entry + T2_MULT * risk (within ε) when no earnings
        expected_t2 = entry + target2_mult * risk
        assert abs(plan.target2 - expected_t2) <= epsilon, (
            f"target2 ({plan.target2}) != entry + T2*risk ({expected_t2}), "
            f"diff={abs(plan.target2 - expected_t2)}"
        )

        # P2c: target1 < target2
        assert plan.target1 < plan.target2, (
            f"target1 ({plan.target1}) must be strictly less than target2 ({plan.target2})"
        )

        # P2d: reward_risk == TARGET1_MULT (within ε)
        assert abs(plan.reward_risk - target1_mult) <= epsilon, (
            f"reward_risk ({plan.reward_risk}) != TARGET1_MULT ({target1_mult}), "
            f"diff={abs(plan.reward_risk - target1_mult)}"
        )


# ─── Property 3: Resistance Annotation Correctness ───────────────────────────


class TestResistanceAnnotationCorrectness:
    """
    Feature: trade-engine, Property 3: Resistance Annotation Correctness

    target_above_resistance == True iff target1 > resistance;
    resistance never mutates targets.

    **Validates: Requirements 4.2, 4.3, 4.5**
    """

    @given(
        ohlc=st_valid_ohlc(),
        entry=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_resistance_annotation_and_target_immutability(self, ohlc, entry):
        """P3: target_above_resistance iff target1 > resistance; targets unchanged by resistance"""
        highs, lows, closes = ohlc
        cfg = make_config()
        engine = TradeEngine(cfg)

        try:
            plan = engine.build_plan(
                entry=entry,
                highs=highs,
                lows=lows,
                closes=closes,
                score=70,
            )
        except ValueError:
            return

        # P3a: target_above_resistance == True iff target1 > resistance
        if plan.target1 > plan.resistance:
            assert plan.target_above_resistance is True, (
                f"target_above_resistance should be True when target1 ({plan.target1}) > "
                f"resistance ({plan.resistance})"
            )
        else:
            assert plan.target_above_resistance is False, (
                f"target_above_resistance should be False when target1 ({plan.target1}) <= "
                f"resistance ({plan.resistance})"
            )

        # P3b: Resistance never mutates targets — verify targets follow R-multiple formula
        risk = plan.risk_per_share
        expected_t1 = entry + cfg.TRADE_TARGET1_MULT * risk
        expected_t2 = entry + cfg.TRADE_TARGET2_MULT * risk
        epsilon = 0.02

        assert abs(plan.target1 - expected_t1) <= epsilon, (
            f"Resistance mutated target1: {plan.target1} != expected {expected_t1}"
        )
        assert abs(plan.target2 - expected_t2) <= epsilon, (
            f"Resistance mutated target2: {plan.target2} != expected {expected_t2}"
        )


# ─── Property 4: Low R:R Flag ────────────────────────────────────────────────


class TestLowRRFlag:
    """
    Feature: trade-engine, Property 4: Low Reward-Risk Flag

    low_rr == True iff reward_risk < MIN_REWARD_RISK.

    **Validates: Requirements 5.2, 5.3**
    """

    @given(
        ohlc=st_valid_ohlc(),
        entry=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_rr=st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False),
        target1_mult=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_low_rr_flag_iff_reward_risk_below_threshold(
        self, ohlc, entry, min_rr, target1_mult
    ):
        """P4: low_rr == True iff reward_risk < MIN_REWARD_RISK"""
        highs, lows, closes = ohlc

        # Ensure target2_mult > target1_mult
        target2_mult = target1_mult + 1.0

        cfg = make_config(
            target1_mult=target1_mult,
            target2_mult=target2_mult,
            min_reward_risk=min_rr,
        )
        engine = TradeEngine(cfg)

        try:
            plan = engine.build_plan(
                entry=entry,
                highs=highs,
                lows=lows,
                closes=closes,
                score=70,
            )
        except ValueError:
            return

        # P4: low_rr iff reward_risk < min_reward_risk
        if plan.reward_risk < min_rr:
            assert plan.low_rr is True, (
                f"low_rr should be True when reward_risk ({plan.reward_risk}) < "
                f"MIN_REWARD_RISK ({min_rr})"
            )
        else:
            assert plan.low_rr is False, (
                f"low_rr should be False when reward_risk ({plan.reward_risk}) >= "
                f"MIN_REWARD_RISK ({min_rr})"
            )


# ─── Property 9: ATR/Expected Move Math ──────────────────────────────────────


class TestATRExpectedMoveMath:
    """
    Feature: trade-engine, Property 9: ATR and Expected Move Mathematical Correctness

    ATR == mean of last 14 true ranges;
    expected_move_pct == sigma × √horizon × 100 in historical branch.

    **Validates: Requirements 1.5, 3.1, 3.2**
    """

    @given(
        ohlc=st_valid_ohlc(min_bars=21, max_bars=30),
    )
    @settings(max_examples=100, deadline=None)
    def test_atr_is_mean_of_14_true_ranges(self, ohlc):
        """P9a: ATR(14) == arithmetic mean of the last 14 true ranges"""
        highs, lows, closes = ohlc

        # Compute ATR manually for verification
        n = 14
        prev_closes = closes[:-1]
        current_highs = highs[1:]
        current_lows = lows[1:]

        high_low = current_highs - current_lows
        high_prev_close = np.abs(current_highs - prev_closes)
        low_prev_close = np.abs(current_lows - prev_closes)

        true_ranges = np.maximum(high_low, np.maximum(high_prev_close, low_prev_close))
        expected_atr = float(np.mean(true_ranges[-n:]))

        # Compute via TradeEngine
        computed_atr = TradeEngine.compute_atr(highs, lows, closes, n=14)

        assert abs(computed_atr - expected_atr) < 1e-10, (
            f"ATR mismatch: computed={computed_atr}, expected={expected_atr}"
        )

    @given(
        ohlc=st_valid_ohlc(min_bars=22, max_bars=30),
        entry=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        horizon=st.integers(min_value=1, max_value=63),
    )
    @settings(max_examples=100, deadline=None)
    def test_expected_move_pct_formula_historical_branch(self, ohlc, entry, horizon):
        """P9b: expected_move_pct == daily_sigma × √horizon × 100 in historical branch"""
        highs, lows, closes = ohlc

        cfg = make_config(horizon_days=horizon, sigma_lookback=20)
        engine = TradeEngine(cfg)

        try:
            plan = engine.build_plan(
                entry=entry,
                highs=highs,
                lows=lows,
                closes=closes,
                score=70,
                # No options_iv → forces historical branch
                options_iv=None,
            )
        except ValueError:
            return

        # If expected_move_pct is None, insufficient data for sigma computation
        if plan.expected_move_pct is None:
            return

        # Verify vol_source is historical
        assert plan.vol_source == "historical", (
            f"vol_source should be 'historical' when no options_iv supplied, got '{plan.vol_source}'"
        )

        # Compute daily sigma manually from closes
        lookback = cfg.TRADE_SIGMA_LOOKBACK
        if len(closes) >= lookback + 1:
            recent_prices = closes[-(lookback + 1):]
            log_returns = np.log(recent_prices[1:] / recent_prices[:-1])
            daily_sigma = float(np.std(log_returns, ddof=0))

            # expected_move_pct = daily_sigma * sqrt(horizon) * 100
            expected_move_pct = round(daily_sigma * np.sqrt(horizon) * 100, 2)

            assert abs(plan.expected_move_pct - expected_move_pct) < 0.02, (
                f"expected_move_pct mismatch: plan={plan.expected_move_pct}, "
                f"expected={expected_move_pct}"
            )
