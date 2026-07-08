# Trade Engine Backtest Results

Generated: 2026-07-01 02:30 UTC

## Summary

- **Status**: FAIL - See failures below
- **Total trades**: 219
- **Resolved**: 191 (target: 90, stop: 101)
- **Undecided**: 28
- **Hit rate**: 47.1%
- **Expectancy**: +0.361R
- **Sample period**: 2023-03-01 to 2025-01-02
- **Tickers**: 30
- **Scan dates**: 12

## Temporal Split (70/30)

| Period | Trades | Resolved | Hit Rate | Expectancy |
|--------|--------|----------|----------|------------|
| In-sample | 153 | 133 | 48.1% | +0.386R |
| Out-of-sample | 66 | 58 | 44.8% | +0.303R |

## Parameter Sweep

| ATR Mult | T1 Mult | Trades | Expectancy | Hit Rate |
|----------|---------|--------|------------|----------|
| 1.5 | 2.5 | 153 | +0.4739R | 44.0% |
| 2.0 | 2.0 | 153 | +0.4314R | 51.2% |
| 2.5 | 1.5 | 153 | +0.4183R | 62.1% |
| 1.5 | 2.0 | 153 | +0.4118R | 48.2% |
| 1.5 | 3.0 | 153 | +0.4052R | 37.7% |
| 2.0 | 1.5 | 153 | +0.3824R | 57.5% |
| 3.0 | 1.5 | 153 | +0.3431R | 62.1% |
| 2.5 | 2.0 | 153 | +0.3399R | 51.6% |
| 2.0 | 2.5 | 153 | +0.3366R | 42.4% |
| 2.0 | 3.0 | 153 | +0.3268R | 37.8% |
| 1.5 | 1.5 | 153 | +0.3137R | 53.1% |
| 3.0 | 2.0 | 153 | +0.3137R | 53.8% |
| 2.5 | 2.5 | 153 | +0.2876R | 43.9% |
| 3.0 | 2.5 | 153 | +0.2222R | 43.8% |
| 2.5 | 3.0 | 153 | +0.1699R | 34.3% |
| 3.0 | 3.0 | 153 | +0.0980R | 32.1% |

**Best operating point**: ATR=1.5, T1=2.5 (IS expectancy: +0.4739R)
**OOS expectancy**: +0.2803R

## Earnings-Window Validation

- Earnings subset: 85 trades
- No-earnings subset: 134 trades
- Earnings variance: 0.013357
- No-earnings variance: 0.012783
- Variance ratio: 1.0449 (required: >= 1.2)
- Status: **FAIL**

## Calibration Buckets

| Bucket | Sample | Resolved | Hit Rate | Expectancy |
|--------|--------|----------|----------|------------|
| high_normal | 24 | 17 | 41.2% | +0.167R |
| high_tight | 155 | 139 | 46.8% | +0.361R |
| mid_normal | 8 | 7 | 85.7% | +1.375R |
| mid_tight | 32 | 28 | 42.9% | +0.250R |

## Failures

- **FAIL**: Earnings variance ratio 1.0449 < required 1.2
