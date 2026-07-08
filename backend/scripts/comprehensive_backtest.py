"""
Comprehensive Trade Plan Backtest

Tests the full halal universe (212 tickers) across 24 monthly dates (Jan 2023 - Dec 2024).
Sweeps 25 parameter combinations (ATR mult × Target1 mult).
Produces calibration table with real bucket probabilities.

Run from backend/:  python scripts/comprehensive_backtest.py
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from core.api_client import RestApiClient  # noqa: E402
from core.halal_universe import load_halal_universe  # noqa: E402
from core.trade_calibration import CalibrationTable  # noqa: E402
from core.trade_engine import TradeEngine  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────────────

HORIZON_BARS = 30
MIN_HISTORY_BARS = 200
CALENDAR_FETCH_DAYS = 400
FORWARD_CALENDAR_DAYS = 55

# Parameter sweep grid: 5 × 5 = 25 combinations
ATR_MULT_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0]
TARGET1_MULT_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0]

# Validation
MIN_RESOLVED_TRADES = 30
IN_SAMPLE_RATIO = 0.70

# Progress reporting
PROGRESS_INTERVAL = 50

# 24 monthly scan dates: Jan 2023 through Dec 2024
BACKTEST_DATES = [
    "2023-01-03", "2023-02-01", "2023-03-01", "2023-04-03",
    "2023-05-01", "2023-06-01", "2023-07-03", "2023-08-01",
    "2023-09-01", "2023-10-02", "2023-11-01", "2023-12-01",
    "2024-01-02", "2024-02-01", "2024-03-01", "2024-04-01",
    "2024-05-01", "2024-06-03", "2024-07-01", "2024-08-01",
    "2024-09-03", "2024-10-01", "2024-11-01", "2024-12-02",
]

# Output paths
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
CALIBRATION_OUTPUT = DATA_DIR / "trade_calibration.json"
REPORT_OUTPUT = DOCS_DIR / "TRADE_ENGINE_COMPREHENSIVE_RESULTS.md"


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
    r_result: float
    forward_bars: list[dict] = field(default_factory=list)


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


def evaluate_trade(entry: float, stop: float, target1: float,
                   target1_mult: float, forward_bars: list[dict]) -> tuple[str, float]:
    """Walk forward bar-by-bar, first-touch evaluation.

    Args:
        entry: Entry price
        stop: Stop loss price
        target1: Target 1 price
        target1_mult: R-multiple earned on target hit
        forward_bars: List of bar dicts with 'high', 'low'

    Returns:
        (outcome, r_result)
    """
    for bar in forward_bars[:HORIZON_BARS]:
        if bar["low"] <= stop:
            return ("stop_hit", -1.0)
        if bar["high"] >= target1:
            return ("target_hit", target1_mult)
    return ("undecided", 0.0)


def is_buy_candidate(bars: list[dict]) -> tuple[bool, int]:
    """Check if ticker qualifies as BUY candidate (simplified Minervini).

    Criteria: price > SMA(50) AND price > SMA(200)
    Score: base 40 + bonuses for distance above SMAs, golden cross, etc.

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

    # Need SMA200 for full candidate check
    sma200 = mean(closes[-200:]) if len(closes) >= 200 else mean(closes)
    if current <= sma200:
        return False, 0

    # Score computation
    pct_above_sma50 = (current - sma50) / sma50 * 100
    score = 40

    if pct_above_sma50 > 2:
        score += 10
    if pct_above_sma50 > 5:
        score += 10
    if pct_above_sma50 > 10:
        score += 5

    if len(closes) >= 200:
        sma150 = mean(closes[-150:])
        if sma50 > sma150 > sma200:
            score += 15  # Golden cross structure
        pct_above_200 = (current - sma200) / sma200 * 100
        if pct_above_200 > 10:
            score += 10

    return True, min(score, 100)


def build_plan_params(bars: list[dict], atr_mult: float,
                      target1_mult: float) -> dict | None:
    """Build trade plan parameters from historical bars.

    Returns dict with entry, stop, target1, atr_pct, reward_risk
    or None if insufficient data.
    """
    if len(bars) < 15:
        return None

    highs = np.array([b["high"] for b in bars], dtype=np.float64)
    lows = np.array([b["low"] for b in bars], dtype=np.float64)
    closes = np.array([b["close"] for b in bars], dtype=np.float64)
    entry = float(closes[-1])

    # Compute ATR(14)
    try:
        atr_val = TradeEngine.compute_atr(highs, lows, closes, n=14)
    except ValueError:
        return None

    # Compute stop
    stop = entry - atr_mult * atr_val
    max_loss_floor = entry * 0.90  # 10% max loss
    if stop < max_loss_floor:
        stop = max_loss_floor

    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return None

    target1 = entry + target1_mult * risk_per_share
    atr_pct = (atr_val / entry) * 100.0

    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target1": round(target1, 2),
        "atr_pct": round(atr_pct, 4),
        "reward_risk": round(target1_mult, 2),
        "risk_per_share": round(risk_per_share, 2),
    }


def classify_bucket(score: int, atr_pct: float) -> tuple[str, str, str]:
    """Classify into score_band × atr_band bucket."""
    score_band = CalibrationTable.score_band(score)
    atr_band = CalibrationTable.atr_band(atr_pct)
    return f"{score_band}_{atr_band}", score_band, atr_band


# ─── Data Collection ──────────────────────────────────────────────────────────


async def collect_raw_data(client: RestApiClient,
                           tickers: list[str]) -> list[dict]:
    """Fetch historical + forward data for all ticker×date combos.

    Returns list of raw records with bars and metadata for later
    parameter sweep (avoids re-fetching for each parameter combo).
    """
    raw_records: list[dict] = []
    total_combos = len(BACKTEST_DATES) * len(tickers)
    processed = 0
    skipped = 0
    start_time = time.time()

    print(f"\n{'═' * 60}")
    print(f"PHASE 1: DATA COLLECTION")
    print(f"{'═' * 60}")
    print(f"  Tickers: {len(tickers)}")
    print(f"  Dates: {len(BACKTEST_DATES)}")
    print(f"  Total combinations: {total_combos}")
    print(f"{'─' * 60}")

    for date_str in BACKTEST_DATES:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        hist_from = (dt - timedelta(days=CALENDAR_FETCH_DAYS)).strftime("%Y-%m-%d")
        fwd_from = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        fwd_to = (dt + timedelta(days=FORWARD_CALENDAR_DAYS)).strftime("%Y-%m-%d")

        date_candidates = 0

        for ticker in tickers:
            processed += 1

            if processed % PROGRESS_INTERVAL == 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                print(f"  [{processed}/{total_combos}] "
                      f"({rate:.1f} combos/s) "
                      f"Records: {len(raw_records)}, Skipped: {skipped}")

            try:
                # Fetch historical bars
                hist_bars = await client.fetch_stock_data_range(
                    ticker, hist_from, date_str
                )
                if len(hist_bars) < MIN_HISTORY_BARS:
                    skipped += 1
                    continue

                # Check if BUY candidate
                is_candidate, score = is_buy_candidate(hist_bars)
                if not is_candidate:
                    skipped += 1
                    continue

                # Fetch forward bars for evaluation
                fwd_bars = await client.fetch_stock_data_range(
                    ticker, fwd_from, fwd_to
                )
                if len(fwd_bars) < 5:
                    skipped += 1
                    continue

                date_candidates += 1
                raw_records.append({
                    "ticker": ticker,
                    "date": date_str,
                    "score": score,
                    "hist_bars": hist_bars,
                    "fwd_bars": fwd_bars,
                })

            except Exception as e:
                skipped += 1
                if processed % 200 == 0:
                    print(f"    [skip] {ticker}@{date_str}: {type(e).__name__}")
                continue

            # Small delay to be respectful of API
            await asyncio.sleep(0.05)

        print(f"  Date {date_str}: {date_candidates} candidates found")

    elapsed = time.time() - start_time
    print(f"\n{'─' * 60}")
    print(f"  Data collection complete in {elapsed:.1f}s")
    print(f"  Raw records: {len(raw_records)}")
    print(f"  Skipped: {skipped}")
    return raw_records


# ─── Parameter Sweep ──────────────────────────────────────────────────────────


def sweep_parameters(raw_records: list[dict]) -> list[dict]:
    """Sweep all ATR×Target1 parameter combinations on collected data.

    For each combo, builds plan and evaluates first-touch outcome.
    Returns list of per-combo summary dicts.
    """
    print(f"\n{'═' * 60}")
    print(f"PHASE 2: PARAMETER SWEEP")
    print(f"{'═' * 60}")
    print(f"  ATR mults: {ATR_MULT_RANGE}")
    print(f"  Target1 mults: {TARGET1_MULT_RANGE}")
    print(f"  Combinations: {len(ATR_MULT_RANGE) * len(TARGET1_MULT_RANGE)}")
    print(f"{'─' * 60}")

    combo_results = []

    for atr_mult in ATR_MULT_RANGE:
        for t1_mult in TARGET1_MULT_RANGE:
            trades: list[TradeResult] = []

            for rec in raw_records:
                plan = build_plan_params(
                    rec["hist_bars"], atr_mult, t1_mult
                )
                if plan is None:
                    continue

                outcome, r_result = evaluate_trade(
                    plan["entry"], plan["stop"], plan["target1"],
                    t1_mult, rec["fwd_bars"]
                )

                trades.append(TradeResult(
                    ticker=rec["ticker"],
                    date=rec["date"],
                    score=rec["score"],
                    entry=plan["entry"],
                    stop=plan["stop"],
                    target1=plan["target1"],
                    atr_pct=plan["atr_pct"],
                    reward_risk=plan["reward_risk"],
                    outcome=outcome,
                    r_result=r_result,
                    forward_bars=rec["fwd_bars"],
                ))

            # Compute metrics for this combo
            resolved = [t for t in trades if t.outcome != "undecided"]
            target_hits = sum(1 for t in resolved if t.outcome == "target_hit")
            hit_rate = target_hits / len(resolved) if resolved else 0.0
            all_r = [t.r_result for t in trades]
            expectancy = mean(all_r) if all_r else 0.0

            combo_results.append({
                "atr_mult": atr_mult,
                "target1_mult": t1_mult,
                "trades": trades,
                "total": len(trades),
                "resolved": len(resolved),
                "target_hits": target_hits,
                "stop_hits": sum(1 for t in resolved if t.outcome == "stop_hit"),
                "undecided": len(trades) - len(resolved),
                "hit_rate": round(hit_rate, 4),
                "expectancy_r": round(expectancy, 4),
            })

            print(f"  ATR={atr_mult:.1f} T1={t1_mult:.1f}: "
                  f"n={len(trades)}, resolved={len(resolved)}, "
                  f"hit={hit_rate:.1%}, exp={expectancy:+.3f}R")

    return combo_results


# ─── Temporal Split & Best Point Selection ────────────────────────────────────


def temporal_split(trades: list[TradeResult]) -> tuple[list[TradeResult], list[TradeResult]]:
    """70/30 temporal split by date."""
    sorted_trades = sorted(trades, key=lambda t: t.date)
    split_idx = int(len(sorted_trades) * IN_SAMPLE_RATIO)
    return sorted_trades[:split_idx], sorted_trades[split_idx:]


def select_best_operating_point(combo_results: list[dict]) -> dict | None:
    """Select best combo: highest hit rate with positive expectancy on IS + OOS.

    Returns the best combo dict with IS/OOS metrics added, or None.
    """
    print(f"\n{'═' * 60}")
    print(f"PHASE 3: OPERATING POINT SELECTION")
    print(f"{'═' * 60}")

    viable = []

    for combo in combo_results:
        trades = combo["trades"]
        if len(trades) < MIN_RESOLVED_TRADES:
            continue

        is_trades, oos_trades = temporal_split(trades)

        # IS metrics
        is_resolved = [t for t in is_trades if t.outcome != "undecided"]
        is_hits = sum(1 for t in is_resolved if t.outcome == "target_hit")
        is_hit_rate = is_hits / len(is_resolved) if is_resolved else 0.0
        is_r = [t.r_result for t in is_trades]
        is_expectancy = mean(is_r) if is_r else 0.0

        # OOS metrics
        oos_resolved = [t for t in oos_trades if t.outcome != "undecided"]
        oos_hits = sum(1 for t in oos_resolved if t.outcome == "target_hit")
        oos_hit_rate = oos_hits / len(oos_resolved) if oos_resolved else 0.0
        oos_r = [t.r_result for t in oos_trades]
        oos_expectancy = mean(oos_r) if oos_r else 0.0

        # Must have positive expectancy on BOTH IS and OOS
        if is_expectancy > 0 and oos_expectancy > 0:
            viable.append({
                **combo,
                "is_trades": len(is_trades),
                "is_resolved": len(is_resolved),
                "is_hit_rate": round(is_hit_rate, 4),
                "is_expectancy": round(is_expectancy, 4),
                "oos_trades": len(oos_trades),
                "oos_resolved": len(oos_resolved),
                "oos_hit_rate": round(oos_hit_rate, 4),
                "oos_expectancy": round(oos_expectancy, 4),
            })

    if not viable:
        print("  WARNING: No combo has positive expectancy on both IS and OOS!")
        # Fallback: pick best overall expectancy
        positive = [c for c in combo_results if c["expectancy_r"] > 0]
        if positive:
            best = max(positive, key=lambda x: x["expectancy_r"])
            trades = best["trades"]
            is_trades, oos_trades = temporal_split(trades)
            is_r = [t.r_result for t in is_trades]
            oos_r = [t.r_result for t in oos_trades]
            best.update({
                "is_trades": len(is_trades),
                "is_resolved": sum(1 for t in is_trades if t.outcome != "undecided"),
                "is_hit_rate": best["hit_rate"],
                "is_expectancy": round(mean(is_r) if is_r else 0.0, 4),
                "oos_trades": len(oos_trades),
                "oos_resolved": sum(1 for t in oos_trades if t.outcome != "undecided"),
                "oos_hit_rate": best["hit_rate"],
                "oos_expectancy": round(mean(oos_r) if oos_r else 0.0, 4),
            })
            print(f"  Fallback: best overall expectancy combo selected")
            return best
        return None

    # Select highest hit rate among viable
    best = max(viable, key=lambda x: x["is_hit_rate"])

    print(f"  Viable combos (IS+OOS positive): {len(viable)}")
    print(f"  Best: ATR={best['atr_mult']:.1f}, T1={best['target1_mult']:.1f}")
    print(f"    IS:  hit={best['is_hit_rate']:.1%}, exp={best['is_expectancy']:+.4f}R")
    print(f"    OOS: hit={best['oos_hit_rate']:.1%}, exp={best['oos_expectancy']:+.4f}R")

    return best


# ─── Bucket Calibration ──────────────────────────────────────────────────────


def compute_bucket_calibration(best_combo: dict) -> dict[str, BucketStats]:
    """Compute per-bucket stats from the best combo's trades."""
    trades = best_combo["trades"]
    buckets: dict[str, BucketStats] = {}

    for t in trades:
        bucket_id, score_band, atr_band = classify_bucket(t.score, t.atr_pct)

        if bucket_id not in buckets:
            buckets[bucket_id] = BucketStats(
                bucket_id=bucket_id,
                score_band=score_band,
                atr_band=atr_band,
            )

        b = buckets[bucket_id]
        b.total += 1
        b.r_results.append(t.r_result)

        if t.outcome == "target_hit":
            b.target_hits += 1
        elif t.outcome == "stop_hit":
            b.stop_hits += 1
        else:
            b.undecided += 1

    return buckets


# ─── Output Writers ───────────────────────────────────────────────────────────


def write_calibration_json(best_combo: dict,
                           buckets: dict[str, BucketStats]) -> None:
    """Write calibration JSON with real bucket probabilities."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    bucket_data = {}
    for bid, b in sorted(buckets.items()):
        bucket_data[bid] = {
            "score_band": b.score_band,
            "atr_band": b.atr_band,
            "sample_size": b.total,
            "realized_hit_rate": round(b.hit_rate, 4),
            "mean_expectancy_r": round(b.expectancy, 4),
            "prob_hit_target1": round(b.hit_rate, 4),
        }

    calibration = {
        "version": "2.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "method": "comprehensive_backtest",
        "sample_period": {
            "start": BACKTEST_DATES[0],
            "end": BACKTEST_DATES[-1],
        },
        "universe_size": len(load_halal_universe()),
        "scan_dates": len(BACKTEST_DATES),
        "total_trades": best_combo["total"],
        "operating_point": {
            "atr_mult": best_combo["atr_mult"],
            "target1_mult": best_combo["target1_mult"],
            "target2_mult": best_combo["target1_mult"] + 1.0,
            "is_expectancy_r": best_combo.get("is_expectancy", 0.0),
            "oos_expectancy_r": best_combo.get("oos_expectancy", 0.0),
            "overall_hit_rate": best_combo["hit_rate"],
            "breakeven_rate": round(1.0 / (1.0 + best_combo["target1_mult"]), 4),
        },
        "validation": {
            "overall_expectancy_r": best_combo["expectancy_r"],
            "is_hit_rate": best_combo.get("is_hit_rate", 0.0),
            "is_expectancy_r": best_combo.get("is_expectancy", 0.0),
            "oos_hit_rate": best_combo.get("oos_hit_rate", 0.0),
            "oos_expectancy_r": best_combo.get("oos_expectancy", 0.0),
            "breakeven_rate": round(1.0 / (1.0 + best_combo["target1_mult"]), 4),
            "passes_breakeven": best_combo["hit_rate"] > 1.0 / (1.0 + best_combo["target1_mult"]),
            "passes_positive_expectancy": best_combo["expectancy_r"] > 0,
            "passes_oos_positive": best_combo.get("oos_expectancy", 0.0) > 0,
        },
        "buckets": bucket_data,
    }

    with open(CALIBRATION_OUTPUT, "w") as f:
        json.dump(calibration, f, indent=2)

    print(f"\n  Calibration written to: {CALIBRATION_OUTPUT}")
    print(f"  Buckets: {len(bucket_data)}")


def write_report(best_combo: dict, combo_results: list[dict],
                 buckets: dict[str, BucketStats], raw_count: int) -> None:
    """Write comprehensive results report as markdown."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Trade Engine Comprehensive Backtest Results",
        "",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Overview",
        "",
        f"- **Universe**: {len(load_halal_universe())} halal tickers (full universe)",
        f"- **Scan dates**: {len(BACKTEST_DATES)} monthly dates "
        f"({BACKTEST_DATES[0]} to {BACKTEST_DATES[-1]})",
        f"- **Raw candidates evaluated**: {raw_count}",
        f"- **Parameter grid**: {len(ATR_MULT_RANGE)}×{len(TARGET1_MULT_RANGE)} "
        f"= {len(ATR_MULT_RANGE)*len(TARGET1_MULT_RANGE)} combinations",
        f"- **Temporal split**: 70% in-sample / 30% out-of-sample",
        "",
        "## Best Operating Point",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| ATR Multiplier | {best_combo['atr_mult']:.1f} |",
        f"| Target1 Multiplier | {best_combo['target1_mult']:.1f} |",
        f"| Total Trades | {best_combo['total']} |",
        f"| Resolved | {best_combo['resolved']} |",
        f"| Overall Hit Rate | {best_combo['hit_rate']:.1%} |",
        f"| Overall Expectancy | {best_combo['expectancy_r']:+.4f}R |",
        f"| IS Hit Rate | {best_combo.get('is_hit_rate', 0):.1%} |",
        f"| IS Expectancy | {best_combo.get('is_expectancy', 0):+.4f}R |",
        f"| OOS Hit Rate | {best_combo.get('oos_hit_rate', 0):.1%} |",
        f"| OOS Expectancy | {best_combo.get('oos_expectancy', 0):+.4f}R |",
        "",
        "## Full Parameter Sweep Results",
        "",
        "| ATR | T1 | Trades | Resolved | Hit Rate | Expectancy |",
        "|-----|-----|--------|----------|----------|------------|",
    ]

    for c in sorted(combo_results, key=lambda x: x["expectancy_r"], reverse=True):
        lines.append(
            f"| {c['atr_mult']:.1f} | {c['target1_mult']:.1f} | "
            f"{c['total']} | {c['resolved']} | "
            f"{c['hit_rate']:.1%} | {c['expectancy_r']:+.4f}R |"
        )

    lines.extend(["", "## Calibration Buckets", ""])
    lines.append("| Bucket | N | Resolved | Hit Rate | Expectancy |")
    lines.append("|--------|---|----------|----------|------------|")

    for bid, b in sorted(buckets.items()):
        lines.append(
            f"| {bid} | {b.total} | {b.resolved} | "
            f"{b.hit_rate:.1%} | {b.expectancy:+.3f}R |"
        )

    lines.extend([
        "",
        "## Methodology",
        "",
        "1. Load full halal universe (212 tickers)",
        "2. For each of 24 monthly dates, fetch 400 calendar days of history",
        "3. Identify BUY candidates: price > SMA(50) AND price > SMA(200)",
        "4. Score candidates using simplified Minervini proxy",
        "5. For each candidate, fetch 55 calendar days forward data",
        "6. Sweep 25 parameter combinations (ATR mult × Target1 mult)",
        "7. Evaluate first-touch: stop or target1 hit within 30 bars",
        "8. 70/30 temporal split for in-sample vs out-of-sample",
        "9. Select best point: highest hit rate with positive IS+OOS expectancy",
        "10. Compute per-bucket probabilities for calibration table",
        "",
        "## Notes",
        "",
        "- Undecided trades (neither stop nor target hit in 30 bars) "
        "counted as 0R in expectancy",
        "- Breakeven rate = 1 / (1 + target1_mult)",
        "- All data from Polygon.io premium API (adjusted prices, sorted asc)",
        "",
    ])

    with open(REPORT_OUTPUT, "w") as f:
        f.write("\n".join(lines))

    print(f"  Report written to: {REPORT_OUTPUT}")


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main():
    """Run comprehensive backtest."""
    total_start = time.time()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     COMPREHENSIVE TRADE PLAN BACKTEST                       ║")
    print("║     Full Halal Universe × 24 Months × 25 Param Combos      ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # Load full halal universe
    tickers = list(load_halal_universe())
    print(f"\n  Halal universe loaded: {len(tickers)} tickers")

    if not tickers:
        print("ERROR: No tickers loaded from halal universe!")
        sys.exit(1)

    # Initialize API client (premium plan: max_concurrent=5)
    client = RestApiClient(max_concurrent=5)
    print(f"  API client initialized (max_concurrent=5)")

    try:
        # Phase 1: Collect raw data
        raw_records = await collect_raw_data(client, tickers)

        if not raw_records:
            print("\nERROR: No valid records collected! Check API connectivity.")
            sys.exit(1)

        # Phase 2: Parameter sweep
        combo_results = sweep_parameters(raw_records)

        if not combo_results:
            print("\nERROR: No parameter combinations produced results!")
            sys.exit(1)

        # Phase 3: Select best operating point
        best = select_best_operating_point(combo_results)

        if best is None:
            print("\nERROR: No viable operating point found!")
            # Write what we have anyway
            best = max(combo_results, key=lambda x: x["expectancy_r"])
            best.update({
                "is_hit_rate": best["hit_rate"],
                "is_expectancy": best["expectancy_r"],
                "oos_hit_rate": best["hit_rate"],
                "oos_expectancy": best["expectancy_r"],
            })

        # Phase 4: Bucket calibration
        print(f"\n{'═' * 60}")
        print(f"PHASE 4: BUCKET CALIBRATION")
        print(f"{'═' * 60}")

        buckets = compute_bucket_calibration(best)
        for bid, b in sorted(buckets.items()):
            print(f"  {bid}: n={b.total}, resolved={b.resolved}, "
                  f"hit={b.hit_rate:.1%}, exp={b.expectancy:+.3f}R")

        # Phase 5: Write outputs
        print(f"\n{'═' * 60}")
        print(f"PHASE 5: WRITING OUTPUTS")
        print(f"{'═' * 60}")

        write_calibration_json(best, buckets)
        write_report(best, combo_results, buckets, len(raw_records))

    finally:
        await client.close()

    # Final summary
    total_elapsed = time.time() - total_start

    print(f"\n")
    print(f"COMPREHENSIVE BACKTEST COMPLETE")
    print(f"{'═' * 40}")
    print(f"Total trades evaluated: {best['total']}")
    print(f"Best parameters: ATR={best['atr_mult']:.1f}, "
          f"T1={best['target1_mult']:.1f}")
    print(f"  IS hit rate: {best.get('is_hit_rate', 0)*100:.1f}%  "
          f"IS expectancy: {best.get('is_expectancy', 0):+.3f}R")
    print(f"  OOS hit rate: {best.get('oos_hit_rate', 0)*100:.1f}%  "
          f"OOS expectancy: {best.get('oos_expectancy', 0):+.3f}R")
    print(f"")
    print(f"Calibration table written with {len(buckets)} buckets")
    print(f"Total runtime: {total_elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
