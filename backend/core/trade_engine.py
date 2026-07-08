"""
Trade Engine

Computes risk-defined trade plans from OHLC + optional enhancement data.
Pure and deterministic: all I/O (Massive API calls) happens upstream in the
orchestrator. This class receives pre-fetched data as arguments.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config import Config


@dataclass
class TradePlan:
    """Complete trade plan for a BUY candidate."""

    # Core pricing
    entry: float
    stop: float
    stop_pct: float  # Percentage loss from entry (negative)
    target1: float
    target1_pct: float  # Percentage gain from entry
    target2: float
    target2_pct: float  # Percentage gain from entry
    risk_per_share: float  # entry - stop

    # Risk metrics
    reward_risk: float | None  # target1_R (None if data unavailable)
    low_rr: bool  # True if reward_risk < min_reward_risk
    data_unavailable: bool  # True if reward_risk cannot be computed

    # Expected move
    expected_move_pct: float | None  # 1-sigma % move over horizon (None if insufficient data)
    vol_source: str  # "options_iv" | "historical"

    # Resistance
    resistance: float
    target_above_resistance: bool
    resistance_data_limited: bool  # True if < 60 bars available for resistance

    # Earnings
    earnings_in_window: str | None  # YYYY-MM-DD or None

    # Probability
    prob_hit_target1: float | None  # 0.0-1.0, from calibration table
    calibration_available: bool  # False if bucket missing -> default 0.50 used

    # Analyst (optional)
    analyst_target: float | None
    analyst_low: float | None
    analyst_high: float | None


class TradeEngine:
    """Computes risk-defined trade plans from OHLC + optional enhancement data.

    Pure and deterministic: all I/O (Massive API calls) happens upstream in the
    orchestrator. This class receives pre-fetched data as arguments.
    """

    def __init__(self, cfg: Config, calibration=None):
        """Initialize the TradeEngine.

        Args:
            cfg: Application config with trade parameters.
            calibration: Pre-loaded CalibrationTable (None -> default prob 0.50).
        """
        self.cfg = cfg
        self.calibration = calibration

    @staticmethod
    def compute_atr(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        n: int = 14,
    ) -> float:
        """Compute Average True Range over n periods.

        True Range = max(high - low, |high - prev_close|, |low - prev_close|)
        ATR = mean of last n true ranges

        Requires len(highs) >= n + 1 (15 bars for ATR-14).

        Args:
            highs: Array of daily high prices.
            lows: Array of daily low prices.
            closes: Array of daily close prices.
            n: Number of periods for ATR (default 14).

        Returns:
            ATR value as float.

        Raises:
            ValueError: If fewer than n + 1 bars available.
        """
        min_bars = n + 1
        num_bars = len(highs)

        if num_bars < min_bars or len(lows) < min_bars or len(closes) < min_bars:
            actual = min(num_bars, len(lows), len(closes))
            raise ValueError(
                f"Insufficient OHLC data for ATR({n}): need at least {min_bars} bars, "
                f"got {actual}"
            )

        # Compute true range for bars 1..len-1 (need previous close)
        prev_closes = closes[:-1]
        current_highs = highs[1:]
        current_lows = lows[1:]

        high_low = current_highs - current_lows
        high_prev_close = np.abs(current_highs - prev_closes)
        low_prev_close = np.abs(current_lows - prev_closes)

        true_ranges = np.maximum(high_low, np.maximum(high_prev_close, low_prev_close))

        # ATR is the mean of the last n true range values
        atr = float(np.mean(true_ranges[-n:]))
        return atr

    @staticmethod
    def compute_resistance(highs: np.ndarray) -> tuple[float, bool]:
        """Compute nearest resistance = max(60-day high, 252-day high).

        Resistance is defined as the maximum of:
        - The highest high over the trailing 60 trading days
        - The highest high over the trailing 252 trading days (52-week high)

        If fewer than 60 bars are available, uses all available data and
        flags data_limited=True.

        Args:
            highs: Array of daily high prices (float64).

        Returns:
            Tuple of (resistance_price, data_limited) where data_limited is True
            if fewer than 60 bars available for resistance computation.
        """
        n = len(highs)
        data_limited = n < 60

        # 60-day high: max of last 60 bars (or all bars if fewer)
        sixty_day_high = float(np.max(highs[-60:])) if n >= 60 else float(np.max(highs))

        # 252-day (52-week) high: max of last 252 bars (or all bars if fewer)
        year_high = float(np.max(highs[-252:])) if n >= 252 else float(np.max(highs))

        resistance = max(sixty_day_high, year_high)
        return (resistance, data_limited)

    @staticmethod
    def compute_historical_sigma(prices: np.ndarray, lookback: int = 20) -> float | None:
        """Compute daily sigma from log returns over trailing window.

        Args:
            prices: Array of daily close prices (float64).
            lookback: Minimum number of daily returns required (default 20).

        Returns:
            Daily standard deviation of log returns, or None if fewer than
            `lookback` prices available (need lookback+1 prices for lookback returns).
        """
        if len(prices) < lookback + 1:
            return None

        # Compute log returns over the trailing lookback window
        recent_prices = prices[-(lookback + 1):]
        log_returns = np.log(recent_prices[1:] / recent_prices[:-1])
        return float(np.std(log_returns, ddof=0))

    def build_plan(
        self,
        *,
        entry: float,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        score: int,
        horizon: int | None = None,
        earnings_date: str | None = None,
        options_iv: float | None = None,
        analyst: dict | None = None,
    ) -> TradePlan:
        """Build a complete trade plan for a BUY candidate.

        Args:
            entry: Current price (entry point).
            highs: Array of daily high prices (float64).
            lows: Array of daily low prices (float64).
            closes: Array of daily close prices (float64).
            score: Bullish score (0-100) for calibration bucket.
            horizon: Trading days horizon (default from config).
            earnings_date: Earliest earnings date in YYYY-MM-DD if within window, else None.
            options_iv: Annualized ATM implied volatility (0 < iv <= 5.0), or None.
            analyst: Dict with keys 'target', 'low', 'high' or None.

        Returns:
            Complete TradePlan dataclass.

        Raises:
            ValueError: If insufficient data (< 15 bars) or invalid risk (risk_per_share <= 0).
        """
        cfg = self.cfg
        if horizon is None:
            horizon = cfg.TRADE_HORIZON_DAYS

        # -- Step 1: Validate inputs --
        min_bars = 15
        num_bars = min(len(highs), len(lows), len(closes))
        if num_bars < min_bars:
            raise ValueError(
                f"Insufficient OHLC data for trade plan: need at least {min_bars} bars, "
                f"got {num_bars}"
            )

        # -- Step 2: Compute ATR(14) --
        atr_val = self.compute_atr(highs, lows, closes, n=14)

        # -- Step 3: Compute stop --
        stop = entry - cfg.TRADE_ATR_MULT * atr_val

        # -- Step 4: Cap stop at MAX_LOSS_PCT floor --
        max_loss_floor = entry * (1.0 - cfg.TRADE_MAX_LOSS_PCT)
        if stop < max_loss_floor:
            stop = max_loss_floor

        # -- Step 5: Compute risk_per_share --
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            raise ValueError(
                f"Invalid risk: risk_per_share={risk_per_share:.4f} "
                f"(entry={entry}, stop={stop}). Must be > 0."
            )

        # Round risk_per_share to 2 decimal places
        risk_per_share = round(risk_per_share, 2)

        # -- Step 6-7: Compute targets --
        target1 = entry + cfg.TRADE_TARGET1_MULT * risk_per_share
        target2 = entry + cfg.TRADE_TARGET2_MULT * risk_per_share

        # -- Step 8: Compute reward_risk --
        reward_risk = round((target1 - entry) / risk_per_share, 2)
        data_unavailable = False
        low_rr = reward_risk < cfg.TRADE_MIN_REWARD_RISK

        # -- Step 9: Compute expected move --
        daily_sigma: float | None = None
        vol_source = "historical"

        # Prefer options IV if valid
        if options_iv is not None and 0 < options_iv <= 5.0:
            daily_sigma = options_iv / np.sqrt(252)
            vol_source = "options_iv"
        else:
            # Fallback to historical volatility
            daily_sigma = self.compute_historical_sigma(
                closes, lookback=cfg.TRADE_SIGMA_LOOKBACK
            )

        if daily_sigma is not None:
            expected_move_pct = round(float(daily_sigma * np.sqrt(horizon) * 100), 2)
        else:
            expected_move_pct = None

        # -- Step 10-11: Compute resistance and annotate --
        resistance, resistance_data_limited = self.compute_resistance(highs)
        target_above_resistance = target1 > resistance
        # CRITICAL: Never modify target1 or target2 based on resistance

        # -- Step 12: Earnings widening (if applicable) --
        earnings_in_window = earnings_date  # None means no earnings in window

        if earnings_in_window is not None and expected_move_pct is not None:
            expected_move_pct = round(
                expected_move_pct * cfg.TRADE_EARNINGS_WIDEN_FACTOR, 2
            )
            # Recompute target2 using widened expected move
            target2 = entry * (1.0 + expected_move_pct / 100.0)

        # -- Step 13: Probability from calibration --
        prob_hit_target1: float | None = None
        calibration_available = False

        if self.calibration is not None:
            atr_pct = (atr_val / entry) * 100.0
            prob, cal_avail = self.calibration.lookup(score, atr_pct)
            if prob is not None:
                prob_hit_target1 = prob
                calibration_available = True
            else:
                prob_hit_target1 = 0.50
                calibration_available = False
        else:
            prob_hit_target1 = 0.50
            calibration_available = False

        # Apply earnings confidence discount
        if earnings_in_window is not None and prob_hit_target1 is not None:
            prob_hit_target1 = round(
                max(prob_hit_target1 * cfg.TRADE_EARNINGS_CONFIDENCE_DISCOUNT, 0.05), 2
            )

        # -- Step 14: Compute percentages --
        stop_pct = round((stop - entry) / entry * 100, 2)
        target1_pct = round((target1 - entry) / entry * 100, 2)
        target2_pct = round((target2 - entry) / entry * 100, 2)

        # -- Step 15: Analyst fields --
        analyst_target = None
        analyst_low = None
        analyst_high = None
        if analyst is not None:
            analyst_target = analyst.get("target")
            analyst_low = analyst.get("low")
            analyst_high = analyst.get("high")

        # -- Step 16: Assemble and return TradePlan --
        return TradePlan(
            entry=entry,
            stop=round(stop, 2),
            stop_pct=stop_pct,
            target1=round(target1, 2),
            target1_pct=target1_pct,
            target2=round(target2, 2),
            target2_pct=target2_pct,
            risk_per_share=risk_per_share,
            reward_risk=reward_risk,
            low_rr=low_rr,
            data_unavailable=data_unavailable,
            expected_move_pct=expected_move_pct,
            vol_source=vol_source,
            resistance=round(resistance, 2),
            target_above_resistance=target_above_resistance,
            resistance_data_limited=resistance_data_limited,
            earnings_in_window=earnings_in_window,
            prob_hit_target1=prob_hit_target1,
            calibration_available=calibration_available,
            analyst_target=analyst_target,
            analyst_low=analyst_low,
            analyst_high=analyst_high,
        )
