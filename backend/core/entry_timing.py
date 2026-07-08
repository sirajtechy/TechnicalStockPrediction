"""
Entry Timing Classifier

Classifies a stock's entry timing into one of three zones based on how
"extended" or "exhausted" its current move is. This is a SEPARATE signal
layer from the bullish score — it does not change the score or ranking.

The goal: warn the user when a stock is already in the overbought /
profit-taking zone (high risk of buying the top), versus when it still
has room to run (healthy uptrend, not stretched).

Research basis: extended breakouts at new highs with overbought RSI have
a high probability of pulling back to the mean, while stocks in a healthy
uptrend that are not stretched tend to continue with less drawdown risk.

Zones:
  - "buy_zone"   (🟢): uptrend intact, RSI healthy, not extended, room to run
  - "extended"   (🟡): getting stretched, elevated caution
  - "overbought" (🔴): overbought + stretched/at-highs, high profit-taking risk
"""

from dataclasses import dataclass, field

from core.models import TechnicalIndicators


@dataclass
class EntryTiming:
    """Entry timing classification for a stock."""

    zone: str  # "buy_zone" | "extended" | "overbought"
    label: str  # Human-readable label
    reasons: list[str] = field(default_factory=list)  # Why this zone
    # Raw metrics for transparency / UI display
    rsi: float | None = None
    dist_above_sma50_pct: float | None = None
    proximity_to_high: float | None = None
    roc_10: float | None = None


# ─── Thresholds (tunable, backtestable) ──────────────────────────────────────

# RSI zones
# NOTE: Backtested on 212 halal tickers × 24 months (2023-2024). RSI cutoff 65
# gave the cleanest buy_zone vs overbought separation (+0.9% return spread,
# larger drawdown gap) vs 70/75. See docs/ENTRY_TIMING_VALIDATION.md.
RSI_OVERBOUGHT = 65.0        # >= this is overbought territory (tuned from 70)
RSI_EXTREME = 75.0           # >= this is extreme overbought (red on its own)
RSI_ELEVATED = 60.0          # >= this is getting warm
RSI_HEALTHY_LOW = 40.0       # healthy uptrend floor
RSI_HEALTHY_HIGH = 60.0      # healthy uptrend ceiling

# Distance above SMA50 (% extension from the mean)
EXT_STRETCHED = 12.0         # > this % above SMA50 = stretched
EXT_ELEVATED = 8.0           # > this % above SMA50 = getting extended

# Proximity to 20-day high (98+ means basically AT the high)
AT_HIGH = 98.0               # pinned at the high
NEAR_HIGH = 95.0             # very close to high

# Parabolic move (10-day rate of change)
ROC_PARABOLIC = 20.0         # up > 20% in 10 days = parabolic/climactic
ROC_HOT = 12.0               # up > 12% in 10 days = hot


def classify_entry_timing(
    current_price: float,
    indicators: TechnicalIndicators,
) -> EntryTiming:
    """Classify a stock's entry timing into buy_zone / extended / overbought.

    Uses RSI, distance above SMA50, proximity to 20-day high, and 10-day
    rate of change. Missing indicators are handled conservatively (they do
    not by themselves push a stock into the overbought zone).

    Args:
        current_price: Latest closing price.
        indicators: Calculated technical indicators.

    Returns:
        EntryTiming with zone, label, reasons, and raw metrics.
    """
    rsi = indicators.rsi_14
    roc = indicators.roc_10
    prox = indicators.proximity_to_20d_high

    # Distance above SMA50 as a percentage
    dist_above_sma50: float | None = None
    if indicators.sma_50 is not None and indicators.sma_50 > 0:
        dist_above_sma50 = ((current_price - indicators.sma_50) / indicators.sma_50) * 100

    reasons: list[str] = []
    overbought_signals = 0
    extended_signals = 0

    # ── RSI checks ──
    if rsi is not None:
        if rsi >= RSI_EXTREME:
            overbought_signals += 2
            reasons.append(f"RSI {rsi:.0f} is extremely overbought (>= {RSI_EXTREME:.0f})")
        elif rsi >= RSI_OVERBOUGHT:
            overbought_signals += 1
            reasons.append(f"RSI {rsi:.0f} is overbought (>= {RSI_OVERBOUGHT:.0f})")
        elif rsi >= RSI_ELEVATED:
            extended_signals += 1
            reasons.append(f"RSI {rsi:.0f} is elevated")

    # ── Extension above SMA50 ──
    if dist_above_sma50 is not None:
        if dist_above_sma50 > EXT_STRETCHED:
            overbought_signals += 1
            reasons.append(
                f"Price is {dist_above_sma50:.0f}% above its 50-day average (stretched)"
            )
        elif dist_above_sma50 > EXT_ELEVATED:
            extended_signals += 1
            reasons.append(
                f"Price is {dist_above_sma50:.0f}% above its 50-day average"
            )

    # ── Pinned at highs ──
    if prox is not None and prox >= AT_HIGH:
        # At the high is only a red flag when combined with overbought momentum
        if rsi is not None and rsi >= RSI_OVERBOUGHT:
            overbought_signals += 1
            reasons.append("Sitting at its 20-day high while overbought (chase risk)")
        else:
            extended_signals += 1
            reasons.append("Near its 20-day high")

    # ── Parabolic move ──
    if roc is not None:
        if roc > ROC_PARABOLIC:
            overbought_signals += 1
            reasons.append(f"Up {roc:.0f}% in 10 days (parabolic, profit-taking risk)")
        elif roc > ROC_HOT:
            extended_signals += 1
            reasons.append(f"Up {roc:.0f}% in 10 days (hot)")

    # ── Decide zone ──
    if overbought_signals >= 2:
        zone, label = "overbought", "Overbought — Profit-Taking Risk"
    elif overbought_signals == 1:
        zone, label = "extended", "Extended — Caution"
    elif extended_signals >= 2:
        zone, label = "extended", "Extended — Caution"
    else:
        zone, label = "buy_zone", "Buy Zone — Room to Run"
        if not reasons:
            healthy = []
            if rsi is not None and RSI_HEALTHY_LOW <= rsi <= RSI_HEALTHY_HIGH:
                healthy.append(f"RSI {rsi:.0f} in healthy range")
            if dist_above_sma50 is not None and dist_above_sma50 <= EXT_ELEVATED:
                healthy.append("not stretched above its average")
            reasons = healthy or ["Uptrend intact, not overextended"]

    return EntryTiming(
        zone=zone,
        label=label,
        reasons=reasons,
        rsi=round(rsi, 1) if rsi is not None else None,
        dist_above_sma50_pct=round(dist_above_sma50, 1) if dist_above_sma50 is not None else None,
        proximity_to_high=round(prox, 1) if prox is not None else None,
        roc_10=round(roc, 1) if roc is not None else None,
    )
