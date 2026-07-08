# Trade Engine Comprehensive Backtest Results

Generated: 2026-07-01 08:20 UTC

## Overview

- **Universe**: 212 halal tickers (full universe)
- **Scan dates**: 24 monthly dates (2023-01-03 to 2024-12-02)
- **Raw candidates evaluated**: 2400
- **Parameter grid**: 5×5 = 25 combinations
- **Temporal split**: 70% in-sample / 30% out-of-sample

## Best Operating Point

| Metric | Value |
|--------|-------|
| ATR Multiplier | 3.0 |
| Target1 Multiplier | 1.0 |
| Total Trades | 2400 |
| Resolved | 2048 |
| Overall Hit Rate | 53.1% |
| Overall Expectancy | +0.0525R |
| IS Hit Rate | 50.4% |
| IS Expectancy | +0.0071R |
| OOS Hit Rate | 59.2% |
| OOS Expectancy | +0.1583R |

## Full Parameter Sweep Results

| ATR | T1 | Trades | Resolved | Hit Rate | Expectancy |
|-----|-----|--------|----------|----------|------------|
| 3.0 | 1.0 | 2400 | 2048 | 53.1% | +0.0525R |
| 2.5 | 1.0 | 2400 | 2220 | 52.8% | +0.0508R |
| 2.5 | 1.5 | 2400 | 2000 | 42.0% | +0.0417R |
| 2.0 | 1.5 | 2400 | 2230 | 41.6% | +0.0375R |
| 2.0 | 2.0 | 2400 | 2067 | 34.1% | +0.0187R |
| 1.0 | 3.0 | 2400 | 2356 | 25.5% | +0.0183R |
| 2.0 | 1.0 | 2400 | 2344 | 50.9% | +0.0175R |
| 3.0 | 1.5 | 2400 | 1731 | 40.6% | +0.0100R |
| 1.0 | 2.5 | 2400 | 2376 | 28.8% | +0.0090R |
| 1.5 | 2.5 | 2400 | 2223 | 28.6% | +0.0027R |
| 1.5 | 2.0 | 2400 | 2310 | 33.4% | +0.0025R |
| 1.5 | 1.5 | 2400 | 2363 | 39.5% | -0.0127R |
| 2.5 | 2.0 | 2400 | 1784 | 32.5% | -0.0183R |
| 2.0 | 2.5 | 2400 | 1932 | 27.8% | -0.0219R |
| 1.0 | 2.0 | 2400 | 2393 | 32.3% | -0.0321R |
| 1.5 | 3.0 | 2400 | 2132 | 23.9% | -0.0383R |
| 1.5 | 1.0 | 2400 | 2394 | 48.0% | -0.0392R |
| 3.0 | 2.0 | 2400 | 1500 | 30.0% | -0.0625R |
| 1.0 | 1.5 | 2400 | 2398 | 37.2% | -0.0700R |
| 2.0 | 3.0 | 2400 | 1804 | 22.3% | -0.0817R |
| 1.0 | 1.0 | 2400 | 2400 | 45.4% | -0.0925R |
| 2.5 | 2.5 | 2400 | 1604 | 24.6% | -0.0938R |
| 3.0 | 2.5 | 2400 | 1330 | 20.6% | -0.1546R |
| 2.5 | 3.0 | 2400 | 1475 | 17.6% | -0.1812R |
| 3.0 | 3.0 | 2400 | 1224 | 13.6% | -0.2317R |

## Calibration Buckets

| Bucket | N | Resolved | Hit Rate | Expectancy |
|--------|---|----------|----------|------------|
| high_normal | 291 | 235 | 53.2% | +0.052R |
| high_tight | 1023 | 880 | 54.0% | +0.068R |
| high_wide | 17 | 17 | 29.4% | -0.412R |
| mid_normal | 156 | 141 | 54.6% | +0.083R |
| mid_tight | 897 | 759 | 52.4% | +0.041R |
| mid_wide | 16 | 16 | 43.8% | -0.125R |

## Methodology

1. Load full halal universe (212 tickers)
2. For each of 24 monthly dates, fetch 400 calendar days of history
3. Identify BUY candidates: price > SMA(50) AND price > SMA(200)
4. Score candidates using simplified Minervini proxy
5. For each candidate, fetch 55 calendar days forward data
6. Sweep 25 parameter combinations (ATR mult × Target1 mult)
7. Evaluate first-touch: stop or target1 hit within 30 bars
8. 70/30 temporal split for in-sample vs out-of-sample
9. Select best point: highest hit rate with positive IS+OOS expectancy
10. Compute per-bucket probabilities for calibration table

## Notes

- Undecided trades (neither stop nor target hit in 30 bars) counted as 0R in expectancy
- Breakeven rate = 1 / (1 + target1_mult)
- All data from Polygon.io premium API (adjusted prices, sorted asc)
