"""
Stock Intelligence API.

GET /api/v1/intelligence/{ticker} — returns the full intelligence bundle for one
ticker (news+sentiment, insider trades, short interest, dividends, macro, analyst
target, earnings, fundamentals). Fetched on demand (not per scan) to bound API cost.
Every section degrades gracefully; unavailable sections are listed in `unavailable`.
"""

from fastapi import APIRouter

from config import config
from core.massive_client import MassiveDataClient
from core.stock_intelligence import gather_intelligence
from utils.logging import get_logger

logger = get_logger(__name__)
intel_router = APIRouter()


def _client() -> MassiveDataClient:
    """Build a MassiveDataClient from config (same auth as the aggregates client)."""
    return MassiveDataClient(api_key=config.POLYGON_TOKEN, base_url=config.API_BASE_URL)


@intel_router.get("/intelligence/{ticker}", tags=["intelligence"])
async def stock_intelligence(ticker: str) -> dict:
    """
    Return the intelligence bundle for a single ticker.

    Args:
        ticker: Stock symbol (case-insensitive).

    Returns:
        Intelligence dict (see core.stock_intelligence.gather_intelligence).
        Always HTTP 200 — individual sections degrade to null/empty rather than error.
    """
    ticker = ticker.strip().upper()
    logger.info(f"Intelligence requested for {ticker}")
    client = _client()
    try:
        return await gather_intelligence(client, ticker)
    finally:
        await client.close()
