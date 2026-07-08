# Implementation Plan: Trade Engine

## Overview

The Trade Engine transforms BUY candidates from the V3 scanner into concrete, risk-defined equity trade plans. Implementation follows a TDD phased approach: data layer → core engine → Massive enhancements → calibration backtest (ship gate) → API/orchestrator wiring → frontend UI. Every task ships with its tests. Property-based tests (hypothesis) validate correctness properties P1–P9. The calibration phase is a ship gate — no probability claims reach the UI until the backtest validates positive expectancy and calibrated probabilities.

## Tasks

- [x] 1. Data layer — OHLC extension
  - [x] 1.1 Add highs/lows arrays to StockData and populate from Polygon bars
    - Extend `StockData` in `core/models.py` with `highs: np.ndarray` and `lows: np.ndarray` fields
    - Modify `RestApiClient.fetch_stock_data` in `core/api_client.py` to populate `highs` from `bar["h"]` and `lows` from `bar["l"]` in the existing parse loop
    - Ensure `highs[i] >= lows[i]` invariant for all indices
    - Existing indicator/scoring code must remain unaffected (backward compatible)
    - _Requirements: 12.1, 12.2, 12.3, 12.5_

  - [x]* 1.2 Write unit tests for OHLC extension
    - Add tests in `tests/unit/test_api_client.py`: highs/lows populated with correct length matching prices/volumes
    - Test that highs[i] >= lows[i] for all elements
    - Test that existing code paths (indicators, scoring) still work with new fields present
    - _Requirements: 12.1, 12.2, 12.5_

- [x] 2. Core TradeEngine — ATR, stop, targets, expected move, R:R
  - [x] 2.1 Implement TradeConfig parameters in config.py
    - Add trade engine configuration constants to the existing `Config` class: `TRADE_ATR_MULT`, `TRADE_MAX_LOSS_PCT`, `TRADE_TARGET1_MULT`, `TRADE_TARGET2_MULT`, `TRADE_HORIZON_DAYS`, `TRADE_SIGMA_LOOKBACK`, `TRADE_MIN_REWARD_RISK`, `TRADE_EARNINGS_WIDEN_FACTOR`, `TRADE_EARNINGS_CONFIDENCE_DISCOUNT`, `TRADE_RESISTANCE_LOOKBACK`
    - Add validation: TARGET1_MULT < TARGET2_MULT, ranges per design §3.2
    - _Requirements: 1.1, 2.1, 2.2, 2.5, 3.1, 5.1, 6.3, 6.4_

  - [x] 2.2 Implement TradePlan dataclass and TradeEngine.compute_atr()
    - Create `core/trade_engine.py` with `TradePlan` dataclass (all fields per design §3.3)
    - Implement `TradeEngine.__init__` accepting `Config` and optional `CalibrationTable`
    - Implement `TradeEngine.compute_atr(highs, lows, closes, n=14)` — true range mean, requires n+1 bars minimum
    - Raise `ValueError` if fewer than 15 OHLC bars available
    - _Requirements: 1.5, 1.6, 12.4_

  - [x] 2.3 Implement TradeEngine.build_plan() — stop, targets, R:R, expected move
    - Implement stop = entry − atr_mult × ATR, with floor cap at entry × (1 − max_loss_pct)
    - Compute risk_per_share = entry − stop; reject if ≤ 0
    - Compute target1 = entry + T1_R × risk, target2 = entry + T2_R × risk
    - Compute reward_risk = (target1 − entry) / risk_per_share; set low_rr flag
    - Implement `compute_historical_sigma(prices, lookback=20)` for daily log returns
    - Expected move: options IV branch (daily_sigma = iv / √252) vs historical branch
    - expected_move_pct = daily_sigma × √horizon × 100
    - Set vol_source to "options_iv" or "historical"
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 2.4 Implement resistance annotation in build_plan
    - Implement `compute_resistance(highs)` — max of 60-day high and 252-day high
    - Set `target_above_resistance = target1 > resistance`; never mutate targets
    - Set `resistance_data_limited = True` if fewer than 60 bars available
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x]* 2.5 Write unit tests for TradeEngine (test_trade_engine.py)
    - Create `tests/unit/test_trade_engine.py` with all 24 test cases per R16.1:
    - ATR correctness on known OHLC, ATR < 15 bars raises error
    - Stop = entry − atr_mult × ATR; stop cap at max_loss_pct
    - risk_per_share > 0 always; rejection when invalid
    - Targets at correct R-multiples; target1 < target2
    - reward_risk = TARGET1_MULT; low_rr threshold boundary
    - Expected move formula; vol_source selection
    - Resistance = max(60d high, 252d high); target_above_resistance flag
    - Resistance never mutates targets
    - _Requirements: 16.1_

  - [x]* 2.6 Write property tests P1, P2, P3, P4, P9 (test_trade_engine_properties.py)
    - **Property 1: Stop-Risk Invariant** — stop < entry AND risk > 0 AND stop ≥ entry × (1 − max_loss_pct)
    - **Validates: Requirements 1.1, 1.2, 1.3**
    - **Property 2: Target R-Multiple Correctness** — target1 = entry + T1_R × risk (within ε), target1 < target2, reward_risk = T1_R
    - **Validates: Requirements 2.1, 2.2, 2.4, 5.1**
    - **Property 3: Resistance Annotation Correctness** — target_above_resistance iff target1 > resistance; targets unchanged
    - **Validates: Requirements 4.2, 4.3, 4.5**
    - **Property 4: Low R:R Flag** — low_rr iff reward_risk < MIN_REWARD_RISK
    - **Validates: Requirements 5.2, 5.3**
    - **Property 9: ATR/Expected Move Math** — ATR = mean of 14 true ranges; expected_move_pct = sigma × √horizon × 100
    - **Validates: Requirements 1.5, 3.1, 3.2**
    - _Requirements: 16.4_

- [x] 3. Checkpoint — Core engine tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Massive enhancements — client, earnings, options IV, analyst
  - [x] 4.1 Implement MassiveDataClient (core/massive_client.py)
    - Create `core/massive_client.py` with `MassiveDataClient` class
    - Implement `get_earnings(ticker, from_date, to_date)` → list[dict] | None
    - Implement `get_options_iv(ticker, entry_price, from_expiry, to_expiry)` → float | None (volume-weighted ATM IV, min 5 contracts)
    - Implement `get_analyst_consensus(ticker)` → dict | None (target/low/high)
    - Same auth as RestApiClient (POLYGON_TOKEN as apiKey param)
    - Retry with exponential backoff (1s, 2s, 4s) for 5xx/network errors; no retry on 4xx
    - All methods return None on failure — never raise
    - httpx.AsyncClient with 10s timeout, max 5 concurrent connections
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [x] 4.2 Implement earnings-in-window flag and target widening in build_plan
    - Accept `earnings_date: str | None` in build_plan
    - If earnings within horizon: set `earnings_in_window`, widen expected_move_pct by EARNINGS_WIDEN_FACTOR
    - Recompute target2 using widened move; leave target1 unchanged
    - Multiply prob_hit_target1 by EARNINGS_CONFIDENCE_DISCOUNT (floor at 0.05)
    - Null earnings → no widening applied
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 4.3 Implement options IV override and analyst passthrough in build_plan
    - When valid options_iv supplied (not None, > 0, ≤ 5.0): use as daily_sigma source, set vol_source = "options_iv"
    - Invalid/None options_iv → historical fallback, never raises
    - Attach analyst_target/low/high when `analyst` dict provided; null when absent
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x]* 4.4 Write unit tests for MassiveDataClient (test_massive_client.py)
    - Create `tests/unit/test_massive_client.py` with all 11 test cases per R16.2:
    - Earnings: parse valid response, empty response, HTTP error → None, timeout → None
    - Options: parse ≥ 5 contracts → weighted IV, < 5 → None, HTTP error → None
    - Consensus: parse valid, empty → None, timeout → None
    - Retry: 5xx triggers retry (up to 3), 4xx no retry
    - All tests use httpx mock transport (zero network)
    - _Requirements: 16.2_

  - [x]* 4.5 Write unit tests for earnings/options/analyst in build_plan
    - Test earnings inside window widens target2/expected_move; outside → no-op
    - Test prob not raised when earnings set; floor at 0.05
    - Test options override vs historical fallback; None → no raise
    - Test analyst fields pass through when supplied, null when absent
    - _Requirements: 16.1_

  - [x]* 4.6 Write property tests P5, P6 (test_trade_engine_properties.py)
    - **Property 5: Earnings Widening Effect** — with earnings: target2 and expected_move > no-earnings case, prob ≤ no-earnings prob, target1 unchanged
    - **Validates: Requirements 6.3, 6.4, 7.4**
    - **Property 6: Vol Source Selection** — vol_source = "options_iv" iff valid options_iv supplied; invalid → "historical", no exception
    - **Validates: Requirements 3.3, 3.4, 8.3, 8.4**
    - _Requirements: 16.4_

- [x] 5. Calibration backtest (SHIP GATE)
  - [x] 5.1 Implement CalibrationTable (core/trade_calibration.py + data/trade_calibration.json)
    - Create `core/trade_calibration.py` with `CalibrationRow` dataclass and `CalibrationTable` class
    - Implement `load(path)` from JSON, `lookup(score, atr_pct)` → (prob | None, calibration_available)
    - Implement `score_band(score)` and `atr_band(atr_pct)` classification
    - Unknown bucket → returns (None, False); build_plan uses default 0.50
    - Wire calibration lookup into `build_plan` for `prob_hit_target1`
    - Create initial `data/trade_calibration.json` with schema (populated after backtest)
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6_

  - [x]* 5.2 Write unit tests for CalibrationTable (test_trade_calibration.py)
    - Create `tests/unit/test_trade_calibration.py` with 4 test cases per R16.3:
    - Lookup known bucket → stored probability
    - Lookup unknown bucket → None
    - Load valid JSON → success
    - Load corrupt/missing JSON → descriptive error
    - _Requirements: 16.3_

  - [x]* 5.3 Write property test P7 (test_trade_engine_properties.py)
    - **Property 7: Calibration Probability Source** — prob_hit_target1 from CalibrationTable lookup or default 0.50; always in [0.0, 1.0] rounded to 2dp
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.5**
    - _Requirements: 16.4_

  - [x] 5.4 Implement backtest script (scripts/trade_backtest.py)
    - Create `scripts/trade_backtest.py` with walk-forward first-touch logic:
    - For historical BUY candidates (min 200 trading days), build plan and walk forward 30 bars
    - Classify: stop-hit, target1-hit, undecided (0R)
    - Compute hit rate and expectancy in R-units
    - 70/30 in-sample/out-of-sample temporal split
    - Bucket candidates by score band × ATR band; verify calibration within ±5pp
    - Parameter sweep: atr_mult 1.5–3.0 × target1_mult 1.5–3.0 (16 combos)
    - Earnings-window subset: confirm variance ratio ≥ 1.2
    - Report failing metrics clearly; produce Calibration_Table only if all pass
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

  - [x]* 5.5 Write unit tests for backtest first-touch evaluator
    - Test on synthetic forward bars: stop-first → classified stop, target-first → classified target, neither → undecided
    - Test expectancy computation with known results
    - Test temporal split logic (70/30 by date)
    - _Requirements: 13.2, 13.4_

  - [x] 5.6 Run calibration backtest and validate results
    - Execute backtest: verify expectancy > 0R on both in-sample and out-of-sample
    - Verify prob claims within ±5pp per bucket
    - Run parameter sweep; select best operating point with positive OOS expectancy
    - Run earnings validation; confirm variance ratio ≥ 1.2
    - Populate `data/trade_calibration.json` with validated results
    - Document findings in `docs/TRADE_ENGINE_RESULTS.md`
    - **SHIP GATE: Only proceed to Phase 6 if positive expectancy and calibrated**
    - _Requirements: 13.3, 13.4, 13.5, 13.7, 14.5, 15.4_

- [x] 6. Checkpoint — Calibration ship gate passed
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. API + Orchestrator wiring
  - [x] 7.1 Add TradePlanResponse model and extend TickerScore in api/models.py
    - Create `TradePlanResponse` Pydantic model with all fields per design §3.8
    - Add `trade_plan: TradePlanResponse | None = None` field to existing `TickerScore` model
    - Ensure JSON serialization/deserialization works correctly
    - _Requirements: 11.3, 11.5, 11.6_

  - [x] 7.2 Wire TradeEngine into ScanOrchestrator (core/orchestrator.py)
    - After PASS 2 identifies BUY candidates, batch-fetch enhancement data via MassiveDataClient
    - Build trade plans for candidate set only (not full universe)
    - Attach `trade_plan` to each candidate's `TickerScore`; null for non-candidates
    - Handle plan failures per-ticker (null + log warning, continue)
    - Skip Massive calls when no candidates
    - Cache stock_data from PASS 1 rows for reuse in plan building
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x]* 7.3 Write unit test for orchestrator trade plan wiring
    - Test in `tests/unit/test_orchestrator.py`: plan present for candidate, null for hard-filter fail
    - Test no Massive call when zero candidates
    - Test graceful degradation when Massive unavailable (core plan still produced)
    - _Requirements: 16.1, 11.1, 11.2, 11.4_

  - [x]* 7.4 Write property test P8 (test_trade_engine_properties.py)
    - **Property 8: Plan Scoping to Candidates** — trade_plan non-null only where is_candidate=true; non-candidates always null
    - **Validates: Requirements 11.1, 11.2**
    - _Requirements: 16.4_

  - [x]* 7.5 Write integration tests (test_trade_engine_integration.py + test_trade_plan_endpoint.py)
    - Create `tests/integration/test_trade_engine_integration.py`: orchestrator pipeline tests per R17.1
    - Create `tests/integration/test_trade_plan_endpoint.py`: API endpoint tests per R17.2
    - Create `tests/integration/test_massive_client_integration.py`: live smoke tests (gated) per R17.3
    - All use FastAPI TestClient; external calls mocked (except gated smoke tests)
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

- [x] 8. Checkpoint — Backend complete, all tests green
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Frontend — types, UI, and report
  - [x] 9.1 Add TradePlan TypeScript type and extend TickerScore interface
    - Update `frontend/src/types/scan.ts` with `TradePlan` interface (all fields per design §3.9)
    - Add `trade_plan?: TradePlan | null` to existing `TickerScore` interface
    - Ensure types align with backend TradePlanResponse schema
    - _Requirements: 11.3, 11.5_

  - [x] 9.2 Implement trade plan expandable row in ResultsTable
    - Add Cloudscape `ExpandableSection` per candidate row in `frontend/src/components/ResultsTable.tsx`
    - Display: entry, stop (with loss %), target1 (with gain %), target2 (with gain %), R:R, expected move %, probability %
    - Badges: "⚠ Earnings on YYYY-MM-DD" (amber), resistance warning, low R:R warning
    - Show vol_source label ("IV" vs "Hist")
    - Show analyst price range (low–target–high) when populated; hide when null
    - Add `data-testid` attributes for E2E tests
    - _Requirements: 11.5, 18.1_

  - [x] 9.3 Add trade plan section to download report (scanReport.ts)
    - Extend `frontend/src/utils/scanReport.ts` with Trade Plan columns per candidate
    - Include: entry, stop, target1, target2, R:R, expected move, probability, earnings badge, resistance annotation
    - _Requirements: 11.6, 18.2_

  - [x]* 9.4 Write frontend unit tests (vitest)
    - Test ResultsTable renders trade plan expandable section for candidates
    - Test badges render correctly for earnings/resistance/low_rr
    - Test null trade_plan shows "Plan unavailable"
    - Test report generation includes trade plan fields
    - Run `tsc --noEmit` and `eslint` clean
    - _Requirements: 18.1, 18.2_

  - [x]* 9.5 Write Playwright E2E tests
    - Create `frontend/tests/e2e/trade-plan-display.spec.ts` per R18.1: expand trigger, fields, badges, collapse
    - Create `frontend/tests/e2e/trade-plan-report.spec.ts` per R18.2: download, fields, earnings, resistance
    - Create `frontend/tests/e2e/trade-plan-edge-cases.spec.ts` per R18.3: zero candidates, null plan, loading
    - All route-intercepted (no live backend); fixture-based; screenshots for visual regression
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

- [x] 10. Final validation gate — full regression
  - [x] 10.1 Run full backend regression + frontend lint + E2E suite
    - Backend: `pytest` all green (unit + property + integration), `ruff check .` clean, `mypy .` clean
    - Frontend: `npm test` green, `tsc --noEmit` clean, `npx playwright test` green
    - Confirm: trade plans only on candidates (P8), positive expectancy confirmed, calibration within tolerance
    - Verify > 90% line coverage on `core/trade_engine.py`, `core/massive_client.py`, `core/trade_calibration.py`
    - _Requirements: 16.6, 16.7, 17.6, 18.6_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (P1–P9)
- Unit tests validate specific examples and edge cases
- **Ship gate:** Phase 5 (calibration) must pass — positive expectancy + calibrated probabilities — before Phase 9 exposes anything to users. No hallucinated numbers reach the UI.
- **Property coverage:** P1→2.6 · P2→2.6 · P3→2.6 · P4→2.6 · P5→4.6 · P6→4.6 · P7→5.3 · P8→7.4 · P9→2.6
- **Definition of Done (per task):** implementation + unit tests + referenced property + >90% coverage on core modules

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4"] },
    { "id": 3, "tasks": ["2.5", "2.6"] },
    { "id": 4, "tasks": ["4.1", "5.1"] },
    { "id": 5, "tasks": ["4.2", "4.3", "4.4", "5.2"] },
    { "id": 6, "tasks": ["4.5", "4.6", "5.3", "5.4"] },
    { "id": 7, "tasks": ["5.5", "5.6"] },
    { "id": 8, "tasks": ["7.1", "9.1"] },
    { "id": 9, "tasks": ["7.2", "7.3"] },
    { "id": 10, "tasks": ["7.4", "7.5"] },
    { "id": 11, "tasks": ["9.2", "9.3"] },
    { "id": 12, "tasks": ["9.4", "9.5"] },
    { "id": 13, "tasks": ["10.1"] }
  ]
}
```
