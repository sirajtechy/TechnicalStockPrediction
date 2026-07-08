# Requirements Document

## Introduction

The Trade Engine transforms bullish BUY candidates from the V3 scanner into concrete, equity-only trade plans. For each candidate that passes hard filters and scores above the regime threshold, the Trade Engine computes: a volatility-based stop-loss, profit targets at configurable R-multiples, a realistic 30-day expected move, a reward:risk quality gate, an earnings-in-window warning with target widening, and a calibrated probability of hitting the primary target. Every number is computed from data and back-tested for calibration — if the engine claims "60% chance of +5%," the backtest must show it actually happened approximately 60% of the time.

## Glossary

- **Trade_Engine**: The core module (`core/trade_engine.py`) that computes trade plans for BUY candidates
- **Trade_Plan**: A Pydantic model representing a complete trade plan with entry, stop, targets, reward:risk, expected move, earnings flag, and probability
- **BUY_Candidate**: A ticker that passed Minervini hard filters AND scored at or above the regime threshold in the scanner
- **ATR**: Average True Range over 14 periods, a measure of daily price volatility requiring high, low, and close data
- **Risk_Per_Share**: The dollar distance from entry price to stop price (entry minus stop); must be greater than zero
- **R_Multiple**: A profit target expressed as a multiple of risk_per_share (e.g., 2R means target is entry plus 2 times risk_per_share)
- **Expected_Move**: The statistically predicted 1-sigma price range over the 30-trading-day horizon
- **Calibration_Table**: A precomputed lookup of empirical hit rates by setup bucket, built from backtest data (never computed ad hoc at runtime)
- **Setup_Bucket**: A grouping key (score band, ATR band) used to index the Calibration_Table for probability lookup
- **Resistance**: The nearest overhead price level computed as the maximum of the 60-day swing high and the 52-week high
- **Massive_Client**: A thin HTTP client module (`core/massive_client.py`) for accessing non-aggregate Massive (Polygon) REST endpoints for earnings, options, and analyst data
- **Scanner**: The existing V3 ScanOrchestrator that identifies BUY candidates
- **StockData**: The internal data model (`core/models.py`) holding ticker price history
- **TickerScore**: The Pydantic response model (`api/models.py`) representing a scored ticker in scan results
- **Vol_Source**: An enumeration indicating whether the expected move was derived from options implied volatility or historical volatility

## Requirements

### Requirement 1: Volatility-Based Stop Loss (ATR)

**User Story:** As a trader, I want a volatility-based stop-loss computed from ATR, so that my downside risk is proportional to the stock's actual volatility and bounded by a hard floor.

#### Acceptance Criteria

1. WHEN a trade plan is computed, THE Trade_Engine SHALL set stop price equal to entry price minus atr_mult multiplied by ATR(14), where atr_mult is configurable within the range 1.0 to 5.0 with a default of 2.0
2. IF the computed stop implies a loss greater than the MAX_LOSS_PCT hard floor (configurable within -0.25 to -0.01, default negative 10 percent), THEN THE Trade_Engine SHALL cap the stop at entry price multiplied by (1 plus MAX_LOSS_PCT)
3. WHEN the stop price is determined, THE Trade_Engine SHALL compute risk_per_share as entry price minus stop price, rounded to 2 decimal places
4. IF risk_per_share is less than or equal to zero, THEN THE Trade_Engine SHALL reject the plan without modifying any prior state and return an error indicating invalid risk with the computed risk_per_share value
5. WHEN ATR(14) is computed, THE Trade_Engine SHALL use 14 periods of true range calculated from high, low, and close data, requiring a minimum of 15 consecutive OHLC bars
6. IF fewer than 15 OHLC bars are available for ATR(14) computation, THEN THE Trade_Engine SHALL reject the plan and return an error indicating insufficient price data with the number of bars available

### Requirement 2: Profit Targets (R-Multiples)

**User Story:** As a trader, I want profit targets expressed as R-multiples, so that my reward is defined relative to my risk and I have both a primary and stretch objective.

#### Acceptance Criteria

1. WHEN a trade plan is computed, THE Trade_Engine SHALL set target1 equal to entry price plus TARGET1_MULT multiplied by risk_per_share, where TARGET1_MULT is configurable with a default of 2.0 and must be greater than 0
2. WHEN a trade plan is computed, THE Trade_Engine SHALL set target2 equal to entry price plus TARGET2_MULT multiplied by risk_per_share, where TARGET2_MULT is configurable with a default of 3.0 and must be greater than TARGET1_MULT; both targets SHALL be computed using the same risk_per_share value determined in Requirement 1
3. THE Trade_Engine SHALL report each target as both an absolute price rounded to 2 decimal places and a percentage gain from entry rounded to 2 decimal places
4. THE Trade_Engine SHALL ensure target1 is less than target2; IF target1 is not less than target2 due to floating-point arithmetic, THEN THE Trade_Engine SHALL recalculate using the same risk_per_share to guarantee proper ordering
5. IF TARGET1_MULT is configured to be greater than or equal to TARGET2_MULT, THEN THE Trade_Engine SHALL reject the configuration and return an error message indicating that TARGET1_MULT must be less than TARGET2_MULT

### Requirement 3: Expected 30-Day Move

**User Story:** As a trader, I want to see the realistic 30-day expected move, so that I can assess whether the targets are plausible relative to historical or implied volatility.

#### Acceptance Criteria

1. WHEN computing the expected move, THE Trade_Engine SHALL calculate the 1-sigma move as daily_sigma multiplied by the square root of horizon_trading_days, where horizon_trading_days defaults to 21 and is configurable between 1 and 63 trading days
2. WHEN historical volatility is used and at least 20 trading days of daily log returns are available within the trailing 30-trading-day window, THE Trade_Engine SHALL compute daily_sigma from the standard deviation of those daily log returns
3. WHEN options implied volatility is available from Requirement 8 and is greater than 0 and no greater than 5.0 (annualized), THE Trade_Engine SHALL use implied volatility divided by the square root of 252 as daily_sigma in preference over historical volatility
4. IF options implied volatility is unavailable or invalid, THEN THE Trade_Engine SHALL fall back to historical volatility as the source for daily_sigma
5. THE Trade_Engine SHALL record vol_source as either "options_iv" or "historical" on the Trade_Plan
6. THE Trade_Engine SHALL report expected_move_pct as the 1-sigma percentage move from entry, rounded to 2 decimal places
7. IF fewer than 20 trading days of price data are available and options implied volatility is also unavailable or invalid, THEN THE Trade_Engine SHALL omit the expected move calculation and record expected_move_pct as null on the Trade_Plan

### Requirement 4: Resistance Cap and Annotation

**User Story:** As a trader, I want to know when my target exceeds overhead resistance, so that I can factor in the likelihood of price stalling at a known supply zone.

#### Acceptance Criteria

1. WHEN a trade plan is computed, THE Trade_Engine SHALL compute nearest_resistance as the maximum of the 60-day high (the highest value in the highs array over the trailing 60 trading days) and the 52-week high (the highest value in the highs array over the trailing 252 trading days)
2. WHEN target1 is strictly greater than nearest_resistance, THE Trade_Engine SHALL set target_above_resistance to true on the Trade_Plan
3. WHEN target1 is less than or equal to nearest_resistance, THE Trade_Engine SHALL set target_above_resistance to false on the Trade_Plan
4. THE Trade_Engine SHALL include nearest_resistance as a numeric price field on the Trade_Plan for display purposes
5. THE Trade_Engine SHALL NOT modify target1 or target2 based on resistance levels
6. IF the highs array contains fewer than 60 elements, THEN THE Trade_Engine SHALL compute nearest_resistance using all available highs data and set resistance_data_limited to true on the Trade_Plan

### Requirement 5: Reward-Risk Ratio and Quality Gate

**User Story:** As a trader, I want a minimum reward-to-risk quality gate, so that I only act on plans with favorable asymmetry and can still see flagged plans below the threshold.

#### Acceptance Criteria

1. THE Trade_Engine SHALL compute reward_risk as (target1 minus entry) divided by risk_per_share, rounded to 2 decimal places
2. WHEN reward_risk is less than MIN_REWARD_RISK (configurable, default 1.5, valid range 0.5 to 10.0), THE Trade_Engine SHALL set low_rr to true on the Trade_Plan; WHEN risk_per_share is zero or invalid (making reward_risk calculation impossible), THE Trade_Engine SHALL also set low_rr to true
3. WHEN reward_risk is greater than or equal to MIN_REWARD_RISK, THE Trade_Engine SHALL set low_rr to false on the Trade_Plan
4. THE Trade_Engine SHALL include all plans in the output regardless of reward_risk value
5. THE Trade_Engine SHALL always include reward_risk as a field on the Trade_Plan; WHEN target1 or entry is unavailable or risk_per_share is not greater than zero, THE Trade_Engine SHALL set reward_risk to null and set a separate data_unavailable flag to true on the Trade_Plan
6. WHEN data is unavailable for reward_risk computation, THE Trade_Engine SHALL set data_unavailable to true (distinct from the low_rr flag which indicates a calculable but unfavorable ratio)

### Requirement 6: Earnings-in-Window Flag and Target Widening

**User Story:** As a trader, I want to be warned when an earnings announcement falls within my 30-day horizon, so that I understand the elevated two-sided risk and see an adjusted expected move.

#### Acceptance Criteria

1. WHEN a trade plan is computed, THE Trade_Engine SHALL query the Massive_Client for all earnings dates for the ticker that fall within the next 30 calendar days from the entry date
2. WHEN one or more earnings dates fall within the 30-day horizon, THE Trade_Engine SHALL set earnings_in_window to the earliest earnings date string in YYYY-MM-DD format
3. WHEN earnings_in_window is set, THE Trade_Engine SHALL multiply expected_move_pct by EARNINGS_WIDEN_FACTOR (configurable, valid range 1.0 to 3.0, default 1.5) and recompute target2 using the widened move while leaving target1 unchanged
4. WHEN earnings_in_window is set, THE Trade_Engine SHALL multiply prob_hit_target1 by EARNINGS_CONFIDENCE_DISCOUNT (configurable, valid range 0.5 to 1.0, default 0.8) to produce the adjusted probability
5. WHEN no earnings date falls within the 30-day horizon, THE Trade_Engine SHALL set earnings_in_window to null
6. IF the earnings query fails due to network error, HTTP 4xx/5xx response, or exceeds a 5-second timeout, THEN THE Trade_Engine SHALL set earnings_in_window to null and proceed without widening
7. THE Trade_Engine SHALL NOT exclude a ticker from plan generation due to earnings presence

### Requirement 7: Calibrated Probability of Hitting Target

**User Story:** As a trader, I want an honest probability estimate that the stock will reach target1 before hitting my stop, so that I can size my confidence appropriately.

#### Acceptance Criteria

1. WHEN a trade plan is computed, THE Trade_Engine SHALL look up prob_hit_target1 from the Calibration_Table using the ticker's Setup_Bucket
2. THE Trade_Engine SHALL derive the Setup_Bucket by combining the ticker's score band (low: 0-39, mid: 40-69, high: 70-100) with its ATR band (tight: ATR less than or equal to 3% of price, normal: ATR greater than 3% and less than or equal to 6% of price, wide: ATR greater than 6% of price)
3. IF no matching bucket exists in the Calibration_Table, THEN THE Trade_Engine SHALL use a default probability of 0.50 and flag calibration_available as false
4. WHEN earnings_in_window is set, THE Trade_Engine SHALL multiply prob_hit_target1 by the EARNINGS_CONFIDENCE_DISCOUNT (default 0.80), with the result floored at 0.05
5. THE Trade_Engine SHALL report prob_hit_target1 as a decimal in the inclusive range 0.0 to 1.0, rounded to two decimal places
6. THE Calibration_Table SHALL be built exclusively from backtest data (Validation Requirement 13) and never computed ad hoc at runtime

### Requirement 8: Options-Implied Expected Move

**User Story:** As a trader, I want the engine to use options-implied volatility when available, so that the expected move reflects the market's forward-looking view rather than just historical data.

#### Acceptance Criteria

1. WHEN a trade plan is computed, THE Massive_Client SHALL request the options chain snapshot for the ticker from GET /v3/snapshot/options/{underlyingAsset} filtering to contracts expiring within 14 to 45 days from the entry date
2. WHEN the options chain response contains at least 5 contracts with non-null implied_volatility fields for strike prices within 5 percent of the current price, THE Trade_Engine SHALL compute the volume-weighted average of those implied volatility values as the at-the-money implied volatility
3. WHEN the options chain response is missing, returns fewer than 5 valid near-the-money contracts, returns an HTTP error, or encounters any computation error during options processing, THE Trade_Engine SHALL fall back to historical volatility without error and SHALL NOT block plan generation
4. THE Trade_Engine SHALL set vol_source to reflect the data source actually used: "options_iv" when implied volatility data was successfully derived and used, "historical" when the fallback to historical volatility occurred for any reason
5. THE Trade_Engine SHALL NOT block or fail plan generation due to any options-related issue including unavailable data, computation errors, or invalid market data during options processing
6. WHEN deriving daily_sigma from options implied volatility, THE Trade_Engine SHALL divide the annualized at-the-money implied volatility by the square root of 252

### Requirement 9: Analyst Consensus Target (Optional Anchor)

**User Story:** As a trader, I want to see the analyst consensus price target alongside my computed plan, so that I have an external reference point for sanity-checking my targets.

#### Acceptance Criteria

1. WHEN a trade plan is computed, THE Massive_Client SHALL request consensus ratings from GET /benzinga/v1/consensus-ratings/{ticker} with a request timeout of 5 seconds
2. WHEN the consensus response contains at least one analyst rating with a price target, THE Trade_Engine SHALL attach analyst_target (mean of all price targets), analyst_low (minimum price target), and analyst_high (maximum price target) to the Trade_Plan
3. WHEN the consensus response returns an empty result set, contains no ratings with price targets, returns an HTTP error status, or exceeds the 5-second timeout, THE Trade_Engine SHALL set analyst_target, analyst_low, and analyst_high to null
4. THE Trade_Engine SHALL NOT modify computed targets (target1, target2) based on analyst consensus values
5. THE Trade_Engine SHALL NOT block or fail plan generation due to any analyst-data-related issue, including unavailable data, timeouts exceeding 5 seconds, or processing errors; plan generation SHALL proceed regardless

### Requirement 10: Massive Data Client for External Endpoints

**User Story:** As a developer, I want a thin HTTP client for Massive REST endpoints (earnings, options, analyst), so that the Trade Engine can retrieve supplementary data using the same authentication as the existing scanner.

#### Acceptance Criteria

1. THE Massive_Client SHALL support GET /benzinga/v1/earnings with query parameters: ticker (string), date.gte (YYYY-MM-DD), and date.lte (YYYY-MM-DD) for date range filtering
2. THE Massive_Client SHALL support GET /v3/snapshot/options/{underlyingAsset} with query parameters: expiration_date.gte, expiration_date.lte, strike_price.gte, strike_price.lte, and limit (max 250)
3. THE Massive_Client SHALL support GET /benzinga/v1/consensus-ratings/{ticker}
4. THE Massive_Client SHALL authenticate using the same POLYGON_TOKEN passed as an apiKey query parameter, consistent with the existing RestApiClient
5. IF any Massive endpoint returns a non-success HTTP status (4xx or 5xx), THEN THE Massive_Client SHALL attempt to log the error with endpoint path, status code, and ticker, and SHALL return None to the caller regardless of whether logging succeeds or fails
6. THE Massive_Client SHALL use async HTTP via httpx.AsyncClient with a per-request timeout of 10 seconds and connection pool limits matching the existing RestApiClient (max 5 concurrent)
7. THE Massive_Client SHALL implement retry with exponential backoff (1s, 2s, 4s delays) for up to 3 attempts on network errors and 5xx status codes, but SHALL NOT retry on 4xx client errors

### Requirement 11: Trade Plans Scoped to BUY Candidates Only

**User Story:** As a user, I want trade plans computed only for BUY candidates, so that the system does not waste API calls on tickers that did not pass the scanner's quality bar.

#### Acceptance Criteria

1. THE Trade_Engine SHALL compute trade plans if and only if the ticker is a BUY_Candidate (passed hard filters AND scored at or above the regime threshold); trade plan computation is strictly forbidden for non-BUY candidates
2. THE Trade_Engine SHALL NOT compute trade plans for tickers that failed hard filters or scored below the regime threshold, and SHALL set the trade_plan field to null on those TickerScore entries
3. WHEN a trade plan is computed for a BUY_Candidate, THE Trade_Engine SHALL attach it to the TickerScore model via a trade_plan field containing the complete Trade_Plan object
4. IF trade plan computation fails for a BUY_Candidate (due to insufficient data or invalid risk), THEN THE Trade_Engine SHALL set trade_plan to null on that TickerScore, log a warning with the ticker and failure reason, and continue processing remaining candidates
5. THE Trade_Plan SHALL be surfaced in the scan results table as an expandable detail row per stock, visible only for tickers where trade_plan is not null
6. THE Trade_Plan SHALL be included in the downloadable scan report alongside the ticker's score and indicator breakdown

### Requirement 12: OHLC Data Availability (High/Low Extension)

**User Story:** As a developer, I want StockData to carry high and low arrays, so that the Trade Engine can compute ATR and swing highs/lows without making additional API calls.

#### Acceptance Criteria

1. THE StockData model SHALL include highs and lows fields as numpy float64 arrays of the same length as the existing prices, volumes, and timestamps fields
2. WHEN fetching stock data from the Polygon bars API, THE RestApiClient SHALL populate highs from the h field and lows from the l field of each bar in the API response, preserving the same element order as prices and volumes
3. THE Trade_Engine SHALL compute ATR and resistance values using only the highs, lows, and prices arrays already present in the StockData instance, without issuing additional HTTP requests to obtain high/low data
4. IF highs or lows arrays are empty (length zero), THEN THE Trade_Engine SHALL reject plan generation for that ticker regardless of any other conditions; IF highs or lows arrays are non-empty but contain fewer than 14 elements, THEN THE Trade_Engine SHALL also reject plan generation and return an error indicating insufficient high/low data for ATR computation with the actual element count
5. WHEN the RestApiClient successfully returns a StockData instance, THE highs array SHALL contain values where each element is greater than or equal to the corresponding element in lows at the same index

### Requirement 13: Calibration Backtest Validation

**User Story:** As a developer, I want a walk-forward backtest that validates trade plan quality, so that probability claims are empirically grounded and expectancy is confirmed positive.

#### Acceptance Criteria

1. WHEN the calibration backtest is executed, THE Backtest_Runner SHALL build a trade plan for every historical BUY_Candidate in the sample period using a minimum of 200 trading days of historical data
2. THE Backtest_Runner SHALL walk forward 30 trading days bar-by-bar using path-dependent first-touch logic (whichever of stop or target1 is hit first), and SHALL classify any trade where neither stop nor target1 is hit within 30 trading days as "undecided" with a result of 0R
3. THE Backtest_Runner SHALL compute target1-before-stop hit rate (excluding undecided trades from the denominator) and verify it exceeds the breakeven rate implied by the R-multiple, calculated as 1 divided by (1 plus the reward-risk ratio) (greater than 33 percent for a 2:1 plan)
4. THE Backtest_Runner SHALL split the sample period into 70 percent in-sample (earlier dates) and 30 percent out-of-sample (later dates), compute expectancy in R-units on each split, and verify expectancy is greater than zero on both periods with a minimum of 30 resolved trades per period
5. THE Backtest_Runner SHALL group candidates into buckets by score band (each 10-point band from 0-100) and ATR band (low, medium, high based on terciles), and verify that realized target1-before-stop hit rate matches prob_hit_target1 claims within a tolerance of plus or minus 5 percentage points per bucket
6. IF the hit rate or expectancy fails to meet required thresholds on either period, THEN THE Backtest_Runner SHALL report the failing metric, its actual value, the required threshold, and the affected period, and SHALL NOT produce a Calibration_Table; IF some metrics pass and others fail, THE Backtest_Runner SHALL NOT produce a partial Calibration_Table and SHALL report all failing metrics
7. WHEN all validation thresholds pass, THE Backtest_Runner SHALL produce the Calibration_Table containing one row per bucket with columns: bucket identifier, sample size, realized hit rate, mean expectancy in R-units, and the prob_hit_target1 value consumed by Requirement 7

### Requirement 14: ATR-Multiple and Target-Multiple Parameter Sweep

**User Story:** As a developer, I want to sweep atr_mult and target multiples, so that I can select the operating point with the best expectancy without overfitting.

#### Acceptance Criteria

1. WHEN the parameter sweep is executed, THE Backtest_Runner SHALL test atr_mult values from 1.5 to 3.0 in steps of 0.5 combined with target1 multiples from 1.5 to 3.0 in steps of 0.5, producing 16 parameter combinations
2. THE Backtest_Runner SHALL split the historical candidate data into in-sample (first 70% by date) and out-of-sample (remaining 30% by date) segments using a temporal split to prevent look-ahead bias
3. THE Backtest_Runner SHALL report expectancy in R-units for each of the 16 parameter combinations on in-sample data, excluding any combination that produced fewer than 30 trades from the selection process
4. THE Backtest_Runner SHALL report the selected operating point expectancy on out-of-sample data, flagging potential overfitting when out-of-sample expectancy is less than 50% of in-sample expectancy
5. THE Backtest_Runner SHALL select the parameter combination with the highest in-sample expectancy that also shows positive (greater than 0R) out-of-sample expectancy
6. IF no parameter combination shows positive out-of-sample expectancy, THEN THE Backtest_Runner SHALL report that no viable operating point was found and output the full results grid without selecting a default combination

### Requirement 15: Earnings-Window Subset Validation

**User Story:** As a developer, I want to compare plan performance with and without earnings in the window, so that I can confirm the earnings flag captures real elevated variance.

#### Acceptance Criteria

1. WHEN the earnings validation is executed, THE Backtest_Runner SHALL partition historical plans into two subsets: plans where an earnings date falls within the 30-day horizon (earnings-in-window) and plans where no earnings date falls within the horizon (no-earnings), requiring a minimum of 30 plans in each subset for the comparison to proceed
2. THE Backtest_Runner SHALL compute for each subset: hit rate (percentage of plans where price reached target1 before stop) and expectancy (mean reward in R-multiples per plan)
3. THE Backtest_Runner SHALL compute and report the sample variance of realized 30-day returns for each subset, outputting both variance values and the ratio of earnings-in-window variance to no-earnings variance
4. THE Backtest_Runner SHALL confirm that the earnings-in-window subset exhibits a return variance at least 1.2 times greater than the no-earnings subset
5. IF the earnings-in-window variance is less than 1.2 times the no-earnings variance, THEN THE Backtest_Runner SHALL flag the earnings flag as uncalibrated and report the actual variance ratio
6. IF either subset contains fewer than 30 plans, THEN THE Backtest_Runner SHALL skip the variance comparison and report an insufficient-data warning indicating the subset name and actual plan count

### Requirement 16: Unit Tests (Backend)

**User Story:** As a developer, I want comprehensive unit tests for every Trade Engine component, so that each function is verified in isolation with deterministic synthetic data and no network dependency.

#### Acceptance Criteria

1. THE test suite SHALL include unit tests in `tests/unit/test_trade_engine.py` covering the TradeEngine class with at minimum the following test cases:
   - ATR computation correctness on known OHLC data (hand-calculated expected values)
   - ATR with fewer than 15 bars raises appropriate error
   - Stop price equals entry minus atr_mult times ATR when not capped
   - Stop price capped at entry times (1 minus MAX_LOSS_PCT) when ATR-derived stop exceeds the floor
   - risk_per_share greater than zero for all valid inputs
   - risk_per_share rejection (error) when entry equals or is below stop
   - target1 and target2 at correct R-multiples of risk
   - target1 less than target2 invariant holds
   - TARGET1_MULT >= TARGET2_MULT configuration rejected with error
   - reward_risk equals TARGET1_MULT (within floating-point epsilon) before earnings widen
   - low_rr flag set correctly at threshold boundary (MIN_REWARD_RISK minus epsilon vs plus epsilon)
   - expected_move_pct equals daily_sigma times sqrt(horizon) times 100 for historical branch
   - vol_source set to "options_iv" when valid options_move supplied, "historical" otherwise
   - None options_move never raises, falls back to historical
   - resistance equals max of 60-day high and 252-day high
   - target_above_resistance flag true iff target1 strictly greater than resistance
   - resistance never mutates target1 or target2
   - earnings_in_window set when earnings_date within horizon
   - earnings_in_window null when earnings_date outside horizon or None
   - earnings widen: target2 and expected_move_pct increase, target1 unchanged
   - prob_hit_target1 reduced (not increased) when earnings_in_window set, floored at 0.05
   - prob_hit_target1 lookup from calibration table with known bucket
   - prob_hit_target1 defaults to 0.50 with calibration_available false when bucket missing
   - analyst fields pass through when supplied, null when not supplied
2. THE test suite SHALL include unit tests in `tests/unit/test_massive_client.py` covering the MassiveDataClient class with at minimum:
   - Earnings endpoint: parse valid JSON response with multiple earnings dates, return list
   - Earnings endpoint: empty response returns empty list
   - Earnings endpoint: HTTP 403/404/500 returns None (logged, no exception)
   - Earnings endpoint: network timeout returns None
   - Options endpoint: parse response with at least 5 ATM contracts, return volume-weighted IV
   - Options endpoint: fewer than 5 valid contracts returns None (fallback)
   - Options endpoint: HTTP error returns None
   - Consensus endpoint: parse valid response with price targets, return mean/low/high
   - Consensus endpoint: empty result returns None
   - Consensus endpoint: timeout returns None
   - Retry behavior: 5xx triggers retry (up to 3 attempts), 4xx does not retry
3. THE test suite SHALL include unit tests in `tests/unit/test_trade_calibration.py` covering the CalibrationTable class:
   - Lookup with known bucket returns stored probability
   - Lookup with unknown bucket returns None
   - Load from JSON file with valid schema succeeds
   - Load from JSON file with missing/corrupt data raises descriptive error
4. THE test suite SHALL include property-based tests in `tests/property/test_trade_engine_properties.py` using hypothesis with at minimum:
   - P1: For all valid OHLC inputs, stop is less than entry AND risk_per_share greater than 0 AND stop never below entry times (1 minus max_loss_pct)
   - P2: target1 equals entry plus target1_R times risk (within epsilon) AND reward_risk equals target1_R (within epsilon)
   - P3: target_above_resistance is true if and only if target1 strictly greater than resistance
   - P4: low_rr is true if and only if reward_risk less than min_reward_risk
   - P5: When earnings_in_window is set, target2 and expected_move are strictly greater than the no-earnings case AND prob_hit_target1 is not greater than the no-earnings case
   - P6: vol_source equals "options_iv" if and only if a valid (non-None, positive) options_move was supplied
   - P7: prob_hit_target1 comes from calibration table or is the default 0.50 (never an ad hoc computation)
   - P9: ATR equals mean of last 14 true ranges AND expected_move_pct equals sigma_daily times sqrt(horizon) times 100 in historical branch
5. ALL unit tests SHALL run without network access (all HTTP calls mocked using httpx mock transport or pytest monkeypatch)
6. ALL unit tests SHALL pass with pytest in under 30 seconds total execution time
7. THE unit test coverage for `core/trade_engine.py`, `core/massive_client.py`, and `core/trade_calibration.py` SHALL exceed 90 percent line coverage

### Requirement 17: Integration Tests (Backend)

**User Story:** As a developer, I want integration tests that verify the Trade Engine works correctly within the scan pipeline, so that I can confirm the orchestrator wiring, API response format, and end-to-end data flow are correct.

#### Acceptance Criteria

1. THE test suite SHALL include integration tests in `tests/integration/test_trade_engine_integration.py` covering the orchestrator-to-trade-engine pipeline:
   - A scan with mock API data returns TickerScore objects where BUY candidates have trade_plan populated and non-candidates have trade_plan as null
   - The trade_plan field in the JSON response conforms to the TradePlan Pydantic schema (all required fields present, types correct)
   - A scan where all tickers fail hard filters returns zero trade plans (all null)
   - A scan where Massive enhancement data (earnings/options/analyst) is unavailable still returns valid core trade plans with vol_source "historical" and null analyst fields
   - The orchestrator batches Massive calls only for the candidate set (verified via mock call counts)
2. THE test suite SHALL include integration tests in `tests/integration/test_trade_plan_endpoint.py` testing the API endpoint directly:
   - POST /scan with valid tickers returns 200 with trade_plan fields on candidates
   - The trade_plan JSON includes all required fields: entry, stop, stop_pct, target1, target1_pct, target2, target2_pct, risk_per_share, reward_risk, expected_move_pct, vol_source, resistance, target_above_resistance, low_rr, earnings_in_window, prob_hit_target1, analyst_target, analyst_low, analyst_high
   - The trade_plan numeric fields are within valid ranges (stop less than entry, targets greater than entry, reward_risk positive, prob between 0 and 1)
   - When include_all is true, non-candidate tickers show trade_plan as null with other fields populated
   - Error responses (invalid tickers, server errors) do not expose trade plan internal errors to the client
3. THE test suite SHALL include integration tests in `tests/integration/test_massive_client_integration.py` with one live smoke test per endpoint (gated behind POLYGON_TOKEN presence):
   - Earnings endpoint for a known ticker (AAPL) returns parseable results with date fields
   - Options chain endpoint for a known ticker returns contracts with implied_volatility fields
   - Consensus endpoint for a known ticker returns price target data
   - Each smoke test is marked with `@pytest.mark.skipif` when POLYGON_TOKEN is not set
4. ALL integration tests SHALL use FastAPI TestClient (httpx-based) for endpoint tests
5. ALL integration tests (except live smoke tests) SHALL mock external Polygon/Massive API calls using respx or httpx mock transport
6. THE integration test suite SHALL pass in under 60 seconds total

### Requirement 18: End-to-End Tests (Playwright)

**User Story:** As a developer, I want Playwright E2E tests that verify the Trade Engine UI renders correctly in the browser, so that I can confirm trade plans display properly with all fields, badges, and interactions working.

#### Acceptance Criteria

1. THE E2E test suite SHALL include a test file `tests/e2e/trade-plan-display.spec.ts` with the following scenarios:
   - Given a scan returns candidates with trade plans, WHEN the results table loads, THEN each candidate row shows a "Trade Plan" expand trigger (button or icon)
   - WHEN the user clicks the expand trigger on a candidate row, THEN an expanded detail section appears showing: entry price, stop price (with loss percentage), target1 (with gain percentage), target2 (with gain percentage), reward:risk ratio, expected move percentage, and probability percentage
   - WHEN a trade plan has target_above_resistance true, THEN a visual indicator (badge or icon) appears next to the target1 value indicating resistance overhead
   - WHEN a trade plan has low_rr true, THEN a warning indicator appears next to the reward:risk value
   - WHEN a trade plan has earnings_in_window set, THEN a warning badge displays "Earnings on YYYY-MM-DD" with a distinct visual style (amber/orange)
   - WHEN a trade plan has vol_source "options_iv", THEN the expected move section shows an "IV" label; when "historical", it shows "Hist"
   - WHEN a trade plan has analyst_target populated, THEN the analyst price range (low-target-high) is displayed as a secondary reference
   - WHEN a trade plan has analyst_target null, THEN no analyst section is rendered (no empty space or "N/A")
   - WHEN the user collapses the expanded section, THEN it returns to the compact row view without page reload
2. THE E2E test suite SHALL include a test file `tests/e2e/trade-plan-report.spec.ts` with the following scenarios:
   - Given a scan with trade plans is complete, WHEN the user clicks the download report button, THEN an HTML file is downloaded
   - The downloaded HTML report contains a "Trade Plan" section with columns for entry, stop, target1, target2, R:R, expected move, and probability for each candidate
   - The report includes the earnings warning text for tickers with earnings_in_window set
   - The report includes resistance annotation for tickers with target_above_resistance true
3. THE E2E test suite SHALL include a test file `tests/e2e/trade-plan-edge-cases.spec.ts` with the following scenarios:
   - WHEN a scan returns zero candidates (bearish regime or all filtered), THEN no trade plan sections appear and no expand triggers are visible
   - WHEN a candidate has trade_plan null (plan computation failed), THEN the row shows a "Plan unavailable" message instead of the expand trigger
   - WHEN the backend returns an error during the scan, THEN the error message displays without broken trade plan UI elements
   - WHEN a scan is in progress (loading state), THEN no stale trade plan data from a previous scan is visible
4. ALL E2E tests SHALL use route interception (page.route) to mock the backend API response with realistic trade plan fixtures (no live backend required for CI)
5. ALL E2E tests SHALL capture screenshots at key assertion points for visual regression review (stored in `test-results/screenshots/`)
6. ALL E2E tests SHALL run headless in CI and pass in under 120 seconds total
7. THE E2E test fixtures SHALL include at minimum:
   - A fixture with 3 candidates: one with earnings_in_window, one with target_above_resistance, one with low_rr (covers all badge types in one scan)
   - A fixture with vol_source "options_iv" on at least one ticker and "historical" on another
   - A fixture with analyst data on some tickers and null on others
   - A fixture with zero candidates (empty ranked_tickers array)
