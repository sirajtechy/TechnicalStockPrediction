"""
Stock Intelligence aggregator.

Fetches the full "intelligence" bundle for one ticker from the MassiveDataClient —
news+sentiment, insider trades, short interest, dividends, macro, analyst target,
earnings, and fundamentals — concurrently, and assembles a single dict for the API.

Every section degrades independently: a failed/unentitled section is set to None and
its name added to ``unavailable`` (rather than fabricating a value). List sections that
are entitled-but-empty stay ``[]`` and are NOT marked unavailable. Sections run
concurrently and a per-section failure can't break the bundle; a whole-bundle deadline
bounds total latency so one slow feed can't hang the request.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from core.massive_client import MassiveDataClient

logger = logging.getLogger(__name__)

# Whole-bundle deadline (seconds). Bounds total latency even if a section's own
# retries would otherwise run long; on timeout, unfinished sections degrade to None.
GATHER_DEADLINE_SECONDS = 12.0


async def gather_intelligence(client: MassiveDataClient, ticker: str) -> dict:
    """
    Concurrently fetch every intelligence section for ``ticker``.

    Returns a dict:
        {
          "ticker", "generated_utc",
          "news": [...], "insider_trades": [...], "short_interest": {...}|None,
          "dividends": [...], "macro": {...}|None,
          "analyst": {...}|None, "earnings": [...], "fundamentals": {...}|None,
          "unavailable": ["analyst", "earnings", ...]   # sections that returned None
        }
    A section is None ⇒ the fetch was unavailable (403/error) and its name is added
    to ``unavailable`` so the UI can show "requires plan / unavailable" rather than a
    fake value.
    """
    now = datetime.now(timezone.utc)
    fwd = (now + timedelta(days=90)).strftime("%Y-%m-%d")
    back = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    async def _safe(coro):
        # A section must never break the bundle: any error OR a whole-bundle
        # timeout degrades that section to None (→ listed in `unavailable`).
        try:
            return await asyncio.wait_for(coro, timeout=GATHER_DEADLINE_SECONDS)
        except (Exception, asyncio.TimeoutError) as e:
            logger.warning("Intelligence section failed for %s: %s", ticker, e)
            return None

    (
        news,
        insider,
        short,
        short_volume,
        dividends,
        macro,
        analyst,
        analyst_insights,
        earnings,
        fundamentals,
    ) = await asyncio.gather(
        _safe(client.get_news(ticker)),
        _safe(client.get_insider_trades(ticker)),
        _safe(client.get_short_interest(ticker)),
        _safe(client.get_short_volume(ticker)),
        _safe(client.get_dividends(ticker)),
        _safe(client.get_macro()),
        _safe(client.get_analyst_consensus(ticker)),
        _safe(client.get_analyst_insights(ticker)),
        _safe(client.get_earnings(ticker, back, fwd)),
        _safe(client.get_fundamentals(ticker)),
    )

    sections = {
        "news": news,
        "insider_trades": insider,
        "short_interest": short,
        "short_volume": short_volume,
        "dividends": dividends,
        "macro": macro,
        "analyst": analyst,
        "analyst_insights": analyst_insights,
        "earnings": earnings,
        "fundamentals": fundamentals,
    }
    unavailable = [name for name, value in sections.items() if value is None]

    return {
        "ticker": ticker.upper(),
        "generated_utc": now.isoformat(),
        # Normalise None → [] for list sections so the UI iterates safely.
        "news": news or [],
        "insider_trades": insider or [],
        "short_interest": short,
        "short_volume": short_volume,
        "dividends": dividends or [],
        "macro": macro,
        "analyst": analyst,
        "analyst_insights": analyst_insights or [],
        "earnings": earnings or [],
        "fundamentals": fundamentals,
        "unavailable": unavailable,
    }
