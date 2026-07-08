# Entry Timing Classifier Validation

Generated: 2026-07-05 14:47 UTC

## Overview

- **Universe**: 212 halal tickers (full universe)
- **Scan dates**: 24 monthly (2023-01-03 to 2024-12-02)
- **Candidates classified**: 2400 (passed price > SMA50 AND price > SMA200)
- **Forward horizon**: 30 trading bars
- **Runtime**: 2081.6s

## Hypothesis

> buy_zone stocks have HIGHER forward returns and LOWER (less negative) drawdown than overbought stocks over the next 30 trading days.

## Zone Performance (30-day forward)

| Zone | N | Mean Ret | Median | Max DD | % Positive |
|------|---|----------|--------|--------|------------|
| buy_zone | 1345 | +1.9% | +1.1% | -6.8% | 54% |
| extended | 648 | +0.4% | +0.1% | -8.1% | 51% |
| overbought | 407 | +0.9% | +1.3% | -6.8% | 57% |

## Hypothesis Result

- **Return spread** (buy_zone − overbought): **+0.9%** — PASS
- **Drawdown** (buy_zone -6.8% vs overbought -6.8%): PASS (buy_zone drawdown should be less negative)
- **Monotonic ordering** (buy_zone > extended > overbought): FAIL

### Overall: ✅ PASS

## Threshold Sensitivity (RSI overbought cutoff)

| RSI cutoff | buy_zone N / Ret | extended N / Ret | overbought N / Ret | bz−ob spread |
|-----------|------------------|------------------|--------------------|--------------|
| 65 | 1345 / +1.9% | 648 / +0.4% | 407 / +0.9% | +0.9% |
| 70 | 1371 / +1.9% | 812 / +0.3% | 217 / +1.4% | +0.5% |
| 75 | 1380 / +1.9% | 906 / +0.4% | 114 / +1.7% | +0.2% |

## Threshold Recommendation

**Recommended RSI overbought cutoff: 65**

Rationale: largest buy_zone−overbought spread (+0.9%) with adequate sample. A larger buy_zone−overbought return spread means the classifier separates healthy entries from exhausted ones more cleanly. The current default is 70.

## Methodology

1. Load full halal universe.
2. For each monthly scan date, fetch 400 calendar days of history per ticker.
3. Fetch SPY once per date for relative strength; reuse across tickers.
4. Compute indicators (RSI14, SMA50/200, ROC10, proximity to 20d high).
5. Keep only uptrend candidates: price > SMA50 AND price > SMA200.
6. Classify the entry zone at the scan date.
7. Fetch 45 calendar days forward; measure outcomes over the next 30 trading bars.
8. Aggregate by zone; evaluate the hypothesis; sweep RSI cutoffs 65/70/75.

Notes: forward return uses the close of the last bar within the 30-bar window; max drawdown is the lowest low vs entry (the key profit-taking risk metric).

## Classification Metrics

Treats the entry-timing classifier as a binary predictor under two framings. Predicted-positive = the classifier raised a caution flag; actual-positive = the bad outcome actually occurred.

| Framing | TP | FP | FN | TN | Precision | Recall | Accuracy | F1 | Specificity | Base rate | Lift |
|---------|----|----|----|----|-----------|--------|----------|----|-------------|-----------|------|
| FRAMING A1: "overbought flags a LOSING trade" | 175 | 232 | 933 | 1060 | 43.0% | 15.8% | 51.5% | 23.1% | 82.0% | 46.2% | 0.93x |
| FRAMING A2: "extended OR overbought flags a LOSING trade" | 495 | 560 | 613 | 732 | 46.9% | 44.7% | 51.1% | 45.8% | 56.7% | 46.2% | 1.02x |
| FRAMING B: "not-buy_zone flags a >=10% drawdown" | 294 | 761 | 311 | 1034 | 27.9% | 48.6% | 55.3% | 35.4% | 57.6% | 25.2% | 1.11x |
| FRAMING B (15%): "not-buy_zone flags a >=15% drawdown" | 139 | 916 | 131 | 1214 | 13.2% | 51.5% | 56.4% | 21.0% | 57.0% | 11.2% | 1.17x |

### FRAMING A1: "overbought flags a LOSING trade"

```
Confusion matrix:
                      Actual Loser    Actual Winner
  Overbought        TP=175        FP=232
  Not overbought     FN=933        TN=1060
```

- Precision: 43.0%  |  Recall: 15.8%  |  Accuracy: 51.5%
- F1: 23.1%  |  Specificity: 82.0%  |  Base rate (losers): 46.2%
- Lift over base rate: 0.93x

### FRAMING A2: "extended OR overbought flags a LOSING trade"

```
Confusion matrix:
                      Actual Loser    Actual Winner
  Ext/Overbought     TP=495        FP=560
  Buy zone          FN=613        TN=732
```

- Precision: 46.9%  |  Recall: 44.7%  |  Accuracy: 51.1%
- F1: 45.8%  |  Specificity: 56.7%  |  Base rate (losers): 46.2%
- Lift over base rate: 1.02x

### FRAMING B: "not-buy_zone flags a >=10% drawdown"

```
Confusion matrix:
                      Actual DD>=10%  Actual DD<10%
  Flagged (risky)     TP=294        FP=761
  Buy zone (safe)     FN=311        TN=1034
```

- Precision: 27.9%  |  Recall: 48.6%  |  Accuracy: 55.3%
- F1: 35.4%  |  Specificity: 57.6%  |  Base rate (DD>=10%): 25.2%
- Lift over base rate: 1.11x

### FRAMING B (15%): "not-buy_zone flags a >=15% drawdown"

```
Confusion matrix:
                      Actual DD>=15%  Actual DD<15%
  Flagged (risky)     TP=139        FP=916
  Buy zone (safe)     FN=131        TN=1214
```

- Precision: 13.2%  |  Recall: 51.5%  |  Accuracy: 56.4%
- F1: 21.0%  |  Specificity: 57.0%  |  Base rate (DD>=15%): 11.2%
- Lift over base rate: 1.17x

