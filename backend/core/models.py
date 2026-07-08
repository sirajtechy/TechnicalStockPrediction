"""
Internal Data Models

Data classes for internal use by core components.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class StockData:
    """Raw stock data from API."""

    ticker: str
    prices: np.ndarray  # Close prices
    volumes: np.ndarray
    timestamps: np.ndarray
    highs: np.ndarray = None  # High prices (float64)
    lows: np.ndarray = None  # Low prices (float64)

    def __post_init__(self):
        """Default highs/lows to empty arrays if not provided (backward compat)."""
        if self.highs is None:
            self.highs = np.empty(0, dtype=np.float64)
        if self.lows is None:
            self.lows = np.empty(0, dtype=np.float64)


@dataclass
class TechnicalIndicators:
    """Calculated technical indicators."""

    sma_50: float | None = None
    sma_150: float | None = None  # V3: Minervini hard filter H3
    sma_200: float | None = None  # V3: Minervini hard filters H1/H4
    sma_200_slope: float | None = None  # V3: H2 (rising 200-day SMA over last 20 bars)
    week52_high: float | None = None  # V3: H6 (within 25% of 52-week high)
    week52_low: float | None = None  # V3: H5 (30% above 52-week low)
    ema_20: float | None = None
    ema_9: float | None = None
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    avg_volume_20: float | None = None
    relative_strength: float | None = None
    rsi_14: float | None = None
    roc_10: float | None = None
    proximity_to_20d_high: float | None = None
