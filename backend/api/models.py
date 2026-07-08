"""
API Models

Pydantic models for API request and response validation.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    """Request model for initiating a scan."""

    tickers: list[str] = Field(..., min_length=1, description="List of ticker symbols to analyze")
    include_all: bool = Field(
        default=False,
        description="If true, return ALL scanned tickers (candidates + below-threshold + "
        "hard-filter failures) with a status, instead of only buy candidates.",
    )

    class Config:
        json_schema_extra = {"example": {"tickers": ["AAPL", "MSFT", "GOOGL"]}}


class MarketRegime(str, Enum):
    """Market regime classification."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class IndicatorSignals(BaseModel):
    """Individual indicator signals contributing to score."""

    price_above_sma50: bool = Field(description="Current price above 50-day SMA")
    price_above_ema20: bool = Field(description="Current price above 20-day EMA")
    macd_above_signal: bool = Field(description="MACD line above signal line")
    macd_histogram_positive: bool = Field(description="MACD histogram is positive")
    volume_above_average: bool = Field(description="Volume 20% above 20-day average")
    relative_strength_positive: bool = Field(description="Relative strength vs market is positive")

    class Config:
        json_schema_extra = {
            "example": {
                "price_above_sma50": True,
                "price_above_ema20": True,
                "macd_above_signal": True,
                "macd_histogram_positive": True,
                "volume_above_average": False,
                "relative_strength_positive": True,
            }
        }


class TradePlanResponse(BaseModel):
    """Trade plan response model (mirrors TradePlan dataclass)."""

    entry: float = Field(description="Entry price")
    stop: float = Field(description="Stop loss price")
    stop_pct: float = Field(description="Stop loss as percentage from entry (negative)")
    target1: float = Field(description="Primary profit target (2R)")
    target1_pct: float = Field(description="Target1 as percentage gain from entry")
    target2: float = Field(description="Stretch profit target (3R)")
    target2_pct: float = Field(description="Target2 as percentage gain from entry")
    risk_per_share: float = Field(description="Dollar risk per share (entry - stop)")
    reward_risk: float | None = Field(default=None, description="Reward:risk ratio")
    low_rr: bool = Field(description="True if reward_risk below minimum threshold")
    data_unavailable: bool = Field(default=False, description="True if reward_risk cannot be computed")
    expected_move_pct: float | None = Field(default=None, description="1-sigma expected move percentage")
    vol_source: str = Field(description="Volatility source: 'options_iv' or 'historical'")
    resistance: float = Field(description="Nearest overhead resistance price")
    target_above_resistance: bool = Field(description="True if target1 exceeds resistance")
    resistance_data_limited: bool = Field(
        default=False, description="True if < 60 bars for resistance"
    )
    earnings_in_window: str | None = Field(
        default=None, description="Earnings date YYYY-MM-DD if within horizon"
    )
    prob_hit_target1: float | None = Field(
        default=None, description="Calibrated probability 0.0-1.0"
    )
    calibration_available: bool = Field(
        default=False, description="True if calibration bucket found"
    )
    analyst_target: float | None = Field(default=None, description="Analyst mean price target")
    analyst_low: float | None = Field(default=None, description="Analyst lowest price target")
    analyst_high: float | None = Field(default=None, description="Analyst highest price target")


class EntryTimingResponse(BaseModel):
    """Entry timing classification (overbought / extended / buy zone)."""

    zone: str = Field(description="Entry zone: 'buy_zone', 'extended', or 'overbought'")
    label: str = Field(description="Human-readable label for the zone")
    reasons: list[str] = Field(default_factory=list, description="Why the stock is in this zone")
    rsi: float | None = Field(default=None, description="RSI(14) value")
    dist_above_sma50_pct: float | None = Field(
        default=None, description="Percentage distance above the 50-day SMA"
    )
    proximity_to_high: float | None = Field(
        default=None, description="Proximity to 20-day high (98+ = at the high)"
    )
    roc_10: float | None = Field(default=None, description="10-day rate of change (%)")


class TickerScore(BaseModel):
    """Scored ticker with details."""

    ticker: str = Field(description="Stock ticker symbol")
    bullish_score: int = Field(ge=0, le=100, description="Bullish score (0-100)")
    signals: IndicatorSignals = Field(description="Individual indicator signals")
    current_price: float = Field(description="Current stock price")
    indicators: dict[str, float | None] = Field(description="Raw indicator values")
    entry_timing: EntryTimingResponse | None = Field(
        default=None,
        description="Entry timing zone (buy_zone / extended / overbought) — a separate "
        "signal warning of profit-taking risk, does not affect the bullish score",
    )
    # V3 diagnostic fields (populated when include_all is requested)
    passed_hard_filters: bool | None = Field(
        default=None, description="Whether the ticker passed the Minervini hard filters"
    )
    is_candidate: bool | None = Field(
        default=None,
        description="Whether it is a BUY candidate (passed filters AND score >= threshold)",
    )
    score_breakdown: dict[str, int] | None = Field(
        default=None,
        description="Per-component point contributions (trend/momentum/strength/confirmation/"
        "stage_pattern and extension/climax/divergence penalties)",
    )
    trade_plan: TradePlanResponse | None = Field(
        default=None,
        description="Trade plan for BUY candidates (null for non-candidates or plan failure)",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "ticker": "AAPL",
                "bullish_score": 85,
                "signals": {
                    "price_above_sma50": True,
                    "price_above_ema20": True,
                    "macd_above_signal": True,
                    "macd_histogram_positive": True,
                    "volume_above_average": False,
                    "relative_strength_positive": True,
                },
                "current_price": 178.50,
                "indicators": {
                    "sma_50": 175.20,
                    "ema_20": 177.80,
                    "macd_line": 1.25,
                    "macd_signal": 0.95,
                    "macd_histogram": 0.30,
                    "avg_volume_20": 52000000.0,
                    "relative_strength": 2.5,
                },
            }
        }


class ScanMetadata(BaseModel):
    """Metadata about the scan execution."""

    timestamp: datetime = Field(description="Scan execution timestamp")
    ticker_count: int = Field(description="Number of tickers analyzed")
    duration_seconds: float = Field(description="Scan duration in seconds")

    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": "2024-01-15T10:30:00Z",
                "ticker_count": 3,
                "duration_seconds": 2.5,
            }
        }


class ScanResponse(BaseModel):
    """Complete scan results."""

    scan_id: str = Field(description="Unique identifier for this scan")
    market_regime: MarketRegime = Field(description="Current market regime")
    ranked_tickers: list[TickerScore] = Field(description="Tickers ranked by bullish score")
    metadata: ScanMetadata = Field(description="Scan execution metadata")
    score_threshold: int | None = Field(
        default=None, description="BUY score threshold for this regime (65 bullish / 75 neutral)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "scan_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "market_regime": "bullish",
                "ranked_tickers": [
                    {
                        "ticker": "AAPL",
                        "bullish_score": 85,
                        "signals": {
                            "price_above_sma50": True,
                            "price_above_ema20": True,
                            "macd_above_signal": True,
                            "macd_histogram_positive": True,
                            "volume_above_average": False,
                            "relative_strength_positive": True,
                        },
                        "current_price": 178.50,
                        "indicators": {
                            "sma_50": 175.20,
                            "ema_20": 177.80,
                            "macd_line": 1.25,
                            "macd_signal": 0.95,
                            "macd_histogram": 0.30,
                            "avg_volume_20": 52000000.0,
                            "relative_strength": 2.5,
                        },
                    }
                ],
                "metadata": {
                    "timestamp": "2024-01-15T10:30:00Z",
                    "ticker_count": 3,
                    "duration_seconds": 2.5,
                },
            }
        }


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="Service health status")

    class Config:
        json_schema_extra = {"example": {"status": "healthy"}}


class HalalUniverseResponse(BaseModel):
    """The full curated halal stock universe."""

    tickers: list[str] = Field(description="Deduplicated list of halal ticker symbols")
    count: int = Field(description="Number of tickers")

    class Config:
        json_schema_extra = {"example": {"tickers": ["AAPL", "MSFT", "NVDA"], "count": 3}}
