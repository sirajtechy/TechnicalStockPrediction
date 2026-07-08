# Product Overview

## Bullish Stock Scanner + Trade Engine

A full-stack application for identifying potentially bullish stocks through technical analysis and generating actionable trade plans. The system combines a Python FastAPI backend with a React frontend to provide analysis based on Minervini-style trend template scoring, market regime detection, and risk-defined trade planning.

## Purpose

Analyze technical indicators and chart patterns to identify stocks with bullish potential, then produce concrete trade plans with entry, stop, targets, and calibrated probability. The system provides:

- **Automated Scanning**: Batch analysis of a curated halal stock universe
- **Market Context**: SPY-based regime classification (bullish/neutral/bearish) with regime-adaptive thresholds
- **Quantified Signals**: Gradient-based 100-point scoring with Minervini hard filters
- **Trade Plans**: Volatility-based stops, R-multiple targets, expected moves, earnings warnings (in development)
- **Ranked Results**: Stocks sorted by bullish score with expandable per-ticker detail
- **Backtesting**: Walk-forward validation with confusion matrix and expectancy tracking

## Core Features (Built)

### V3 Technical Analysis
- **Minervini Hard Filters (H1-H6)**: Price vs SMA200/150/50, golden cross, 52-week range
- **Gradient Scoring (5 components, max 100 pts)**: Trend position, momentum, strength, confirmation, stage/pattern bonus
- **Penalties**: Extension (-25), climax/exhaustion (-12), indicator divergence (-8)
- **Stage 2 Classification**: Weinstein stage detection for bonus scoring
- **Pattern Detection**: Cup-with-handle and other chart patterns
- **Market Regime**: SPY-based bullish/bearish/neutral with persistence (5 consecutive days)
- **Regime-Adaptive Thresholds**: 65 (bullish) / 75 (neutral) / no signals (bearish)
- **Relative Strength Percentile**: Cross-universe RS ranking (not just raw RS)

### Backtesting Framework (Built)
- Walk-forward backtest engine with point-in-time data (no look-ahead)
- Confusion matrix: TP/FP/FN/TN with precision/recall
- Multi-date validation across 5+ dates
- Scripts: `validate_v3.py`, `tune_v3.py`, `analyze_fp.py`
- Trade plan prototype validated: +0.27R/trade, 41% target-before-stop on 2:1

### User Experience (Built)
- **Web Interface**: React UI with Cloudscape Design System
- **REST API**: FastAPI with Swagger docs at `/docs`
- **Scan Report**: Downloadable HTML report with full breakdown
- **Include All Mode**: See all tickers (candidates + filtered + below-threshold)

## Trade Engine (Next Phase — Spec Complete)

For each BUY candidate, produce a risk-defined equity trade plan:
- ATR-based volatility stop (configurable, default 2x ATR with 10% max loss cap)
- R-multiple profit targets (2R primary, 3R stretch)
- 30-day expected move (historical σ or options IV)
- Resistance annotation (60-day high / 52-week high)
- Reward:risk quality gate (min 1.5)
- Earnings-in-window warning with target widening
- Calibrated hit probability from backtest data
- Analyst consensus anchor (optional external reference)

## Target Users

1. **Swing Traders**: Minervini-style trend following with 30-day horizon
2. **Halal Investors**: Pre-curated Shariah-compliant stock universe
3. **Systematic Traders**: Data-driven scoring with no subjective calls
4. **Developers**: API access for integration with trading systems

## Technical Approach

### Architecture
- **Backend**: Python 3.10+ with FastAPI, async everywhere
- **Frontend**: React 18+ with TypeScript and Cloudscape Design System
- **Data**: Polygon.io (Massive) API with premium pro plan
- **Testing**: pytest + hypothesis (property-based), vitest, Playwright e2e
- **Backtesting**: Walk-forward with temporal in-sample/out-of-sample splits

### Key Design Decisions

1. **Minervini Hard Filters First**: Binary gate before scoring (eliminates 80%+ of universe)
2. **Gradient Scoring over Binary**: Partial credit for proximity to signals
3. **Penalties over Caps**: Extension/climax penalties reduce score rather than hard-capping
4. **Calibration-Gated**: No probability claims reach UI without backtest validation
5. **Graceful Degradation**: Enhancement data (earnings, IV, analyst) falls back silently
6. **Two-Pass Pipeline**: RS percentile requires all raw RS values before scoring
7. **Point-in-Time Data**: Backtests use `as_of_date` to prevent look-ahead bias

## Success Criteria

### Scanner (Met)
- V3 scoring validated: precision ~70%+ at score threshold 70
- False negatives minimized through gradient scoring
- Backtest across 5 dates × halal universe confirms edge

### Trade Engine (Target)
- Positive expectancy (> 0R) on in-sample AND out-of-sample
- Probability claims calibrated within ±5pp per bucket
- Earnings-in-window correctly captures elevated variance
- Every number reproducible from data

## Out of Scope
- Options/futures trading (equity only; options data used for IV input)
- Real-money order placement
- Position sizing by account equity
- Intraday/stop-trailing management
- Machine learning models

## License

Apache License 2.0
