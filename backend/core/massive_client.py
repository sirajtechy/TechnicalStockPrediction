"""
Massive Data Client

Thin async HTTP client for non-aggregate Massive (Polygon) REST endpoints:
- Earnings calendar (Benzinga)
- Options chain snapshot (implied volatility)
- Analyst consensus ratings (Benzinga)

Authenticates with the same POLYGON_TOKEN as RestApiClient (apiKey query param).
Implements retry with exponential backoff for 5xx/network errors.
All methods return None on failure (graceful degradation).
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class MassiveDataClient:
    """Async client for Massive REST endpoints (earnings, options, analyst).

    Authenticates with the same POLYGON_TOKEN as RestApiClient.
    Implements retry with exponential backoff for 5xx/network errors.
    All methods return None on failure (graceful degradation).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.polygon.io",
        timeout: float = 10.0,
        max_concurrent: int = 5,
        max_retries: int = 3,
    ):
        """
        Initialize Massive Data Client.

        Args:
            api_key: POLYGON_TOKEN for authentication (passed as apiKey param)
            base_url: Base URL for Massive/Polygon API
            timeout: Per-request timeout in seconds (default: 10)
            max_concurrent: Maximum concurrent connections (default: 5)
            max_retries: Maximum retry attempts (default: 3)
        """
        limits = httpx.Limits(
            max_connections=max_concurrent,
            max_keepalive_connections=max_concurrent,
        )
        self.client = httpx.AsyncClient(limits=limits, timeout=timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries

    async def _request_with_retry(
        self, endpoint: str, params: dict, ticker: str
    ) -> httpx.Response | None:
        """Execute GET request with exponential backoff retry for 5xx/network errors.

        Retry logic:
        - Max 3 attempts
        - Exponential backoff: 1s, 2s, 4s delays
        - Retry on: network errors (httpx.RequestError), 5xx status codes
        - No retry on: 4xx client errors

        Args:
            endpoint: API endpoint path (e.g., /benzinga/v1/earnings)
            params: Query parameters dict
            ticker: Ticker symbol for logging context

        Returns:
            httpx.Response on success, None on failure
        """
        url = f"{self.base_url}{endpoint}"
        params["apiKey"] = self.api_key

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self.client.get(url, params=params)

                # 4xx: no retry, log and return None immediately
                if 400 <= response.status_code < 500:
                    try:
                        logger.error(
                            f"Client error {response.status_code} for {endpoint} "
                            f"(ticker={ticker})"
                        )
                    except Exception:
                        pass
                    return None

                # 5xx: retry with backoff
                if response.status_code >= 500:
                    try:
                        logger.warning(
                            f"Server error {response.status_code} for {endpoint} "
                            f"(ticker={ticker}, attempt {attempt}/{self.max_retries})"
                        )
                    except Exception:
                        pass
                    if attempt < self.max_retries:
                        delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                        await asyncio.sleep(delay)
                        continue
                    return None

                # Success (2xx/3xx)
                return response

            except httpx.RequestError as e:
                # Network error: retry with backoff
                try:
                    logger.warning(
                        f"Network error for {endpoint} (ticker={ticker}, "
                        f"attempt {attempt}/{self.max_retries}): {e}"
                    )
                except Exception:
                    pass
                if attempt < self.max_retries:
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    await asyncio.sleep(delay)
                    continue
                return None

            except Exception as e:
                # Unexpected error: no retry
                try:
                    logger.error(f"Unexpected error for {endpoint} (ticker={ticker}): {e}")
                except Exception:
                    pass
                return None

        return None

    async def get_earnings(self, ticker: str, from_date: str, to_date: str) -> list[dict] | None:
        """Fetch earnings dates within range.

        GET /benzinga/v1/earnings?ticker={ticker}&date.gte={from}&date.lte={to}&apiKey=...

        Args:
            ticker: Stock symbol (e.g., "AAPL")
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)

        Returns:
            List of earnings dicts with 'date' field, or None on error
        """
        try:
            endpoint = "/benzinga/v1/earnings"
            params = {
                "ticker": ticker,
                "date.gte": from_date,
                "date.lte": to_date,
            }

            response = await self._request_with_retry(endpoint, params, ticker)
            if response is None:
                return None

            data = response.json()

            # The API returns a list of earnings objects
            if isinstance(data, list):
                return data
            # Some responses wrap in a results/earnings key
            if isinstance(data, dict):
                if "earnings" in data:
                    return data["earnings"]
                if "results" in data:
                    return data["results"]
                # Empty response
                return []

            return []

        except Exception as e:
            try:
                logger.error(f"Error parsing earnings response for {ticker}: {e}")
            except Exception:
                pass
            return None

    async def get_options_iv(
        self,
        ticker: str,
        entry_price: float,
        from_expiry: str,
        to_expiry: str,
    ) -> float | None:
        """Fetch ATM implied volatility from options chain snapshot.

        GET /v3/snapshot/options/{ticker}?expiration_date.gte={from}&expiration_date.lte={to}
            &strike_price.gte={low}&strike_price.lte={high}&limit=250&apiKey=...

        Filters to contracts within 5% of entry_price.
        Requires >= 5 contracts with non-null implied_volatility.
        Returns volume-weighted average IV (annualized), or None.

        Args:
            ticker: Stock symbol (e.g., "AAPL")
            entry_price: Current stock price for ATM filtering
            from_expiry: Start expiration date (YYYY-MM-DD)
            to_expiry: End expiration date (YYYY-MM-DD)

        Returns:
            Volume-weighted annualized IV as float, or None if insufficient data
        """
        try:
            endpoint = f"/v3/snapshot/options/{ticker}"

            # Filter to strikes within 5% of entry price
            strike_low = round(entry_price * 0.95, 2)
            strike_high = round(entry_price * 1.05, 2)

            params = {
                "expiration_date.gte": from_expiry,
                "expiration_date.lte": to_expiry,
                "strike_price.gte": str(strike_low),
                "strike_price.lte": str(strike_high),
                "limit": "250",
            }

            response = await self._request_with_retry(endpoint, params, ticker)
            if response is None:
                return None

            data = response.json()

            # Extract contracts from response
            results = []
            if isinstance(data, dict):
                results = data.get("results", [])
            elif isinstance(data, list):
                results = data

            if not results:
                return None

            # Collect contracts with valid implied_volatility and volume
            valid_contracts = []
            for contract in results:
                # Handle nested structure: contract may have 'details' and 'greeks'
                iv = None
                volume = 0

                # Try greeks.implied_volatility first (snapshot format)
                if isinstance(contract, dict):
                    greeks = contract.get("greeks", {})
                    if isinstance(greeks, dict):
                        iv = greeks.get("implied_volatility")

                    # Also check top-level implied_volatility
                    if iv is None:
                        iv = contract.get("implied_volatility")

                    # Get volume (day volume or open_interest as fallback weight)
                    day = contract.get("day", {})
                    if isinstance(day, dict):
                        volume = day.get("volume", 0) or 0
                    if volume == 0:
                        volume = contract.get("volume", 0) or 0
                    if volume == 0:
                        # Use open_interest as weight fallback
                        volume = contract.get("open_interest", 0) or 0

                if iv is not None and iv > 0:
                    valid_contracts.append(
                        {
                            "iv": float(iv),
                            "volume": float(volume) if volume else 1.0,
                        }
                    )

            # Require at least 5 contracts with valid IV
            if len(valid_contracts) < 5:
                try:
                    logger.info(
                        f"Options IV for {ticker}: only {len(valid_contracts)} valid "
                        f"contracts (need 5+), returning None"
                    )
                except Exception:
                    pass
                return None

            # Compute volume-weighted average IV
            total_weight = sum(c["volume"] for c in valid_contracts)
            if total_weight <= 0:
                # Equal weight if all volumes are zero
                avg_iv = sum(c["iv"] for c in valid_contracts) / len(valid_contracts)
            else:
                avg_iv = sum(c["iv"] * c["volume"] for c in valid_contracts) / total_weight

            return float(avg_iv)

        except Exception as e:
            try:
                logger.error(f"Error computing options IV for {ticker}: {e}")
            except Exception:
                pass
            return None

    async def get_analyst_consensus(self, ticker: str) -> dict | None:
        """Fetch analyst consensus price targets.

        GET /benzinga/v1/consensus-ratings/{ticker}?apiKey=...

        Args:
            ticker: Stock symbol (e.g., "AAPL")

        Returns:
            Dict with 'target', 'low', 'high' keys, or None on error/empty
        """
        # Real Benzinga consensus schema (per Massive docs):
        #   results[].{consensus_price_target, high_price_target, low_price_target,
        #              consensus_rating, price_target_contributors, ratings_contributors,
        #              buy_ratings, hold_ratings, sell_ratings, strong_buy_ratings,
        #              strong_sell_ratings}
        results = await self._results(
            f"/benzinga/v1/consensus-ratings/{ticker}", {"ticker": ticker, "limit": 1}, ticker
        )
        if not results:
            return None
        r = results[0]
        target = _num(r.get("consensus_price_target"))
        if target is None:
            return None
        return {
            "target": target,  # kept for the trade engine (expects target/low/high)
            "low": _num(r.get("low_price_target")),
            "high": _num(r.get("high_price_target")),
            "rating": r.get("consensus_rating"),
            "rating_value": _num(r.get("consensus_rating_value")),
            "analyst_count": _num(
                _first(r, "price_target_contributors", "ratings_contributors")
            ),
            "buy_ratings": _num(r.get("buy_ratings")),
            "hold_ratings": _num(r.get("hold_ratings")),
            "sell_ratings": _num(r.get("sell_ratings")),
        }

    # ─── Stock Intelligence fetchers (news, insider, short interest, ─────
    #     dividends, macro). Each returns parsed data or None on failure,
    #     never raises. Reuses _request_with_retry (adds apiKey, retries 5xx).

    async def _results(self, endpoint: str, params: dict, ticker: str) -> list[dict] | None:
        """GET and return the JSON `results` list (dicts only), or None on failure.

        Returns None on transport/HTTP failure (incl. 4xx/403) and [] on an
        entitled-but-empty body. Filters to dict elements so downstream `.get()`
        can never raise (honours the never-raise contract).
        """
        response = await self._request_with_retry(endpoint, dict(params), ticker)
        if response is None:
            return None
        try:
            body = response.json()
        except Exception:
            return None
        results = body.get("results") if isinstance(body, dict) else body
        if isinstance(results, dict):
            results = [results]
        if not isinstance(results, list):
            return []
        # Keep only dict rows — a stray scalar/None would otherwise break r.get(...).
        return [r for r in results if isinstance(r, dict)]

    async def get_news(self, ticker: str, limit: int = 5) -> list[dict] | None:
        """Recent news with per-ticker sentiment (`/v2/reference/news`)."""
        results = await self._results(
            "/v2/reference/news",
            {"ticker": ticker, "limit": limit, "order": "desc", "sort": "published_utc"},
            ticker,
        )
        if results is None:
            return None
        items = []
        for r in results:
            insight = next((i for i in (r.get("insights") or []) if i.get("ticker") == ticker), {})
            items.append(
                {
                    "title": r.get("title"),
                    "publisher": (r.get("publisher") or {}).get("name"),
                    "published_utc": r.get("published_utc"),
                    "article_url": r.get("article_url"),
                    "description": r.get("description"),
                    "sentiment": insight.get("sentiment"),
                    "sentiment_reasoning": insight.get("sentiment_reasoning"),
                }
            )
        return items

    async def get_insider_trades(self, ticker: str, limit: int = 10) -> list[dict] | None:
        """SEC Form 4 insider transactions (`/stocks/filings/vX/form-4`).

        NB: this endpoint filters by ``tickers`` (an array-contains filter), NOT
        ``ticker`` — passing ``ticker`` is silently ignored and returns market-wide
        filings. Sorted newest-first by filing_date (the endpoint default).
        """
        results = await self._results(
            "/stocks/filings/vX/form-4", {"tickers": ticker, "limit": limit}, ticker
        )
        if results is None:
            return None
        trades = []
        for r in results:
            code = r.get("transaction_code")
            trades.append(
                {
                    "owner_name": r.get("owner_name"),
                    "is_director": r.get("is_director"),
                    "is_officer": r.get("is_officer"),
                    "is_ten_percent_owner": r.get("is_ten_percent_owner"),
                    "transaction_date": r.get("transaction_date"),
                    "transaction_code": code,
                    "action": _insider_action(code, r.get("transaction_acquired_disposed")),
                    "shares": _num(r.get("transaction_shares")),
                    "price": _num(r.get("transaction_price_per_share")),
                    "value": _num(r.get("transaction_value")),
                }
            )
        return trades

    async def get_short_interest(self, ticker: str) -> dict | None:
        """Latest short interest (`/stocks/v1/short-interest`)."""
        results = await self._results(
            "/stocks/v1/short-interest",
            {"ticker": ticker, "limit": 1, "sort": "settlement_date.desc"},
            ticker,
        )
        if not results:
            return None
        r = results[0]
        return {
            "settlement_date": r.get("settlement_date"),
            "short_interest": _num(r.get("short_interest")),
            "avg_daily_volume": _num(r.get("avg_daily_volume")),
            "days_to_cover": _num(r.get("days_to_cover")),
        }

    async def get_short_volume(self, ticker: str) -> dict | None:
        """Latest daily short-sale volume (`/stocks/v1/short-volume`).

        Included in all Stocks plans. `short_volume_ratio` = % of daily volume sold
        short — a fast, daily read on bearish pressure (complements short interest).
        """
        results = await self._results(
            "/stocks/v1/short-volume",
            {"ticker": ticker, "limit": 1, "sort": "date.desc"},
            ticker,
        )
        if not results:
            return None
        r = results[0]
        return {
            "date": r.get("date"),
            "short_volume": _num(r.get("short_volume")),
            "total_volume": _num(r.get("total_volume")),
            "short_volume_ratio": _num(r.get("short_volume_ratio")),
        }

    async def get_dividends(self, ticker: str, limit: int = 4) -> list[dict] | None:
        """Recent / upcoming dividends (`/stocks/v1/dividends`)."""
        results = await self._results(
            "/stocks/v1/dividends",
            {"ticker": ticker, "limit": limit, "sort": "ex_dividend_date.desc"},
            ticker,
        )
        if results is None:
            return None
        return [
            {
                "ex_dividend_date": r.get("ex_dividend_date"),
                "pay_date": r.get("pay_date"),
                "cash_amount": _num(r.get("cash_amount")),
                "frequency": r.get("frequency"),
                "currency": r.get("currency"),
            }
            for r in results
        ]

    async def get_macro(self) -> dict | None:
        """Latest macro snapshot: treasury yields + CPI (`/fed/v1/...`)."""
        yields = await self._results(
            "/fed/v1/treasury-yields", {"limit": 1, "sort": "date.desc"}, "FED"
        )
        infl = await self._results("/fed/v1/inflation", {"limit": 1, "sort": "date.desc"}, "FED")
        if not yields and not infl:
            return None
        y = yields[0] if yields else {}
        i = infl[0] if infl else {}
        return {
            "as_of": y.get("date") or i.get("date"),
            "yield_1y": _num(y.get("yield_1_year")),
            "yield_5y": _num(y.get("yield_5_year")),
            "yield_10y": _num(y.get("yield_10_year")),
            "cpi": _num(i.get("cpi")),
        }

    async def get_fundamentals(self, ticker: str) -> dict | None:
        """Latest financial ratios (`/stocks/financials/v1/ratios`). Premium (entitlement-gated)."""
        results = await self._results(
            "/stocks/financials/v1/ratios", {"ticker": ticker, "limit": 1}, ticker
        )
        if not results:
            return None
        r = results[0]
        return {
            "pe_ratio": _num(_first(r, "price_to_earnings", "pe_ratio", "pe")),
            "price_to_sales": _num(_first(r, "price_to_sales", "ps_ratio")),
            "gross_margin": _num(_first(r, "gross_margin", "gross_profit_margin")),
            "net_margin": _num(_first(r, "net_margin", "net_profit_margin")),
            "debt_to_equity": _num(_first(r, "debt_to_equity", "de_ratio")),
        }

    async def get_analyst_insights(self, ticker: str, limit: int = 5) -> list[dict] | None:
        """Recent per-analyst rating actions with rationale (`/benzinga/v1/analyst-insights`).

        Richer than the consensus card: each record is a single firm's rating, price
        target, rating_action (upgrades/downgrades/initiates/maintains) and a narrative
        `insight` explaining the call. Premium (Benzinga entitlement) — None when
        unentitled, so it degrades to "unavailable" like the other Benzinga sections.
        """
        results = await self._results(
            "/benzinga/v1/analyst-insights",
            {"ticker": ticker, "limit": limit, "sort": "date.desc"},
            ticker,
        )
        if results is None:
            return None
        return [
            {
                "date": r.get("date"),
                "firm": r.get("firm"),
                "rating": r.get("rating"),
                "rating_action": r.get("rating_action"),
                "price_target": _num(r.get("price_target")),
                "insight": r.get("insight"),
            }
            for r in results
        ]

    async def close(self) -> None:
        """Close the HTTP client. Should be called on shutdown."""
        await self.client.aclose()


def _first(d: dict, *keys: str):
    """First present, non-None value among the given keys."""
    for k in keys:
        if d.get(k) is not None:
            return d.get(k)
    return None


def _num(v) -> float | None:
    """Coerce to float, or None (never treat 0 as missing)."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _insider_action(code: str | None, acquired_disposed: str | None) -> str | None:
    """Human label for a Form-4 transaction code."""
    if code is None:
        return None
    mapping = {"P": "buy", "S": "sell", "M": "exercise", "A": "grant", "G": "gift", "F": "tax"}
    if code in mapping:
        return mapping[code]
    if acquired_disposed == "A":
        return "acquire"
    if acquired_disposed == "D":
        return "dispose"
    return "other"
