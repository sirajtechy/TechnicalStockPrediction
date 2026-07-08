"""
Scan Orchestrator

Coordinates the complete scan pipeline: universe building, market regime analysis,
indicator calculation, scoring, and ranking.
"""

import logging
import time
import uuid
from datetime import datetime, timedelta

from api.models import (
    EntryTimingResponse,
    IndicatorSignals,
    ScanMetadata,
    ScanRequest,
    ScanResponse,
    TickerScore,
)
from core.entry_timing import classify_entry_timing
from config import config
from core.api_client import ApiError, RestApiClient
from core.indicator_calculator import IndicatorCalculator
from core.ranking_service import RankingService
from core.regime_analyzer import MarketRegimeAnalyzer
from core.scoring_engine import ScoringEngine
from core.universe_builder import UniverseBuilder

logger = logging.getLogger(__name__)


class ScanError(Exception):
    """Exception raised when scan execution fails."""

    pass


class ScanOrchestrator:
    """Orchestrates the complete scan pipeline."""

    def __init__(
        self,
        api_client: RestApiClient,
        universe_builder: UniverseBuilder,
        regime_analyzer: MarketRegimeAnalyzer,
        indicator_calc: IndicatorCalculator,
        scoring_engine: ScoringEngine,
        ranking_service: RankingService,
    ):
        """
        Initialize with all component dependencies.

        Args:
            api_client: REST API client for fetching stock data
            universe_builder: Universe builder for ticker validation
            regime_analyzer: Market regime analyzer
            indicator_calc: Technical indicator calculator
            scoring_engine: Scoring engine for bullish scores
            ranking_service: Ranking service for sorting results
        """
        self.api_client = api_client
        self.universe_builder = universe_builder
        self.regime_analyzer = regime_analyzer
        self.indicator_calc = indicator_calc
        self.scoring_engine = scoring_engine
        self.ranking_service = ranking_service

        logger.info("ScanOrchestrator initialized")

    async def execute_scan(
        self,
        request: ScanRequest,
        as_of_date: str | None = None,
        apply_signal_gate: bool = True,
    ) -> ScanResponse:
        """
        Execute complete scan pipeline.

        Args:
            apply_signal_gate: When True (production/UI), bearish regimes emit zero
                candidates and only tickers scoring >= the regime threshold are
                returned. When False (backtesting), the bearish short-circuit and the
                threshold filter are skipped so the caller receives ALL
                hard-filter-passing tickers with scores plus the regime, enabling a
                full confusion matrix and threshold sweeps.

        Pipeline Flow:
        1. Clear API client cache
        2. Build universe from ticker list (validate and filter)
        3. Analyze market regime (parallel with ticker processing)
        4. For each ticker in universe:
           - Fetch stock data (with caching)
           - Calculate indicators
           - Calculate score
           - Handle errors (mark unavailable, continue)
        5. Rank all scored tickers
        6. Build response with metadata
        7. Return results

        Args:
            request: Scan request with ticker list
            as_of_date: Optional cutoff date (YYYY-MM-DD). If provided, the scanner
                        will only use data available up to this date. This prevents
                        look-ahead bias during backtesting.

        Returns:
            Complete scan results with UUID scan_id

        Raises:
            ScanError: If scan fails critically
        """
        start_time = time.time()
        scan_id = str(uuid.uuid4())

        logger.info(f"Starting scan {scan_id} with {len(request.tickers)} tickers")

        try:
            # Step 1: Clear API client cache for new scan session
            self.api_client.clear_cache()
            logger.debug("API cache cleared")

            # Step 2: Build and validate universe
            try:
                universe = self.universe_builder.build_universe(request.tickers)
                logger.info(f"Universe built with {len(universe)} valid tickers")
            except ValueError as e:
                logger.error(f"Universe building failed: {e}")
                raise ScanError(f"Invalid ticker list: {e}")

            # Step 3: Analyze market regime (V3 gate → RegimeResult)
            regime = await self.regime_analyzer.analyze_regime(as_of_date=as_of_date)
            market_regime = regime.regime
            logger.info(f"Market regime: {market_regime.value} (threshold={regime.threshold})")

            # V3 R1: BEARISH regime emits ZERO candidates — short-circuit before scoring.
            # (Skipped in backtest mode so the caller can compute FN/TN over the universe.)
            if apply_signal_gate and not regime.emit_signals:
                logger.info(f"Scan {scan_id}: bearish regime — emitting zero candidates")
                duration = time.time() - start_time
                return ScanResponse(
                    scan_id=scan_id,
                    market_regime=market_regime,
                    ranked_tickers=[],
                    metadata=ScanMetadata(
                        timestamp=datetime.utcnow(),
                        ticker_count=0,
                        duration_seconds=round(duration, 2),
                    ),
                )

            # Step 4: Fetch market data (SPY) for relative strength calculations
            try:
                market_data = await self.api_client.fetch_stock_data(
                    "SPY", days=config.HISTORY_FETCH_DAYS, as_of_date=as_of_date
                )
                logger.debug("Market data (SPY) fetched successfully")
            except ApiError as e:
                logger.error(f"Failed to fetch market data: {e}")
                raise ScanError("Unable to fetch market data for analysis")

            # === Step 5 — PASS 1: fetch + indicators + raw RS for every ticker ===
            # (Two-pass: RS percentile needs all tickers' raw RS before any is scored.)
            rows = []  # (ticker, stock_data, indicators, current_price, current_volume)
            fetch_error_count = 0  # distinguish "all fetches errored" from "validly filtered out"

            for ticker in universe:
                try:
                    stock_data = await self.api_client.fetch_stock_data(
                        ticker, days=config.HISTORY_FETCH_DAYS, as_of_date=as_of_date
                    )
                    indicators = self.indicator_calc.calculate_all(stock_data, market_data)
                    current_price = float(stock_data.prices[-1])
                    current_volume = float(stock_data.volumes[-1])
                    rows.append((ticker, stock_data, indicators, current_price, current_volume))
                except ApiError as e:
                    fetch_error_count += 1
                    logger.warning(f"Failed to fetch {ticker}: {e}. Skipping.")
                    continue
                except Exception as e:
                    fetch_error_count += 1
                    logger.error(f"Unexpected error fetching {ticker}: {e}. Skipping.")
                    continue

            # V3 R5: relative-strength percentile across the universe (min-rank for ties).
            # Precompute a {value -> percentile} map; None/unseen → 0.0 (no crash).
            rs_values = sorted(
                r[2].relative_strength for r in rows if r[2].relative_strength is not None
            )
            rank_map = (
                {v: (i / len(rs_values)) * 100 for i, v in enumerate(rs_values)}
                if rs_values
                else {}
            )

            def _rs_pct(rs):
                return rank_map.get(rs, 0.0)

            # === Step 5 — PASS 2: hard-filter gate + scoring with RS percentile ===
            scored_tickers: list[TickerScore] = []
            for ticker, stock_data, indicators, current_price, current_volume in rows:
                try:
                    # V3 R2: Minervini hard filters — any fail → not a BUY candidate.
                    passed, _checks = self.scoring_engine.passes_hard_filters(
                        current_price, indicators
                    )
                    if not passed:
                        failed = [k for k, ok in _checks.items() if not ok]
                        logger.info(f"{ticker} excluded by hard filters: failed {failed}")
                        if apply_signal_gate:
                            continue  # production/UI: drop non-candidates entirely
                        # Backtest mode: keep as a score-0 PREDICTED-NEGATIVE so the
                        # confusion matrix covers the FULL universe (FN/TN are real).
                        scored_tickers.append(
                            TickerScore(
                                ticker=ticker,
                                bullish_score=0,
                                signals=IndicatorSignals(
                                    price_above_sma50=False,
                                    price_above_ema20=False,
                                    macd_above_signal=False,
                                    macd_histogram_positive=False,
                                    volume_above_average=False,
                                    relative_strength_positive=False,
                                ),
                                current_price=current_price,
                                indicators={
                                    "sma_50": indicators.sma_50,
                                    "ema_20": indicators.ema_20,
                                    "macd_line": indicators.macd_line,
                                    "macd_signal": indicators.macd_signal,
                                    "macd_histogram": indicators.macd_histogram,
                                    "avg_volume_20": indicators.avg_volume_20,
                                    "relative_strength": indicators.relative_strength,
                                },
                                passed_hard_filters=False,
                                is_candidate=False,
                            )
                        )
                        continue

                    score_breakdown: dict = {}
                    (
                        bullish_score,
                        signals,
                        stage_result,
                        pattern_result,
                    ) = self.scoring_engine.calculate_enhanced_score(
                        current_price,
                        current_volume,
                        indicators,
                        stock_data.prices,
                        stock_data.volumes,
                        rs_percentile=_rs_pct(indicators.relative_strength),
                        breakdown=score_breakdown,
                    )

                    # V3 R7: BUY only when score clears the regime threshold
                    # (65 BULLISH / 75 NEUTRAL). Below-threshold = not a candidate.
                    # (Skipped in backtest mode so all scored tickers are returned.)
                    if apply_signal_gate and bullish_score < regime.threshold:
                        logger.info(
                            f"{ticker} below threshold: score={bullish_score} < {regime.threshold}"
                        )
                        continue

                    indicators_dict = {
                        "sma_50": indicators.sma_50,
                        "ema_20": indicators.ema_20,
                        "macd_line": indicators.macd_line,
                        "macd_signal": indicators.macd_signal,
                        "macd_histogram": indicators.macd_histogram,
                        "avg_volume_20": indicators.avg_volume_20,
                        "relative_strength": indicators.relative_strength,
                    }

                    # Entry timing classification (separate signal, does not affect score)
                    et = classify_entry_timing(current_price, indicators)
                    entry_timing = EntryTimingResponse(
                        zone=et.zone,
                        label=et.label,
                        reasons=et.reasons,
                        rsi=et.rsi,
                        dist_above_sma50_pct=et.dist_above_sma50_pct,
                        proximity_to_high=et.proximity_to_high,
                        roc_10=et.roc_10,
                    )

                    ticker_score = TickerScore(
                        ticker=ticker,
                        bullish_score=bullish_score,
                        signals=signals,
                        current_price=current_price,
                        indicators=indicators_dict,
                        passed_hard_filters=True,
                        is_candidate=bullish_score >= regime.threshold,
                        score_breakdown=score_breakdown,
                        entry_timing=entry_timing,
                    )

                    scored_tickers.append(ticker_score)
                    logger.info(f"Processed {ticker}: score={bullish_score}")

                except Exception as e:
                    logger.error(f"Unexpected error scoring {ticker}: {e}. Skipping.")
                    continue

            # V3: an empty candidate list is only an ERROR when EVERY fetch failed.
            # A valid scan where all tickers were filtered out / scored below threshold
            # returns an empty ranked list (HTTP 200), not a 500.
            if not scored_tickers and fetch_error_count == len(universe):
                logger.error("All tickers failed to fetch/process")
                raise ScanError(
                    "All tickers failed to process. Please check ticker symbols and try again."
                )
            if not scored_tickers:
                logger.info("No tickers qualified after filtering — returning empty candidate list")

            # === PASS 3: Trade Plan generation for BUY candidates (R11) ===
            candidate_scores = [ts for ts in scored_tickers if ts.is_candidate]

            if candidate_scores:
                from core.trade_engine import TradeEngine
                from core.massive_client import MassiveDataClient
                from core.trade_calibration import CalibrationTable
                from pathlib import Path
                from api.models import TradePlanResponse

                # Load calibration table
                cal_path = Path(__file__).parent.parent / "data" / "trade_calibration.json"
                calibration = None
                if cal_path.exists():
                    try:
                        calibration = CalibrationTable.load(cal_path)
                    except (ValueError, FileNotFoundError):
                        pass

                trade_engine = TradeEngine(cfg=config, calibration=calibration)
                massive = MassiveDataClient(
                    api_key=config.POLYGON_TOKEN, base_url=config.API_BASE_URL
                )

                try:
                    today = datetime.utcnow()
                    horizon_end = today + timedelta(days=45)
                    today_str = today.strftime("%Y-%m-%d")
                    horizon_str = horizon_end.strftime("%Y-%m-%d")
                    expiry_from = (today + timedelta(days=14)).strftime("%Y-%m-%d")
                    expiry_to = (today + timedelta(days=45)).strftime("%Y-%m-%d")

                    for ticker_score in candidate_scores:
                        try:
                            # Find the stock_data from PASS 1 rows cache
                            stock_data = None
                            for t, sd, ind, cp, cv in rows:
                                if t == ticker_score.ticker:
                                    stock_data = sd
                                    break

                            if stock_data is None or len(stock_data.highs) < 15:
                                ticker_score.trade_plan = None
                                continue

                            # Fetch enhancement data (each returns None on failure)
                            earnings_list = await massive.get_earnings(
                                ticker_score.ticker, today_str, horizon_str
                            )
                            options_iv = await massive.get_options_iv(
                                ticker_score.ticker,
                                ticker_score.current_price,
                                expiry_from,
                                expiry_to,
                            )
                            analyst = await massive.get_analyst_consensus(ticker_score.ticker)

                            # Determine earliest earnings date
                            earnings_date = None
                            if earnings_list:
                                dates = [
                                    e.get("date") for e in earnings_list if e.get("date")
                                ]
                                if dates:
                                    earnings_date = min(dates)

                            # Build trade plan
                            plan = trade_engine.build_plan(
                                entry=ticker_score.current_price,
                                highs=stock_data.highs,
                                lows=stock_data.lows,
                                closes=stock_data.prices,
                                score=ticker_score.bullish_score,
                                earnings_date=earnings_date,
                                options_iv=options_iv,
                                analyst=analyst,
                            )

                            # Convert TradePlan dataclass to TradePlanResponse Pydantic model
                            ticker_score.trade_plan = TradePlanResponse(
                                entry=plan.entry,
                                stop=plan.stop,
                                stop_pct=plan.stop_pct,
                                target1=plan.target1,
                                target1_pct=plan.target1_pct,
                                target2=plan.target2,
                                target2_pct=plan.target2_pct,
                                risk_per_share=plan.risk_per_share,
                                reward_risk=plan.reward_risk,
                                low_rr=plan.low_rr,
                                data_unavailable=plan.data_unavailable,
                                expected_move_pct=plan.expected_move_pct,
                                vol_source=plan.vol_source,
                                resistance=plan.resistance,
                                target_above_resistance=plan.target_above_resistance,
                                resistance_data_limited=plan.resistance_data_limited,
                                earnings_in_window=plan.earnings_in_window,
                                prob_hit_target1=plan.prob_hit_target1,
                                calibration_available=plan.calibration_available,
                                analyst_target=plan.analyst_target,
                                analyst_low=plan.analyst_low,
                                analyst_high=plan.analyst_high,
                            )

                        except ValueError as e:
                            logger.warning(
                                f"Trade plan failed for {ticker_score.ticker}: {e}"
                            )
                            ticker_score.trade_plan = None
                        except Exception as e:
                            logger.error(
                                f"Unexpected error building trade plan for "
                                f"{ticker_score.ticker}: {e}"
                            )
                            ticker_score.trade_plan = None
                finally:
                    await massive.close()

            # Step 6: Rank tickers
            ranked_tickers = self.ranking_service.rank_tickers(scored_tickers)
            logger.info(f"Ranked {len(ranked_tickers)} tickers")

            # Step 7: Build response with metadata
            duration = time.time() - start_time

            metadata = ScanMetadata(
                timestamp=datetime.utcnow(),
                ticker_count=len(ranked_tickers),
                duration_seconds=round(duration, 2),
            )

            response = ScanResponse(
                scan_id=scan_id,
                market_regime=market_regime,
                ranked_tickers=ranked_tickers,
                metadata=metadata,
                score_threshold=regime.threshold,
            )

            logger.info(
                f"Scan {scan_id} completed in {duration:.2f}s: "
                f"{len(ranked_tickers)} tickers processed, "
                f"market regime: {market_regime.value}"
            )

            return response

        except ScanError:
            # Re-raise ScanError as-is
            raise
        except Exception as e:
            logger.error(f"Critical error during scan execution: {e}", exc_info=True)
            raise ScanError(f"Scan failed due to unexpected error: {e!s}")
