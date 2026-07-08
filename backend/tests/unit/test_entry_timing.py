"""Unit tests for the entry timing classifier (core/entry_timing.py)."""

from core.entry_timing import classify_entry_timing
from core.models import TechnicalIndicators


def _ind(**kw) -> TechnicalIndicators:
    return TechnicalIndicators(**kw)


class TestOverbought:
    """Stocks that should be flagged as overbought / profit-taking risk."""

    def test_extreme_rsi_alone_is_overbought(self):
        et = classify_entry_timing(106.0, _ind(sma_50=100.0, rsi_14=80.0))
        assert et.zone == "overbought"

    def test_overbought_rsi_plus_stretched(self):
        # RSI 76 (overbought) + 14% above SMA50 (stretched) = 2 signals
        et = classify_entry_timing(114.0, _ind(sma_50=100.0, rsi_14=76.0))
        assert et.zone == "overbought"

    def test_the_burned_scenario(self):
        # Real case: RSI 76, 14% above SMA50, at 20d high, up 22% in 10d
        et = classify_entry_timing(
            114.0,
            _ind(sma_50=100.0, rsi_14=76.0, roc_10=22.0, proximity_to_20d_high=99.0),
        )
        assert et.zone == "overbought"
        assert len(et.reasons) >= 3

    def test_parabolic_plus_overbought(self):
        et = classify_entry_timing(
            112.0,
            _ind(sma_50=100.0, rsi_14=72.0, roc_10=25.0, proximity_to_20d_high=99.0),
        )
        assert et.zone == "overbought"


class TestBuyZone:
    """Healthy uptrend stocks with room to run."""

    def test_healthy_rsi_not_stretched(self):
        et = classify_entry_timing(
            104.0,
            _ind(sma_50=100.0, rsi_14=52.0, roc_10=4.0, proximity_to_20d_high=88.0),
        )
        assert et.zone == "buy_zone"

    def test_pulled_back_from_high(self):
        et = classify_entry_timing(
            103.0,
            _ind(sma_50=100.0, rsi_14=48.0, roc_10=2.0, proximity_to_20d_high=85.0),
        )
        assert et.zone == "buy_zone"
        assert len(et.reasons) >= 1


class TestExtended:
    """Stocks getting stretched but not yet overbought."""

    def test_elevated_rsi_and_extension(self):
        # RSI 67 (elevated) + 9% above SMA50 = 2 extended signals
        et = classify_entry_timing(109.0, _ind(sma_50=100.0, rsi_14=67.0, roc_10=8.0))
        assert et.zone == "extended"

    def test_single_overbought_signal_is_extended(self):
        # Only RSI 71 overbought, nothing else → 1 overbought signal → extended
        et = classify_entry_timing(
            104.0,
            _ind(sma_50=100.0, rsi_14=71.0, roc_10=3.0, proximity_to_20d_high=85.0),
        )
        assert et.zone == "extended"


class TestMissingData:
    """Missing indicators handled conservatively."""

    def test_no_indicators_defaults_buy_zone(self):
        et = classify_entry_timing(100.0, _ind())
        assert et.zone == "buy_zone"

    def test_metrics_populated(self):
        et = classify_entry_timing(110.0, _ind(sma_50=100.0, rsi_14=65.0, roc_10=5.0))
        assert et.rsi == 65.0
        assert et.dist_above_sma50_pct == 10.0
        assert et.roc_10 == 5.0
