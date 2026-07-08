"""
Trade Calibration Table

Precomputed probability lookup from backtest data.
Loaded once at startup from data/trade_calibration.json.
Never computed ad hoc at runtime (R7.6).

Score bands:
  - "low": 0–39
  - "mid": 40–69
  - "high": 70–100

ATR bands (ATR as % of price):
  - "tight": ATR ≤ 3% of price
  - "normal": ATR > 3% and ≤ 6% of price
  - "wide": ATR > 6% of price

Bucket ID format: "{score_band}_{atr_band}" (e.g., "high_tight", "mid_normal")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CalibrationRow:
    """One row in the calibration table."""

    bucket_id: str  # e.g., "high_tight"
    sample_size: int
    realized_hit_rate: float
    mean_expectancy_r: float
    prob_hit_target1: float  # The value consumed by build_plan


class CalibrationTable:
    """Precomputed probability lookup from backtest data.

    Loaded once at startup from data/trade_calibration.json.
    Never computed ad hoc at runtime (R7.6).
    """

    def __init__(self, rows: dict[str, CalibrationRow]):
        self._rows = rows

    @classmethod
    def load(cls, path: Path) -> "CalibrationTable":
        """Load calibration data from JSON file.

        Args:
            path: Path to the trade_calibration.json file.

        Returns:
            CalibrationTable instance.

        Raises:
            FileNotFoundError: If calibration file doesn't exist.
            ValueError: If JSON schema is invalid or data is corrupt.
        """
        if not path.exists():
            raise FileNotFoundError(f"Calibration file not found: {path}")

        try:
            with open(path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in calibration file: {e}") from e

        # Validate top-level schema
        if not isinstance(data, dict):
            raise ValueError("Calibration file must contain a JSON object")

        if "version" not in data:
            raise ValueError("Calibration file missing 'version' field")

        if "buckets" not in data:
            raise ValueError("Calibration file missing 'buckets' field")

        buckets_raw = data["buckets"]
        if not isinstance(buckets_raw, dict):
            raise ValueError("'buckets' field must be a JSON object")

        # Parse bucket rows
        rows: dict[str, CalibrationRow] = {}
        for bucket_id, bucket_data in buckets_raw.items():
            if not isinstance(bucket_data, dict):
                raise ValueError(
                    f"Bucket '{bucket_id}' must be a JSON object, got {type(bucket_data).__name__}"
                )

            # Validate required fields
            required_fields = [
                "sample_size",
                "realized_hit_rate",
                "mean_expectancy_r",
                "prob_hit_target1",
            ]
            for field in required_fields:
                if field not in bucket_data:
                    raise ValueError(
                        f"Bucket '{bucket_id}' missing required field '{field}'"
                    )

            try:
                row = CalibrationRow(
                    bucket_id=bucket_id,
                    sample_size=int(bucket_data["sample_size"]),
                    realized_hit_rate=float(bucket_data["realized_hit_rate"]),
                    mean_expectancy_r=float(bucket_data["mean_expectancy_r"]),
                    prob_hit_target1=float(bucket_data["prob_hit_target1"]),
                )
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"Invalid data in bucket '{bucket_id}': {e}"
                ) from e

            rows[bucket_id] = row

        return cls(rows=rows)

    def lookup(self, score: int, atr_pct: float) -> tuple[float | None, bool]:
        """Look up probability for a given setup bucket.

        Args:
            score: Bullish score (0-100).
            atr_pct: ATR as percentage of price.

        Returns:
            (probability, calibration_available) where probability is None
            if bucket not found (caller uses default 0.50).
        """
        bid = self.bucket_id(score, atr_pct)
        row = self._rows.get(bid)
        if row is not None:
            return (row.prob_hit_target1, True)
        return (None, False)

    @staticmethod
    def score_band(score: int) -> str:
        """Classify score into band.

        Returns:
            'low' (0-39), 'mid' (40-69), 'high' (70-100).
        """
        if score <= 39:
            return "low"
        elif score <= 69:
            return "mid"
        else:
            return "high"

    @staticmethod
    def atr_band(atr_pct: float) -> str:
        """Classify ATR percentage into band.

        Args:
            atr_pct: ATR as percentage of price.

        Returns:
            'tight' (≤3%), 'normal' (>3% and ≤6%), 'wide' (>6%).
        """
        if atr_pct <= 3.0:
            return "tight"
        elif atr_pct <= 6.0:
            return "normal"
        else:
            return "wide"

    @staticmethod
    def bucket_id(score: int, atr_pct: float) -> str:
        """Compose bucket identifier from score band and ATR band.

        Args:
            score: Bullish score (0-100).
            atr_pct: ATR as percentage of price.

        Returns:
            Bucket ID string, e.g. "high_tight", "mid_normal".
        """
        return f"{CalibrationTable.score_band(score)}_{CalibrationTable.atr_band(atr_pct)}"
