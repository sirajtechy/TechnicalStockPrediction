"""
Trade Backtest — Walk-Forward Calibration Runner

Validates trade plan quality via walk-forward first-touch backtesting.
Produces calibration table only when all metrics pass.

Run from backend/:  python scripts/trade_backtest.py
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, variance

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from core.api_client import RestApiClient  # noqa: E402
from core.trade_calibration import CalibrationTable  # noqa: E402
from core.trade_engine import TradeEngine, TradePlan  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────────────

HORIZON_BARS = 30  # Walk forward 30 trading days
MIN_HISTORY_DAYS = 200  # Minimum trading days of history
CALENDAR_FETCH_DAYS = 400  # Calendar days to fetch for history
FORWARD_CALENDAR_DAYS = 55  # ~30 trading days buffer

# Parameter sweep grid
ATR_MULT_RANGE = [1.5, 2.0, 2.5, 3.0]
TARGET1_MULT_RANGE = [1.5, 2.0, 2.5, 3.0]

# Validation thresholds
MIN_RESOLVED_TRADES = 30
CALIBRATION_TOLERANCE = 0.05  # ±5 percentage points
EARNINGS_VARIANCE_RATIO = 1.2

# Temporal split
IN_SAMPLE_RATIO = 0.70

# Backtest scan dates — spread across market conditions
BACKTEST_DATES = [
    "2023-03-01", "2023-05-01", "2023-07-03", "2023-09-01",
    "2023-11-01", "2024-01-02", "2024-03-01", "2024-05-01",
    "2024-07-01", "2024-09-03", "2024-11-01", "2025-01-02",
]

# Representative tickers (diversified, liquid halal names)
BACKTEST_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AVGO", "LLY", "UNH", "COST",
    "HD", "CRM", "AMD", "QCOM", "TXN", "CAT", "DE", "XOM", "CVX",
    "V", "MA", "TSM", "AMZN", "META", "NFLX", "ADBE", "ORCL",
    "NOW", "ISRG", "INTU", "SNPS", "CDNS",
]

# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class TradeResult:
    """Result of a single trade evaluation."""

    ticker: str
    date: str
    score: int
    entry: float
    stop: float
    target1: float
    atr_pct: float
    reward_risk: float
    outcome: str  # 'target_hit', 'stop_hit', 'undecided'
    r_result: float  # +reward_risk, -1.0, or 0.0
    earnings_in_window: bool = False
    forward_returns: list[float] = field(default_factory=list)


@dataclass
class BucketStats:
    """Aggregated statistics for a calibration bucket."""

    bucket_id: str
    score_band: str
    atr_band: str
    total: int = 0
    target_hits: int = 0
    stop_hits: int = 0
    undecided: int = 0
    r_results: list[float] = field(default_factory=list)

    @property
    def resolved(self) -> int:
        return self.target_hits + self.stop_hits

    @property
    def hit_rate(self) -> float:
        return self.target_hits / self.resolved if self.resolved > 0 else 0.0

    @property
    def expectancy(self) -> float:
        return mean(self.r_results) if self.r_results else 0.0


# ─── Core Functions ───────────────────────────────────────────────────────────


def evaluate_trade(plan: TradePlan, forward_bars: list[dict]) -> tuple[str, float]:
    """Walk forward bar-by-bar, check if stop or target1 hit first.

    Args:
        plan: The trade plan with entry, stop, target1
        forward_bars: List of bar dicts with 'high', 'low', 'close'

    Returns:
        (outcome, r_result) where:
        - outcome: 'target_hit', 'stop_hit', 'undecided'
        - r_result: +reward_risk, -1.0, 0.0
    """
    for bar in forward_bars[:HORIZON_BARS]:
        # Path-dependent: check stop first within same bar
        if bar["low"] <= plan.stop:
            return ("stop_hit", -1.0)
        if bar["high"] >= plan.target1:
            return ("target_hit", plan.reward_risk)
    return ("undecided", 0.0)


def is_buy_candidate(bars: list[dict]) -> tuple[bool, int]:
    """Quick check if a ticker is in an uptrend (proxy for BUY candidate).

    Uses SMA50 as a simple trend filter (matches the real scanner's hard filter H1).
    Also computes a rough bullish score based on trend position.

    Returns:
        (is_candidate, approximate_score)
    """
    if len(bars) < 50:
        return False, 0

    closes = [b["close"] for b in bars]
    sma50 = mean(closes[-50:])
    current = closes[-1]

    if current <= sma50:
        return False, 0

    # Simple score proxy based on trend strength
    pct_above_sma50 = (current - sma50) / sma50 * 100
    sma200 = mean(closes[-200:]) if len(closes) >= 200 else mean(closes)
    above_sma200 = current > sma200

    # Rough score: 40 base + trend bonuses
    score = 40
    if above_sma200:
        score += 15
    if pct_above_sma50 > 2:
        score += 10
    if pct_above_sma50 > 5:
        score += 10
    if len(closes) >= 200:
        sma50_val = mean(closes[-50:])
        sma150 = mean(closes[-150:])
        if sma50_val > sma150 > sma200:
            score += 15  # Golden cross structure

    return True, min(score, 100)


def has_earnings_in_window(date_str: str) -> bool:
    """Simulate earnings detection — approximate using quarterly patterns.

    Real implementation would use Massive API. For backtest purposes,
    we flag ~25% of trades as having earnings in window (quarterly cycle).
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    # Earnings months: Jan, Apr, Jul, Oct (reporting season)
    return dt.month in (1, 4, 7, 10)


def build_plan_for_backtest(
    bars: list[dict],
    score: int,
    atr_mult: float = 2.0,
    target1_mult: float = 2.0,
) -> TradePlan | None:
    """Build a trade plan from historical bars using specified parameters.

    Args:
        bars: Historical OHLCV bars (must have >= 15)
        score: Approximate bullish score
        atr_mult: ATR multiplier for stop
        target1_mult: R-multiple for target1

    Returns:
        TradePlan or None if insufficient data
    """
    if len(bars) < 15:
        return None

    highs = np.array([b["high"] for b in bars], dtype=np.float64)
    lows = np.array([b["low"] for b in bars], dtype=np.float64)
    closes = np.array([b["close"] for b in bars], dtype=np.float64)
    entry = float(closes[-1])

    # Create a temporary config with sweep parameters
    cfg = Config()
    cfg.TRADE_ATR_MULT = atr_mult
    cfg.TRADE_TARGET1_MULT = target1_mult
    cfg.TRADE_TARGET2_MULT = target1_mult + 1.0  # Always T2 = T1 + 1R
    cfg.TRADE_MAX_LOSS_PCT = 0.10

    engine = TradeEngine(cfg=cfg, calibration=None)

    try:
        plan = engine.build_plan(
            entry=entry,
            highs=highs,
            lows=lows,
            closes=closes,
            score=score,
        )
        return plan
    except ValueError:
        return None


def classify_bucket(score: int, atr_pct: float) -> tuple[str, str, str]:
    """Classify a trade into score band and ATR band.

    Returns:
        (bucket_id, score_band, atr_band)
    """
    score_band = CalibrationTable.score_band(score)
    atr_band = CalibrationTable.atr_band(atr_pct)
    bucket_id = f"{score_band}_{atr_band}"
    return bucket_id, score_band, atr_band


def compute_breakeven_rate(reward_risk: float) -> float:
    """Compute breakeven hit rate for a given R-multiple.

    breakeven = 1 / (1 + R)
    For 2:1 plan: 1/(1+2) = 33.3%
    """
    return 1.0 / (1.0 + reward_risk)


# ─── Main Backtest Logic ──────────────────────────────────────────────────────


async def collect_trade_results(
    client: RestApiClient,
    atr_mult: float = 2.0,
    target1_mult: float = 2.0,
) -> list[TradeResult]:
    """Collect all trade results across dates and tickers.

    For each date, fetches historical data, identifies BUY candidates,
    builds trade plans, and evaluates outcomes with forward bars.
    """
    results: list[TradeResult] = []
    total_attempts = len(BACKTEST_DATES) * len(BACKTEST_TICKERS)
    processed = 0

    for date_str in BACKTEST_DATES:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        hist_from = (dt - timedelta(days=CALENDAR_FETCH_DAYS)).strftime("%Y-%m-%d")
        fwd_from = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        fwd_to = (dt + timedelta(days=FORWARD_CALENDAR_DAYS)).strftime("%Y-%m-%d")

        for ticker in BACKTEST_TICKERS:
            processed += 1
            try:
                # Fetch historical bars up to scan date
                hist_bars = await client.fetch_stock_data_range(
                    ticker, hist_from, date_str
                )
                if len(hist_bars) < MIN_HISTORY_DAYS:
                    continue

                # Check if this is a BUY candidate
                is_candidate, score = is_buy_candidate(hist_bars)
                if not is_candidate:
                    continue

                # Build trade plan
                plan = build_plan_for_backtest(
                    hist_bars, score, atr_mult, target1_mult
                )
                if plan is None:
                    continue

                # Fetch forward bars
                fwd_bars = await client.fetch_stock_data_range(
                    ticker, fwd_from, fwd_to
                )
                if len(fwd_bars) < 5:
                    continue

                # Evaluate first-touch outcome
                outcome, r_result = evaluate_trade(plan, fwd_bars)

                # Compute ATR as % of price for bucketing
                atr_pct = (plan.risk_per_share / plan.entry) * 100 / (
                    atr_mult if atr_mult else 2.0
                )
                # More accurate: use actual ATR
                atr_val = plan.entry - plan.stop
                atr_pct = (atr_val / atr_mult / plan.entry) * 100

                # Check earnings window
                earnings = has_earnings_in_window(date_str)

                # Compute forward returns for variance analysis
                fwd_returns = []
                if fwd_bars:
                    entry_price = plan.entry
                    for bar in fwd_bars[:HORIZON_BARS]:
                        ret = (bar["close"] - entry_price) / entry_price
                        fwd_returns.append(ret)

                results.append(TradeResult(
                    ticker=ticker,
                    date=date_str,
                    score=score,
                    entry=plan.entry,
                    stop=plan.stop,
                    target1=plan.target1,
                    atr_pct=atr_pct,
                    reward_risk=plan.reward_risk or target1_mult,
                    outcome=outcome,
                    r_result=r_result,
                    earnings_in_window=earnings,
                    forward_returns=fwd_returns,
                ))

            except Exception as e:
                # Skip individual ticker failures
                if processed % 50 == 0:
                    print(f"  [skip] {ticker} on {date_str}: {e}")
                continue

        print(f"  Date {date_str}: {processed}/{total_attempts} processed, "
              f"{len(results)} valid trades so far")

    return results


def temporal_split(results: list[TradeResult]) -> tuple[list[TradeResult], list[TradeResult]]:
    """Split results into in-sample (70%) and out-of-sample (30%) by date.

    Returns:
        (in_sample, out_of_sample) lists sorted by date
    """
    sorted_results = sorted(results, key=lambda r: r.date)
    split_idx = int(len(sorted_results) * IN_SAMPLE_RATIO)
    return sorted_results[:split_idx], sorted_results[split_idx:]


def compute_metrics(results: list[TradeResult]) -> dict:
    """Compute hit rate and expectancy for a set of trade results.

    Returns dict with:
        - total, resolved, target_hits, stop_hits, undecided
        - hit_rate (excluding undecided)
        - expectancy_r (mean R across all trades including undecided)
        - resolved_expectancy_r (mean R excluding undecided)
    """
    if not results:
        return {
            "total": 0, "resolved": 0, "target_hits": 0,
            "stop_hits": 0, "undecided": 0,
            "hit_rate": 0.0, "expectancy_r": 0.0,
            "resolved_expectancy_r": 0.0,
        }

    target_hits = sum(1 for r in results if r.outcome == "target_hit")
    stop_hits = sum(1 for r in results if r.outcome == "stop_hit")
    undecided = sum(1 for r in results if r.outcome == "undecided")
    resolved = target_hits + stop_hits
    hit_rate = target_hits / resolved if resolved > 0 else 0.0

    all_r = [r.r_result for r in results]
    resolved_r = [r.r_result for r in results if r.outcome != "undecided"]

    return {
        "total": len(results),
        "resolved": resolved,
        "target_hits": target_hits,
        "stop_hits": stop_hits,
        "undecided": undecided,
        "hit_rate": hit_rate,
        "expectancy_r": mean(all_r) if all_r else 0.0,
        "resolved_expectancy_r": mean(resolved_r) if resolved_r else 0.0,
    }


def bucket_results(results: list[TradeResult]) -> dict[str, BucketStats]:
    """Group trade results into calibration buckets.

    Buckets: score_band × atr_band (9 possible combinations).
    """
    buckets: dict[str, BucketStats] = {}

    for r in results:
        bucket_id, score_band, atr_band = classify_bucket(r.score, r.atr_pct)

        if bucket_id not in buckets:
            buckets[bucket_id] = BucketStats(
                bucket_id=bucket_id,
                score_band=score_band,
                atr_band=atr_band,
            )

        b = buckets[bucket_id]
        b.total += 1
        b.r_results.append(r.r_result)

        if r.outcome == "target_hit":
            b.target_hits += 1
        elif r.outcome == "stop_hit":
            b.stop_hits += 1
        else:
            b.undecided += 1

    return buckets


def run_parameter_sweep(
    results: list[TradeResult],
    client: RestApiClient,
) -> dict:
    """Run parameter sweep on in-sample data.

    Tests atr_mult 1.5-3.0 x target1_mult 1.5-3.0 (16 combos, step 0.5).
    Since we already have forward bars in results, we re-evaluate with
    different stop/target levels.

    Returns:
        Dict with sweep results, best combo, and OOS validation.
    """
    in_sample, out_of_sample = temporal_split(results)

    sweep_results = []

    for atr_mult in ATR_MULT_RANGE:
        for t1_mult in TARGET1_MULT_RANGE:
            # Re-evaluate in-sample trades with new parameters
            # We simulate by adjusting stop/target relative to entry
            is_results = []
            for r in in_sample:
                # Recompute stop and target with new multipliers
                # ATR was: (entry - stop) / original_atr_mult
                original_atr = (r.entry - r.stop) / 2.0  # default atr_mult=2.0
                new_stop = r.entry - atr_mult * original_atr
                new_stop = max(new_stop, r.entry * 0.90)  # 10% floor
                new_risk = r.entry - new_stop
                if new_risk <= 0:
                    continue
                new_target1 = r.entry + t1_mult * new_risk
                new_rr = t1_mult

                # Re-evaluate with new levels using forward returns
                # Reconstruct approximate forward bars from returns
                outcome = "undecided"
                r_result = 0.0
                if r.forward_returns:
                    for ret in r.forward_returns:
                        price = r.entry * (1 + ret)
                        # Approximate: use close as proxy for high/low
                        if price <= new_stop:
                            outcome = "stop_hit"
                            r_result = -1.0
                            break
                        if price >= new_target1:
                            outcome = "target_hit"
                            r_result = new_rr
                            break

                is_results.append({"outcome": outcome, "r_result": r_result})

            # Compute expectancy for this combo
            if len(is_results) < MIN_RESOLVED_TRADES:
                continue

            r_values = [x["r_result"] for x in is_results]
            expectancy = mean(r_values) if r_values else 0.0
            resolved = [x for x in is_results if x["outcome"] != "undecided"]
            hit_rate = (
                sum(1 for x in resolved if x["outcome"] == "target_hit")
                / len(resolved)
                if resolved else 0.0
            )

            sweep_results.append({
                "atr_mult": atr_mult,
                "target1_mult": t1_mult,
                "trades": len(is_results),
                "expectancy_r": round(expectancy, 4),
                "hit_rate": round(hit_rate, 4),
            })

    # Find best in-sample combo with positive expectancy
    positive_combos = [s for s in sweep_results if s["expectancy_r"] > 0]
    if not positive_combos:
        return {
            "status": "no_viable_point",
            "sweep_results": sweep_results,
            "best": None,
            "oos_expectancy": None,
        }

    best = max(positive_combos, key=lambda x: x["expectancy_r"])

    # Validate on OOS with best parameters
    oos_results = []
    best_atr = best["atr_mult"]
    best_t1 = best["target1_mult"]

    for r in out_of_sample:
        original_atr = (r.entry - r.stop) / 2.0
        new_stop = r.entry - best_atr * original_atr
        new_stop = max(new_stop, r.entry * 0.90)
        new_risk = r.entry - new_stop
        if new_risk <= 0:
            continue
        new_target1 = r.entry + best_t1 * new_risk

        outcome = "undecided"
        r_result = 0.0
        if r.forward_returns:
            for ret in r.forward_returns:
                price = r.entry * (1 + ret)
                if price <= new_stop:
                    outcome = "stop_hit"
                    r_result = -1.0
                    break
                if price >= new_target1:
                    outcome = "target_hit"
                    r_result = best_t1
                    break

        oos_results.append({"outcome": outcome, "r_result": r_result})

    oos_r = [x["r_result"] for x in oos_results]
    oos_expectancy = mean(oos_r) if oos_r else 0.0

    # Flag overfitting if OOS < 50% of IS
    overfitting = oos_expectancy < (best["expectancy_r"] * 0.5)

    return {
        "status": "ok" if oos_expectancy > 0 else "no_positive_oos",
        "sweep_results": sweep_results,
        "best": best,
        "oos_expectancy": round(oos_expectancy, 4),
        "oos_trades": len(oos_results),
        "overfitting_flag": overfitting,
    }


def validate_earnings_subset(results: list[TradeResult]) -> dict:
    """Validate earnings-window subset shows elevated variance.

    Requirement 15: Confirm variance ratio >= 1.2 for earnings-in-window
    vs no-earnings trades.
    """
    earnings_trades = [r for r in results if r.earnings_in_window]
    no_earnings_trades = [r for r in results if not r.earnings_in_window]

    if len(earnings_trades) < MIN_RESOLVED_TRADES:
        return {
            "status": "insufficient_data",
            "message": f"Earnings subset has {len(earnings_trades)} trades "
                       f"(need {MIN_RESOLVED_TRADES})",
            "earnings_count": len(earnings_trades),
            "no_earnings_count": len(no_earnings_trades),
        }

    if len(no_earnings_trades) < MIN_RESOLVED_TRADES:
        return {
            "status": "insufficient_data",
            "message": f"No-earnings subset has {len(no_earnings_trades)} trades "
                       f"(need {MIN_RESOLVED_TRADES})",
            "earnings_count": len(earnings_trades),
            "no_earnings_count": len(no_earnings_trades),
        }

    # Compute 30-day return variance for each subset
    def final_return(r: TradeResult) -> float:
        if r.forward_returns:
            return r.forward_returns[-1] if r.forward_returns else 0.0
        return 0.0

    earnings_returns = [final_return(r) for r in earnings_trades]
    no_earnings_returns = [final_return(r) for r in no_earnings_trades]

    earnings_var = variance(earnings_returns) if len(earnings_returns) > 1 else 0.0
    no_earnings_var = variance(no_earnings_returns) if len(no_earnings_returns) > 1 else 0.0

    if no_earnings_var == 0:
        ratio = float("inf") if earnings_var > 0 else 1.0
    else:
        ratio = earnings_var / no_earnings_var

    # Compute hit rates per subset
    e_metrics = compute_metrics(earnings_trades)
    ne_metrics = compute_metrics(no_earnings_trades)

    passed = ratio >= EARNINGS_VARIANCE_RATIO

    return {
        "status": "pass" if passed else "fail",
        "earnings_count": len(earnings_trades),
        "no_earnings_count": len(no_earnings_trades),
        "earnings_variance": round(earnings_var, 6),
        "no_earnings_variance": round(no_earnings_var, 6),
        "variance_ratio": round(ratio, 4),
        "required_ratio": EARNINGS_VARIANCE_RATIO,
        "earnings_hit_rate": round(e_metrics["hit_rate"], 4),
        "no_earnings_hit_rate": round(ne_metrics["hit_rate"], 4),
        "earnings_expectancy": round(e_metrics["expectancy_r"], 4),
        "no_earnings_expectancy": round(ne_metrics["expectancy_r"], 4),
        "passed": passed,
    }


def validate_calibration(
    results: list[TradeResult],
) -> tuple[bool, list[str], dict[str, BucketStats]]:
    """Validate all calibration requirements.

    Returns:
        (all_passed, failures, buckets) where:
        - all_passed: True if all validations pass
        - failures: List of failure messages
        - buckets: Dict of bucket stats
    """
    failures: list[str] = []

    # Overall metrics
    metrics = compute_metrics(results)
    print(f"\n  Overall: {metrics['total']} trades, "
          f"{metrics['resolved']} resolved, "
          f"hit_rate={metrics['hit_rate']:.1%}, "
          f"expectancy={metrics['expectancy_r']:+.3f}R")

    # Temporal split validation (R13.4)
    in_sample, out_of_sample = temporal_split(results)
    is_metrics = compute_metrics(in_sample)
    oos_metrics = compute_metrics(out_of_sample)

    print(f"  In-sample:  {is_metrics['total']} trades, "
          f"expectancy={is_metrics['expectancy_r']:+.3f}R, "
          f"hit_rate={is_metrics['hit_rate']:.1%}")
    print(f"  Out-of-sample: {oos_metrics['total']} trades, "
          f"expectancy={oos_metrics['expectancy_r']:+.3f}R, "
          f"hit_rate={oos_metrics['hit_rate']:.1%}")

    # Check minimum resolved trades
    if is_metrics["resolved"] < MIN_RESOLVED_TRADES:
        failures.append(
            f"In-sample has {is_metrics['resolved']} resolved trades "
            f"(need {MIN_RESOLVED_TRADES})"
        )

    if oos_metrics["resolved"] < MIN_RESOLVED_TRADES:
        failures.append(
            f"Out-of-sample has {oos_metrics['resolved']} resolved trades "
            f"(need {MIN_RESOLVED_TRADES})"
        )

    # Check positive expectancy on both periods (R13.4)
    if is_metrics["expectancy_r"] <= 0:
        failures.append(
            f"In-sample expectancy is {is_metrics['expectancy_r']:+.4f}R "
            f"(must be > 0R)"
        )

    if oos_metrics["expectancy_r"] <= 0:
        failures.append(
            f"Out-of-sample expectancy is {oos_metrics['expectancy_r']:+.4f}R "
            f"(must be > 0R)"
        )

    # Check hit rate exceeds breakeven (R13.3)
    # For default 2:1 plan, breakeven = 33.3%
    avg_rr = mean([r.reward_risk for r in results]) if results else 2.0
    breakeven = compute_breakeven_rate(avg_rr)

    if metrics["hit_rate"] <= breakeven:
        failures.append(
            f"Overall hit rate {metrics['hit_rate']:.1%} does not exceed "
            f"breakeven {breakeven:.1%} (for {avg_rr:.1f}:1 plan)"
        )

    # Bucket calibration (R13.5)
    buckets = bucket_results(results)
    print(f"\n  Buckets ({len(buckets)} populated):")
    for bid, b in sorted(buckets.items()):
        if b.resolved >= 10:  # Only report buckets with meaningful sample
            print(f"    {bid}: n={b.total}, resolved={b.resolved}, "
                  f"hit_rate={b.hit_rate:.1%}, expectancy={b.expectancy:+.3f}R")

    return len(failures) == 0, failures, buckets


def build_calibration_json(
    buckets: dict[str, BucketStats],
    sweep_result: dict,
    results: list[TradeResult],
) -> dict:
    """Build the calibration JSON structure.

    Only includes buckets with sufficient sample size (>= 30 resolved).
    """
    bucket_data = {}
    for bid, b in buckets.items():
        if b.resolved < MIN_RESOLVED_TRADES:
            continue

        bucket_data[bid] = {
            "score_band": b.score_band,
            "atr_band": b.atr_band,
            "sample_size": b.total,
            "realized_hit_rate": round(b.hit_rate, 4),
            "mean_expectancy_r": round(b.expectancy, 4),
            "prob_hit_target1": round(b.hit_rate, 4),
        }

    # Determine best operating point
    best_params = sweep_result.get("best", {}) if sweep_result else {}

    return {
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sample_period": {
            "start": BACKTEST_DATES[0],
            "end": BACKTEST_DATES[-1],
        },
        "total_trades": len(results),
        "operating_point": {
            "atr_mult": best_params.get("atr_mult", 2.0),
            "target1_mult": best_params.get("target1_mult", 2.0),
            "is_expectancy_r": best_params.get("expectancy_r", 0.0),
            "oos_expectancy_r": sweep_result.get("oos_expectancy", 0.0)
            if sweep_result else 0.0,
        },
        "buckets": bucket_data,
    }


def write_results_doc(
    results: list[TradeResult],
    buckets: dict[str, BucketStats],
    sweep_result: dict,
    earnings_result: dict,
    all_passed: bool,
    failures: list[str],
) -> None:
    """Write results documentation to docs/TRADE_ENGINE_RESULTS.md."""
    docs_dir = Path(__file__).parent.parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    doc_path = docs_dir / "TRADE_ENGINE_RESULTS.md"

    metrics = compute_metrics(results)
    in_sample, out_of_sample = temporal_split(results)
    is_metrics = compute_metrics(in_sample)
    oos_metrics = compute_metrics(out_of_sample)

    lines = [
        "# Trade Engine Backtest Results",
        "",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Summary",
        "",
        f"- **Status**: {'PASS - All validations passed' if all_passed else 'FAIL - See failures below'}",
        f"- **Total trades**: {metrics['total']}",
        f"- **Resolved**: {metrics['resolved']} "
        f"(target: {metrics['target_hits']}, stop: {metrics['stop_hits']})",
        f"- **Undecided**: {metrics['undecided']}",
        f"- **Hit rate**: {metrics['hit_rate']:.1%}",
        f"- **Expectancy**: {metrics['expectancy_r']:+.3f}R",
        f"- **Sample period**: {BACKTEST_DATES[0]} to {BACKTEST_DATES[-1]}",
        f"- **Tickers**: {len(BACKTEST_TICKERS)}",
        f"- **Scan dates**: {len(BACKTEST_DATES)}",
        "",
        "## Temporal Split (70/30)",
        "",
        f"| Period | Trades | Resolved | Hit Rate | Expectancy |",
        f"|--------|--------|----------|----------|------------|",
        f"| In-sample | {is_metrics['total']} | {is_metrics['resolved']} | "
        f"{is_metrics['hit_rate']:.1%} | {is_metrics['expectancy_r']:+.3f}R |",
        f"| Out-of-sample | {oos_metrics['total']} | {oos_metrics['resolved']} | "
        f"{oos_metrics['hit_rate']:.1%} | {oos_metrics['expectancy_r']:+.3f}R |",
        "",
    ]

    # Parameter sweep section
    lines.append("## Parameter Sweep")
    lines.append("")
    if sweep_result and sweep_result.get("sweep_results"):
        lines.append("| ATR Mult | T1 Mult | Trades | Expectancy | Hit Rate |")
        lines.append("|----------|---------|--------|------------|----------|")
        for s in sorted(sweep_result["sweep_results"],
                       key=lambda x: x["expectancy_r"], reverse=True):
            lines.append(
                f"| {s['atr_mult']:.1f} | {s['target1_mult']:.1f} | "
                f"{s['trades']} | {s['expectancy_r']:+.4f}R | "
                f"{s['hit_rate']:.1%} |"
            )
        lines.append("")
        if sweep_result.get("best"):
            best = sweep_result["best"]
            lines.append(f"**Best operating point**: ATR={best['atr_mult']:.1f}, "
                        f"T1={best['target1_mult']:.1f} "
                        f"(IS expectancy: {best['expectancy_r']:+.4f}R)")
            lines.append(f"**OOS expectancy**: "
                        f"{sweep_result.get('oos_expectancy', 0):+.4f}R")
            if sweep_result.get("overfitting_flag"):
                lines.append("**WARNING**: Possible overfitting "
                           "(OOS < 50% of IS expectancy)")
        lines.append("")
    else:
        lines.append("No viable parameter combination found.")
        lines.append("")

    # Earnings validation section
    lines.append("## Earnings-Window Validation")
    lines.append("")
    if earnings_result:
        lines.append(f"- Earnings subset: {earnings_result.get('earnings_count', 0)} trades")
        lines.append(f"- No-earnings subset: "
                    f"{earnings_result.get('no_earnings_count', 0)} trades")
        lines.append(f"- Earnings variance: "
                    f"{earnings_result.get('earnings_variance', 0):.6f}")
        lines.append(f"- No-earnings variance: "
                    f"{earnings_result.get('no_earnings_variance', 0):.6f}")
        lines.append(f"- Variance ratio: "
                    f"{earnings_result.get('variance_ratio', 0):.4f} "
                    f"(required: >= {EARNINGS_VARIANCE_RATIO})")
        lines.append(f"- Status: **{earnings_result.get('status', 'unknown').upper()}**")
    lines.append("")

    # Calibration buckets section
    lines.append("## Calibration Buckets")
    lines.append("")
    lines.append("| Bucket | Sample | Resolved | Hit Rate | Expectancy |")
    lines.append("|--------|--------|----------|----------|------------|")
    for bid, b in sorted(buckets.items()):
        lines.append(
            f"| {bid} | {b.total} | {b.resolved} | "
            f"{b.hit_rate:.1%} | {b.expectancy:+.3f}R |"
        )
    lines.append("")

    # Failures section
    if failures:
        lines.append("## Failures")
        lines.append("")
        for f in failures:
            lines.append(f"- **FAIL**: {f}")
        lines.append("")

    doc_path.write_text("\n".join(lines))
    print(f"\n  Results written to {doc_path}")


# ─── Main Entry Point ─────────────────────────────────────────────────────────


async def main() -> None:
    """Run the full trade backtest pipeline."""
    print("=" * 70)
    print("  TRADE ENGINE CALIBRATION BACKTEST")
    print("=" * 70)
    print(f"\n  Config: {len(BACKTEST_DATES)} dates × "
          f"{len(BACKTEST_TICKERS)} tickers")
    print(f"  Horizon: {HORIZON_BARS} bars, "
          f"Min history: {MIN_HISTORY_DAYS} days")
    print(f"  Temporal split: {IN_SAMPLE_RATIO:.0%} IS / "
          f"{1-IN_SAMPLE_RATIO:.0%} OOS")
    print()

    # Initialize API client
    from config import config as app_config
    client = RestApiClient(
        api_key=app_config.POLYGON_TOKEN,
        base_url=app_config.API_BASE_URL,
        max_concurrent=5,
        max_retries=3,
    )

    try:
        # ── Step 1: Collect trade results ──────────────────────────────────
        print("─" * 70)
        print("  STEP 1: Collecting trade results (default params: "
              "ATR=2.0, T1=2.0)")
        print("─" * 70)

        results = await collect_trade_results(client)

        if len(results) < MIN_RESOLVED_TRADES:
            print(f"\n  ERROR: Only {len(results)} trades collected "
                  f"(need {MIN_RESOLVED_TRADES})")
            print("  Cannot proceed with calibration.")
            return

        print(f"\n  Collected {len(results)} valid trade results")

        # ── Step 2: Validate calibration ───────────────────────────────────
        print("\n" + "─" * 70)
        print("  STEP 2: Validating calibration metrics")
        print("─" * 70)

        all_passed, failures, buckets = validate_calibration(results)

        # ── Step 3: Parameter sweep ────────────────────────────────────────
        print("\n" + "─" * 70)
        print("  STEP 3: Parameter sweep (16 combinations)")
        print("─" * 70)

        sweep_result = run_parameter_sweep(results, client)

        if sweep_result["status"] == "ok":
            best = sweep_result["best"]
            print(f"\n  Best combo: ATR={best['atr_mult']:.1f}, "
                  f"T1={best['target1_mult']:.1f}")
            print(f"  IS expectancy: {best['expectancy_r']:+.4f}R")
            print(f"  OOS expectancy: {sweep_result['oos_expectancy']:+.4f}R")
            if sweep_result.get("overfitting_flag"):
                print("  WARNING: Possible overfitting detected")
                failures.append("Parameter sweep: OOS expectancy < 50% of IS "
                              "(overfitting risk)")
        elif sweep_result["status"] == "no_viable_point":
            print("\n  No parameter combination shows positive OOS expectancy")
            failures.append("Parameter sweep: no viable operating point found")
        else:
            print(f"\n  Sweep status: {sweep_result['status']}")
            if sweep_result.get("oos_expectancy", 0) <= 0:
                failures.append(
                    f"Parameter sweep: OOS expectancy "
                    f"{sweep_result.get('oos_expectancy', 0):+.4f}R <= 0"
                )

        # ── Step 4: Earnings validation ────────────────────────────────────
        print("\n" + "─" * 70)
        print("  STEP 4: Earnings-window variance validation")
        print("─" * 70)

        earnings_result = validate_earnings_subset(results)

        print(f"\n  Earnings trades: {earnings_result.get('earnings_count', 0)}")
        print(f"  No-earnings trades: {earnings_result.get('no_earnings_count', 0)}")

        if earnings_result["status"] == "pass":
            print(f"  Variance ratio: {earnings_result['variance_ratio']:.4f} "
                  f"(>= {EARNINGS_VARIANCE_RATIO}) PASS")
        elif earnings_result["status"] == "fail":
            print(f"  Variance ratio: {earnings_result['variance_ratio']:.4f} "
                  f"(< {EARNINGS_VARIANCE_RATIO}) FAIL")
            failures.append(
                f"Earnings variance ratio {earnings_result['variance_ratio']:.4f} "
                f"< required {EARNINGS_VARIANCE_RATIO}"
            )
        else:
            print(f"  {earnings_result.get('message', 'Insufficient data')}")
            # Insufficient data is a warning, not a hard failure
            print("  (Skipped — insufficient data for earnings comparison)")

        # ── Step 5: Final verdict ──────────────────────────────────────────
        print("\n" + "=" * 70)

        # Re-check all_passed considering sweep and earnings
        all_passed = len(failures) == 0

        if all_passed:
            print("  RESULT: ALL VALIDATIONS PASSED")
            print("=" * 70)

            # Build and write calibration JSON
            cal_json = build_calibration_json(buckets, sweep_result, results)
            data_dir = Path(__file__).parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            cal_path = data_dir / "trade_calibration.json"
            cal_path.write_text(json.dumps(cal_json, indent=2))
            print(f"\n  Calibration table written to {cal_path}")
            print(f"  Buckets populated: {len(cal_json['buckets'])}")
        else:
            print("  RESULT: VALIDATION FAILED")
            print("=" * 70)
            print("\n  Failing metrics:")
            for f in failures:
                print(f"    - {f}")
            print("\n  Calibration table NOT produced.")

        # Write results documentation regardless of pass/fail
        write_results_doc(
            results, buckets, sweep_result, earnings_result,
            all_passed, failures
        )

        # Print final summary
        metrics = compute_metrics(results)
        print(f"\n  Final Summary:")
        print(f"    Trades: {metrics['total']}")
        print(f"    Hit rate: {metrics['hit_rate']:.1%}")
        print(f"    Expectancy: {metrics['expectancy_r']:+.3f}R")
        print(f"    Status: {'PASS' if all_passed else 'FAIL'}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
