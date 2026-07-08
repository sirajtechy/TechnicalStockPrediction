"""
Configuration Management

Reads configuration from environment variables with sensible defaults.
POLYGON_TOKEN is already set globally in the system shell (no .env file required).
"""

import os


class Config:
    """Application configuration."""

    # API Configuration
    POLYGON_TOKEN: str = os.getenv("POLYGON_TOKEN", "")
    API_BASE_URL: str = os.getenv("API_BASE_URL", "https://api.polygon.io")

    # Server Configuration
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))

    # Logging Configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # API Client Configuration
    MAX_CONCURRENT_REQUESTS: int = 5
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_FACTOR: float = 2.0  # Exponential backoff: 1s, 2s, 4s

    # History window (V3): fetch_stock_data `days` is CALENDAR days. Empirically 365
    # calendar days yields only ~250 trading bars — 2 short of the 252 needed for
    # 52-week high/low. 400 calendar days yields ~274 trading bars, comfortably above
    # the 252 minimum so SMA(200), the 20-bar SMA200 slope, and 52-week high/low are
    # all computable for the Minervini hard filters.
    HISTORY_FETCH_DAYS: int = 400
    MIN_TRADING_BARS: int = 252

    # V3 regime-based BUY thresholds (R1/R7)
    BULLISH_SCORE_THRESHOLD: int = 65
    NEUTRAL_SCORE_THRESHOLD: int = 75
    REGIME_PERSISTENCE_DAYS: int = 5  # consecutive closes above/below SMA200

    # Database Configuration
    DB_PATH: str = os.getenv("DB_PATH", "scanner.db")

    # ─── Trade Engine Configuration ───────────────────────────────────────
    # ATR Stop
    TRADE_ATR_MULT: float = 3.0              # Range: 1.0–5.0 (backtested: best IS+OOS with T1=1.0)
    TRADE_MAX_LOSS_PCT: float = 0.10         # Range: 0.01–0.25 (stored positive, applied as negative)

    # R-Multiple Targets
    TRADE_TARGET1_MULT: float = 1.0          # Must be > 0 (backtested: 53% hit rate, +0.05R expectancy)
    TRADE_TARGET2_MULT: float = 2.0          # Must be > TARGET1_MULT

    # Expected Move
    TRADE_HORIZON_DAYS: int = 21             # Range: 1–63 trading days
    TRADE_SIGMA_LOOKBACK: int = 20           # Min daily returns for historical σ

    # Reward:Risk
    TRADE_MIN_REWARD_RISK: float = 1.5       # Range: 0.5–10.0

    # Earnings
    TRADE_EARNINGS_WIDEN_FACTOR: float = 1.5           # Range: 1.0–3.0
    TRADE_EARNINGS_CONFIDENCE_DISCOUNT: float = 0.8    # Range: 0.5–1.0

    # Resistance
    TRADE_RESISTANCE_LOOKBACK: int = 60      # Days for swing high

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.POLYGON_TOKEN:
            raise ValueError(
                "POLYGON_TOKEN environment variable is required. "
                "It should be set globally in your shell configuration."
            )

        # Trade Engine validation
        if cls.TRADE_TARGET1_MULT >= cls.TRADE_TARGET2_MULT:
            raise ValueError(
                f"TRADE_TARGET1_MULT ({cls.TRADE_TARGET1_MULT}) must be less than "
                f"TRADE_TARGET2_MULT ({cls.TRADE_TARGET2_MULT})"
            )

        if not (1.0 <= cls.TRADE_ATR_MULT <= 5.0):
            raise ValueError(
                f"TRADE_ATR_MULT ({cls.TRADE_ATR_MULT}) must be in range 1.0–5.0"
            )

        if not (0.01 <= cls.TRADE_MAX_LOSS_PCT <= 0.25):
            raise ValueError(
                f"TRADE_MAX_LOSS_PCT ({cls.TRADE_MAX_LOSS_PCT}) must be in range 0.01–0.25"
            )

        if cls.TRADE_TARGET1_MULT <= 0:
            raise ValueError(
                f"TRADE_TARGET1_MULT ({cls.TRADE_TARGET1_MULT}) must be greater than 0"
            )

        if not (1 <= cls.TRADE_HORIZON_DAYS <= 63):
            raise ValueError(
                f"TRADE_HORIZON_DAYS ({cls.TRADE_HORIZON_DAYS}) must be in range 1–63"
            )

        if not (0.5 <= cls.TRADE_MIN_REWARD_RISK <= 10.0):
            raise ValueError(
                f"TRADE_MIN_REWARD_RISK ({cls.TRADE_MIN_REWARD_RISK}) must be in range 0.5–10.0"
            )

        if not (1.0 <= cls.TRADE_EARNINGS_WIDEN_FACTOR <= 3.0):
            raise ValueError(
                f"TRADE_EARNINGS_WIDEN_FACTOR ({cls.TRADE_EARNINGS_WIDEN_FACTOR}) must be in range 1.0–3.0"
            )

        if not (0.5 <= cls.TRADE_EARNINGS_CONFIDENCE_DISCOUNT <= 1.0):
            raise ValueError(
                f"TRADE_EARNINGS_CONFIDENCE_DISCOUNT ({cls.TRADE_EARNINGS_CONFIDENCE_DISCOUNT}) must be in range 0.5–1.0"
            )


# Create global config instance
config = Config()
