"""
Entry Timing Validation Backtest

Validates the Entry Timing classifier (core/entry_timing.py) by measuring the
30-trading-day forward outcomes of stocks classified into each entry zone
(buy_zone / extended / overbought).

HYPOTHESIS: buy_zone stocks have HIGHER forward returns and LOWER (less negative)
drawdown than overbought stocks over the next 30 trading days.

Also runs a threshold-sensitivity sweep on the RSI overbought cutoff (65/70/75)
to recommend the best separation.

Data pattern reused from scripts/comprehensive_backtest.py.

Run from backend/:  python scripts/entry_timing_backtest.py
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.entry_timing as entry_timing  # noqa: E402
from core.api_client import RestApiClient  # noqa: E402
from core.entry_timing import classify_entry_timing  # noqa: E402
from core.halal_universe import load_halal_universe  # noqa: E402
from core.indicator_calculator import IndicatorCalculator  # noqa: E402
from core.models import StockData  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────────────

FORWARD_BARS = 30              # trading bars measured forward
MIN_HISTORY_BARS = 200        # need SMA200 for uptrend filter
CALENDAR_FETCH_DAYS = 400     # ~274 trading bars
FORWARD_CALENDAR_DAYS = 45    # ~30 trading bars forward
MIN_FORWARD_BARS = 20         # require at least this many forward bars
PROGRESS_INTERVAL = 50
ZONES = ("buy_zone", "extended", "overbought")

# RSI overbought cutoffs for threshold sensitivity sweep
RSI_CUTOFF_SWEEP = [65.0, 70.0, 75.0]

# 24 monthly scan dates: Jan 2023 through Dec 2024 (same style as comprehensive_backtest)
BACKTEST_DATES = [
    "2023-01-03", "2023-02-01", "2023-03-01", "2023-04-03",
    "2023-05-01", "2023-06-01", "2023-07-03", "2023-08-01",
    "2023-09-01", "2023-10-02", "2023-11-01", "2023-12-01",
    "2024-01-02", "2024-02-01", "2024-03-01", "2024-04-01",
    "2024-05-01", "2024-06-03", "2024-07-01", "2024-08-01",
    "2024-09-03", "2024-10-01", "2024-11-01", "2024-12-02",
]

MARKET_TICKER = "SPY"

# Output paths
DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
REPORT_OUTPUT = DOCS_DIR / "ENTRY_TIMING_VALIDATION.md"


# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class ScanRecord:
    """A classified candidate with its forward outcome measured."""

    ticker: str
    date: str
    entry: float
    rsi: float | None
    dist_above_sma50: float | None
    proximity_high: float | None
    roc_10: float | None
    fwd_return_30d: float
    max_gain: float
    max_drawdown: float
    positive_30d: bool


@dataclass
class ZoneAgg:
    """Aggregated outcomes for one entry zone."""

    zone: str
    returns: list[float] = field(default_factory=list)
    drawdowns: list[float] = field(default_factory=list)
    gains: list[float] = field(default_factory=list)
    positives: int = 0

    @property
    def count(self) -> int:
        return len(self.returns)

    @property
    def mean_return(self) -> float:
        return mean(self.returns) if self.returns else 0.0

    @property
    def median_return(self) -> float:
        return median(self.returns) if self.returns else 0.0

    @property
    def mean_drawdown(self) -> float:
        return mean(self.drawdowns) if self.drawdowns else 0.0

    @property
    def pct_positive(self) -> float:
        return (self.positives / self.count * 100.0) if self.count else 0.0


# ─── Helpers ──────────────────────────────────────────────────────────────────


def bars_to_stockdata(ticker: str, bars: list[dict]) -> StockData:
    """Convert a list of OHLCV bar dicts into a StockData object."""
    prices = np.array([b["close"] for b in bars], dtype=np.float64)
    volumes = np.array([b["volume"] for b in bars], dtype=np.float64)
    highs = np.array([b["high"] for b in bars], dtype=np.float64)
    lows = np.array([b["low"] for b in bars], dtype=np.float64)
    # Synthetic ascending timestamps (not used by the calculator)
    timestamps = np.arange(len(bars), dtype=np.int64)
    return StockData(
        ticker=ticker,
        prices=prices,
        volumes=volumes,
        timestamps=timestamps,
        highs=highs,
        lows=lows,
    )


def passes_uptrend_filter(current_price: float, indicators) -> bool:
    """Basic candidate filter: price > SMA50 AND price > SMA200."""
    if indicators.sma_50 is None or indicators.sma_200 is None:
        return False
    return current_price > indicators.sma_50 and current_price > indicators.sma_200


def measure_forward_outcome(entry: float, fwd_bars: list[dict]) -> tuple[float, float, float, bool]:
    """Measure 30-bar forward outcome.

    Returns (fwd_return_30d, max_gain, max_drawdown, positive_30d).
    Uses up to FORWARD_BARS bars. fwd_return uses the close of the last
    available bar within the window (bar 30, or fewer if truncated).
    """
    window = fwd_bars[:FORWARD_BARS]
    highs = [b["high"] for b in window]
    lows = [b["low"] for b in window]
    close_end = window[-1]["close"]

    fwd_return_30d = (close_end - entry) / entry * 100.0
    max_gain = (max(highs) - entry) / entry * 100.0
    max_drawdown = (min(lows) - entry) / entry * 100.0
    positive_30d = fwd_return_30d > 0
    return fwd_return_30d, max_gain, max_drawdown, positive_30d


# ─── Data Collection ──────────────────────────────────────────────────────────


async def collect_candidates(client: RestApiClient, tickers: list[str]) -> list[dict]:
    """Fetch history + forward data, apply uptrend filter, keep raw records.

    Each kept record stores current_price, computed indicators, and the
    forward outcome so that classification (default + threshold sweep) can be
    replayed without re-fetching.

    Returns list of dicts ready for classification.
    """
    calc = IndicatorCalculator()
    records: list[dict] = []
    total = len(BACKTEST_DATES) * len(tickers)
    processed = 0
    skipped = 0
    start = time.time()

    print(f"\n{'═' * 60}")
    print("PHASE 1: DATA COLLECTION")
    print(f"{'═' * 60}")
    print(f"  Tickers: {len(tickers)}  Dates: {len(BACKTEST_DATES)}  Combos: {total}")
    print(f"{'─' * 60}")

    for date_str in BACKTEST_DATES:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        hist_from = (dt - timedelta(days=CALENDAR_FETCH_DAYS)).strftime("%Y-%m-%d")
        fwd_from = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        fwd_to = (dt + timedelta(days=FORWARD_CALENDAR_DAYS)).strftime("%Y-%m-%d")

        # Fetch SPY once per date for relative strength (reused across tickers)
        try:
            spy_bars = await client.fetch_stock_data_range(MARKET_TICKER, hist_from, date_str)
            market_data = bars_to_stockdata(MARKET_TICKER, spy_bars) if spy_bars else None
        except Exception:
            market_data = None
        if market_data is None:
            # Fallback: empty market data (relative_strength will be None)
            market_data = bars_to_stockdata(MARKET_TICKER, [])

        date_kept = 0

        for ticker in tickers:
            processed += 1
            if processed % PROGRESS_INTERVAL == 0:
                elapsed = time.time() - start
                rate = processed / elapsed if elapsed > 0 else 0
                print(f"  [{processed}/{total}] ({rate:.1f}/s) "
                      f"kept={len(records)} skipped={skipped}")

            try:
                hist_bars = await client.fetch_stock_data_range(ticker, hist_from, date_str)
                if len(hist_bars) < MIN_HISTORY_BARS:
                    skipped += 1
                    continue

                stock_data = bars_to_stockdata(ticker, hist_bars)
                indicators = calc.calculate_all(stock_data, market_data)
                current_price = float(stock_data.prices[-1])

                # Uptrend candidate filter
                if not passes_uptrend_filter(current_price, indicators):
                    skipped += 1
                    continue

                # Forward data
                fwd_bars = await client.fetch_stock_data_range(ticker, fwd_from, fwd_to)
                if len(fwd_bars) < MIN_FORWARD_BARS:
                    skipped += 1
                    continue

                fwd_ret, max_gain, max_dd, positive = measure_forward_outcome(
                    current_price, fwd_bars
                )

                # dist above sma50 for record display
                dist50 = None
                if indicators.sma_50 and indicators.sma_50 > 0:
                    dist50 = (current_price - indicators.sma_50) / indicators.sma_50 * 100.0

                records.append({
                    "ticker": ticker,
                    "date": date_str,
                    "current_price": current_price,
                    "indicators": indicators,
                    "rsi": indicators.rsi_14,
                    "dist_above_sma50": dist50,
                    "proximity_high": indicators.proximity_to_20d_high,
                    "roc_10": indicators.roc_10,
                    "fwd_return_30d": fwd_ret,
                    "max_gain": max_gain,
                    "max_drawdown": max_dd,
                    "positive_30d": positive,
                })
                date_kept += 1

            except Exception:
                skipped += 1
                continue

            await asyncio.sleep(0.03)

        print(f"  Date {date_str}: {date_kept} candidates kept")

    elapsed = time.time() - start
    print(f"{'─' * 60}")
    print(f"  Collection done in {elapsed:.1f}s | kept={len(records)} skipped={skipped}")
    return records


# ─── Classification & Aggregation ─────────────────────────────────────────────


def aggregate_by_zone(records: list[dict]) -> dict[str, ZoneAgg]:
    """Classify each record at current module thresholds and aggregate by zone."""
    aggs = {z: ZoneAgg(zone=z) for z in ZONES}

    for rec in records:
        timing = classify_entry_timing(rec["current_price"], rec["indicators"])
        zone = timing.zone
        if zone not in aggs:
            aggs[zone] = ZoneAgg(zone=zone)
        agg = aggs[zone]
        agg.returns.append(rec["fwd_return_30d"])
        agg.drawdowns.append(rec["max_drawdown"])
        agg.gains.append(rec["max_gain"])
        if rec["positive_30d"]:
            agg.positives += 1

    return aggs


def run_threshold_sweep(records: list[dict]) -> dict[float, dict[str, ZoneAgg]]:
    """Re-classify all records under alternative RSI overbought cutoffs.

    Temporarily overrides entry_timing.RSI_OVERBOUGHT (and keeps RSI_ELEVATED
    just below it so the 'elevated' band stays meaningful), then restores.
    """
    original_ob = entry_timing.RSI_OVERBOUGHT
    original_elev = entry_timing.RSI_ELEVATED
    sweep: dict[float, dict[str, ZoneAgg]] = {}

    try:
        for cutoff in RSI_CUTOFF_SWEEP:
            entry_timing.RSI_OVERBOUGHT = cutoff
            # Keep elevated band 5 pts below the overbought cutoff (but not above it)
            entry_timing.RSI_ELEVATED = min(original_elev, cutoff - 5.0)
            sweep[cutoff] = aggregate_by_zone(records)
    finally:
        entry_timing.RSI_OVERBOUGHT = original_ob
        entry_timing.RSI_ELEVATED = original_elev

    return sweep


def evaluate_hypothesis(aggs: dict[str, ZoneAgg]) -> dict:
    """Check: buy_zone return > extended > overbought AND buy_zone DD > overbought DD."""
    bz = aggs.get("buy_zone", ZoneAgg("buy_zone"))
    ext = aggs.get("extended", ZoneAgg("extended"))
    ob = aggs.get("overbought", ZoneAgg("overbought"))

    return_spread = bz.mean_return - ob.mean_return
    ordering_ok = bz.mean_return > ext.mean_return > ob.mean_return
    return_ok = return_spread > 0
    # buy_zone DD "smaller" = less negative = greater value
    drawdown_ok = bz.mean_drawdown > ob.mean_drawdown

    return {
        "return_spread": return_spread,
        "ordering_ok": ordering_ok,
        "return_ok": return_ok,
        "drawdown_ok": drawdown_ok,
        "buy_zone_dd": bz.mean_drawdown,
        "overbought_dd": ob.mean_drawdown,
        "passed": return_ok and drawdown_ok,
    }


# ─── Classification Metrics ───────────────────────────────────────────────────


def compute_classification_metrics(records, predict_fn, label_fn) -> dict:
    """Treat the classifier as a binary predictor and compute a confusion matrix.

    Args:
        records: list of record dicts (must have a "zone" key set, plus the
                 outcome fields the label_fn needs).
        predict_fn: callable(record) -> bool, True if "predicted positive".
        label_fn: callable(record) -> bool, True if "actually positive".

    Returns:
        dict with tp/fp/fn/tn/total/precision/recall/accuracy/f1/specificity/
        base_rate/lift. All rates are fractions in [0, 1]. Division-by-zero is
        guarded (returns 0.0 for the affected metric).
    """
    tp = fp = fn = tn = 0
    for rec in records:
        predicted = bool(predict_fn(rec))
        actual = bool(label_fn(rec))
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1

    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    accuracy = (tp + tn) / total if total else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    base_rate = (tp + fn) / total if total else 0.0
    lift = (precision / base_rate) if base_rate else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn, "total": total,
        "precision": precision, "recall": recall, "accuracy": accuracy,
        "f1": f1, "specificity": specificity,
        "base_rate": base_rate, "lift": lift,
    }


def _ensure_zones(records: list[dict]) -> None:
    """Classify each record at current module thresholds and cache its zone."""
    for rec in records:
        if "zone" not in rec:
            rec["zone"] = classify_entry_timing(
                rec["current_price"], rec["indicators"]
            ).zone


def build_framings() -> list[dict]:
    """Define the binary-predictor framings (A variants + B variants).

    Each framing is a dict describing its predicate, label, and the row/column
    text used when rendering the confusion matrix block.
    """
    return [
        {
            "key": "A1",
            "title": 'FRAMING A1: "overbought flags a LOSING trade"',
            "predict": lambda r: r["zone"] == "overbought",
            "label": lambda r: r["fwd_return_30d"] <= 0.0,
            "pos_col": "Actual Loser", "neg_col": "Actual Winner",
            "flag_row": "Overbought   ", "safe_row": "Not overbought",
            "base_label": "losers",
        },
        {
            "key": "A2",
            "title": 'FRAMING A2: "extended OR overbought flags a LOSING trade"',
            "predict": lambda r: r["zone"] in ("extended", "overbought"),
            "label": lambda r: r["fwd_return_30d"] <= 0.0,
            "pos_col": "Actual Loser", "neg_col": "Actual Winner",
            "flag_row": "Ext/Overbought", "safe_row": "Buy zone     ",
            "base_label": "losers",
        },
        {
            "key": "B10",
            "title": 'FRAMING B: "not-buy_zone flags a >=10% drawdown"',
            "predict": lambda r: r["zone"] != "buy_zone",
            "label": lambda r: r["max_drawdown"] <= -10.0,
            "pos_col": "Actual DD>=10%", "neg_col": "Actual DD<10%",
            "flag_row": "Flagged (risky)", "safe_row": "Buy zone (safe)",
            "base_label": "DD>=10%",
        },
        {
            "key": "B15",
            "title": 'FRAMING B (15%): "not-buy_zone flags a >=15% drawdown"',
            "predict": lambda r: r["zone"] != "buy_zone",
            "label": lambda r: r["max_drawdown"] <= -15.0,
            "pos_col": "Actual DD>=15%", "neg_col": "Actual DD<15%",
            "flag_row": "Flagged (risky)", "safe_row": "Buy zone (safe)",
            "base_label": "DD>=15%",
        },
    ]


def run_classification_analysis(records: list[dict]) -> list[dict]:
    """Compute metrics for every framing. Returns list of {framing, metrics}."""
    _ensure_zones(records)
    results = []
    for framing in build_framings():
        metrics = compute_classification_metrics(
            records, framing["predict"], framing["label"]
        )
        results.append({"framing": framing, "metrics": metrics})
    return results


# ─── Console Output ───────────────────────────────────────────────────────────


def print_zone_table(aggs: dict[str, ZoneAgg], n_dates: int, n_tickers: int) -> None:
    """Print the main zone performance table."""
    print(f"\nZONE PERFORMANCE (30-day forward, {n_dates} dates × {n_tickers} tickers)")
    print("═" * 63)
    print(f"{'Zone':<11} | {'N':<5}| {'Mean Ret':<9}| {'Median':<8}| "
          f"{'Max DD':<8}| % Positive")
    for z in ZONES:
        a = aggs.get(z, ZoneAgg(z))
        print(f"{z:<11} | {a.count:<5}| {a.mean_return:+7.1f}% | "
              f"{a.median_return:+6.1f}% | {a.mean_drawdown:+6.1f}% | "
              f"{a.pct_positive:.0f}%")


def print_hypothesis(h: dict) -> None:
    """Print hypothesis evaluation block."""
    ret_flag = "PASS" if h["return_ok"] else "FAIL"
    dd_flag = "PASS" if h["drawdown_ok"] else "FAIL"
    print("\nHYPOTHESIS: buy_zone outperforms overbought?")
    print(f"  Return spread: buy_zone - overbought = {h['return_spread']:+.1f}%  [{ret_flag}]")
    print(f"  Drawdown: buy_zone DD vs overbought DD = "
          f"{h['buy_zone_dd']:.1f}% vs {h['overbought_dd']:.1f}%  [{dd_flag}]")
    order_flag = "PASS" if h["ordering_ok"] else "FAIL"
    print(f"  Ordering (buy_zone > extended > overbought): [{order_flag}]")
    print(f"\n  OVERALL: {'PASS ✓' if h['passed'] else 'FAIL ✗'}")


def print_threshold_sweep(sweep: dict[float, dict[str, ZoneAgg]]) -> None:
    """Print how zone separation changes across RSI overbought cutoffs."""
    print(f"\n{'═' * 63}")
    print("THRESHOLD SENSITIVITY — RSI overbought cutoff sweep")
    print("═" * 63)
    print(f"{'RSI cut':<8}| {'bz N/Ret':<14}| {'ext N/Ret':<14}| "
          f"{'ob N/Ret':<14}| bz-ob spread")
    for cutoff in RSI_CUTOFF_SWEEP:
        aggs = sweep[cutoff]
        bz = aggs.get("buy_zone", ZoneAgg("buy_zone"))
        ext = aggs.get("extended", ZoneAgg("extended"))
        ob = aggs.get("overbought", ZoneAgg("overbought"))
        spread = bz.mean_return - ob.mean_return
        print(f"{cutoff:<8.0f}| {bz.count:>4} {bz.mean_return:+6.1f}% | "
              f"{ext.count:>4} {ext.mean_return:+6.1f}% | "
              f"{ob.count:>4} {ob.mean_return:+6.1f}% | {spread:+.1f}%")


def print_classification_metrics(results: list[dict]) -> None:
    """Print a confusion-matrix + metrics block for each framing."""
    print(f"\n{'═' * 63}")
    print("CLASSIFICATION METRICS (classifier as a binary predictor)")
    print("═" * 63)
    for item in results:
        fr = item["framing"]
        m = item["metrics"]
        print(f"\n{fr['title']}")
        print("  Confusion matrix:")
        print(f"                        {fr['pos_col']:<15} {fr['neg_col']}")
        print(f"    {fr['flag_row']}     TP={m['tp']:<10} FP={m['fp']}")
        print(f"    {fr['safe_row']}     FN={m['fn']:<10} TN={m['tn']}")
        print(f"  Precision: {m['precision'] * 100:.1f}%   "
              f"Recall: {m['recall'] * 100:.1f}%   "
              f"Accuracy: {m['accuracy'] * 100:.1f}%")
        print(f"  F1: {m['f1'] * 100:.1f}%   "
              f"Specificity: {m['specificity'] * 100:.1f}%   "
              f"Base rate ({fr['base_label']}): {m['base_rate'] * 100:.1f}%")
        print(f"  Lift over base rate: {m['lift']:.2f}x")


# ─── Report Writer ────────────────────────────────────────────────────────────


def recommend_threshold(sweep: dict[float, dict[str, ZoneAgg]]) -> tuple[float, str]:
    """Pick the RSI cutoff with the largest buy_zone - overbought return spread,
    requiring both zones to have a usable sample (>= 20)."""
    best_cutoff = None
    best_spread = -1e9
    for cutoff in RSI_CUTOFF_SWEEP:
        aggs = sweep[cutoff]
        bz = aggs.get("buy_zone", ZoneAgg("buy_zone"))
        ob = aggs.get("overbought", ZoneAgg("overbought"))
        if bz.count < 20 or ob.count < 20:
            continue
        spread = bz.mean_return - ob.mean_return
        if spread > best_spread:
            best_spread = spread
            best_cutoff = cutoff
    if best_cutoff is None:
        return entry_timing.RSI_OVERBOUGHT, "insufficient separation; kept default"
    note = f"largest buy_zone−overbought spread ({best_spread:+.1f}%) with adequate sample"
    return best_cutoff, note


def write_report(aggs, h, sweep, n_records, n_tickers, elapsed) -> None:
    """Write the validation report markdown (chunked writes)."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    rec_cut, rec_note = recommend_threshold(sweep)

    lines = [
        "# Entry Timing Classifier Validation",
        "",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Overview",
        "",
        f"- **Universe**: {n_tickers} halal tickers (full universe)",
        f"- **Scan dates**: {len(BACKTEST_DATES)} monthly "
        f"({BACKTEST_DATES[0]} to {BACKTEST_DATES[-1]})",
        f"- **Candidates classified**: {n_records} (passed price > SMA50 AND price > SMA200)",
        f"- **Forward horizon**: {FORWARD_BARS} trading bars",
        f"- **Runtime**: {elapsed:.1f}s",
        "",
        "## Hypothesis",
        "",
        "> buy_zone stocks have HIGHER forward returns and LOWER (less negative) "
        "drawdown than overbought stocks over the next 30 trading days.",
        "",
    ]
    with open(REPORT_OUTPUT, "w") as f:
        f.write("\n".join(lines) + "\n")

    # Zone performance table
    zlines = [
        "## Zone Performance (30-day forward)",
        "",
        "| Zone | N | Mean Ret | Median | Max DD | % Positive |",
        "|------|---|----------|--------|--------|------------|",
    ]
    for z in ZONES:
        a = aggs.get(z, ZoneAgg(z))
        zlines.append(
            f"| {z} | {a.count} | {a.mean_return:+.1f}% | {a.median_return:+.1f}% | "
            f"{a.mean_drawdown:+.1f}% | {a.pct_positive:.0f}% |"
        )
    zlines.append("")
    with open(REPORT_OUTPUT, "a") as f:
        f.write("\n".join(zlines) + "\n")

    # Hypothesis result
    hlines = [
        "## Hypothesis Result",
        "",
        f"- **Return spread** (buy_zone − overbought): **{h['return_spread']:+.1f}%** "
        f"— {'PASS' if h['return_ok'] else 'FAIL'}",
        f"- **Drawdown** (buy_zone {h['buy_zone_dd']:.1f}% vs overbought "
        f"{h['overbought_dd']:.1f}%): {'PASS' if h['drawdown_ok'] else 'FAIL'} "
        f"(buy_zone drawdown should be less negative)",
        f"- **Monotonic ordering** (buy_zone > extended > overbought): "
        f"{'PASS' if h['ordering_ok'] else 'FAIL'}",
        "",
        f"### Overall: {'✅ PASS' if h['passed'] else '❌ FAIL'}",
        "",
    ]
    with open(REPORT_OUTPUT, "a") as f:
        f.write("\n".join(hlines) + "\n")

    # Threshold sensitivity + recommendation
    slines = [
        "## Threshold Sensitivity (RSI overbought cutoff)",
        "",
        "| RSI cutoff | buy_zone N / Ret | extended N / Ret | overbought N / Ret | bz−ob spread |",
        "|-----------|------------------|------------------|--------------------|--------------|",
    ]
    for cutoff in RSI_CUTOFF_SWEEP:
        a = sweep[cutoff]
        bz = a.get("buy_zone", ZoneAgg("buy_zone"))
        ext = a.get("extended", ZoneAgg("extended"))
        ob = a.get("overbought", ZoneAgg("overbought"))
        spread = bz.mean_return - ob.mean_return
        slines.append(
            f"| {cutoff:.0f} | {bz.count} / {bz.mean_return:+.1f}% | "
            f"{ext.count} / {ext.mean_return:+.1f}% | "
            f"{ob.count} / {ob.mean_return:+.1f}% | {spread:+.1f}% |"
        )
    rec_cut, rec_note = recommend_threshold(sweep)
    slines.extend([
        "",
        "## Threshold Recommendation",
        "",
        f"**Recommended RSI overbought cutoff: {rec_cut:.0f}**",
        "",
        f"Rationale: {rec_note}. A larger buy_zone−overbought return spread means the "
        "classifier separates healthy entries from exhausted ones more cleanly. The "
        "current default is 70.",
        "",
        "## Methodology",
        "",
        "1. Load full halal universe.",
        "2. For each monthly scan date, fetch 400 calendar days of history per ticker.",
        "3. Fetch SPY once per date for relative strength; reuse across tickers.",
        "4. Compute indicators (RSI14, SMA50/200, ROC10, proximity to 20d high).",
        "5. Keep only uptrend candidates: price > SMA50 AND price > SMA200.",
        "6. Classify the entry zone at the scan date.",
        "7. Fetch 45 calendar days forward; measure outcomes over the next 30 trading bars.",
        "8. Aggregate by zone; evaluate the hypothesis; sweep RSI cutoffs 65/70/75.",
        "",
        "Notes: forward return uses the close of the last bar within the 30-bar window; "
        "max drawdown is the lowest low vs entry (the key profit-taking risk metric).",
        "",
    ])
    with open(REPORT_OUTPUT, "a") as f:
        f.write("\n".join(slines) + "\n")

    print(f"\n  Report written to: {REPORT_OUTPUT}")


def append_classification_report(results: list[dict]) -> None:
    """Append a '## Classification Metrics' section to the report."""
    lines = [
        "## Classification Metrics",
        "",
        "Treats the entry-timing classifier as a binary predictor under two "
        "framings. Predicted-positive = the classifier raised a caution flag; "
        "actual-positive = the bad outcome actually occurred.",
        "",
        "| Framing | TP | FP | FN | TN | Precision | Recall | Accuracy | F1 | "
        "Specificity | Base rate | Lift |",
        "|---------|----|----|----|----|-----------|--------|----------|----|"
        "-------------|-----------|------|",
    ]
    for item in results:
        fr = item["framing"]
        m = item["metrics"]
        lines.append(
            f"| {fr['title']} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | "
            f"{m['precision'] * 100:.1f}% | {m['recall'] * 100:.1f}% | "
            f"{m['accuracy'] * 100:.1f}% | {m['f1'] * 100:.1f}% | "
            f"{m['specificity'] * 100:.1f}% | {m['base_rate'] * 100:.1f}% | "
            f"{m['lift']:.2f}x |"
        )
    lines.append("")
    with open(REPORT_OUTPUT, "a") as f:
        f.write("\n".join(lines) + "\n")

    # Detailed confusion-matrix blocks per framing
    for item in results:
        fr = item["framing"]
        m = item["metrics"]
        block = [
            f"### {fr['title']}",
            "",
            "```",
            "Confusion matrix:",
            f"                      {fr['pos_col']:<15} {fr['neg_col']}",
            f"  {fr['flag_row']}     TP={m['tp']:<10} FP={m['fp']}",
            f"  {fr['safe_row']}     FN={m['fn']:<10} TN={m['tn']}",
            "```",
            "",
            f"- Precision: {m['precision'] * 100:.1f}%  |  "
            f"Recall: {m['recall'] * 100:.1f}%  |  "
            f"Accuracy: {m['accuracy'] * 100:.1f}%",
            f"- F1: {m['f1'] * 100:.1f}%  |  "
            f"Specificity: {m['specificity'] * 100:.1f}%  |  "
            f"Base rate ({fr['base_label']}): {m['base_rate'] * 100:.1f}%",
            f"- Lift over base rate: {m['lift']:.2f}x",
            "",
        ]
        with open(REPORT_OUTPUT, "a") as f:
            f.write("\n".join(block) + "\n")


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main():
    """Run the entry timing validation backtest."""
    total_start = time.time()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     ENTRY TIMING CLASSIFIER VALIDATION BACKTEST              ║")
    print("║     Full Halal Universe × 24 Months × 30-day forward        ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    tickers = list(load_halal_universe())
    print(f"\n  Halal universe loaded: {len(tickers)} tickers")
    if not tickers:
        print("ERROR: No tickers loaded from halal universe!")
        sys.exit(1)

    client = RestApiClient(max_concurrent=5)
    print("  API client initialized (max_concurrent=5)")

    try:
        records = await collect_candidates(client, tickers)
    finally:
        await client.close()

    if not records:
        print("\nERROR: No candidates collected! Check API connectivity.")
        sys.exit(1)

    # Default-threshold aggregation + hypothesis
    aggs = aggregate_by_zone(records)
    hyp = evaluate_hypothesis(aggs)

    # Threshold sensitivity sweep
    sweep = run_threshold_sweep(records)

    # Binary-predictor classification metrics (framings A + B)
    classification = run_classification_analysis(records)

    # Console output
    print_zone_table(aggs, len(BACKTEST_DATES), len(tickers))
    print_hypothesis(hyp)
    print_threshold_sweep(sweep)
    print_classification_metrics(classification)

    elapsed = time.time() - total_start
    write_report(aggs, hyp, sweep, len(records), len(tickers), elapsed)
    append_classification_report(classification)

    rec_cut, _ = recommend_threshold(sweep)
    print(f"\n{'═' * 63}")
    print(f"VALIDATION COMPLETE in {elapsed:.1f}s")
    print(f"  Candidates classified: {len(records)}")
    print(f"  Hypothesis: {'PASS ✓' if hyp['passed'] else 'FAIL ✗'}")
    print(f"  Recommended RSI overbought cutoff: {rec_cut:.0f}")


if __name__ == "__main__":
    asyncio.run(main())
