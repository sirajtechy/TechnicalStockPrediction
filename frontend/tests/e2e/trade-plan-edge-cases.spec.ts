import { test, expect } from '@playwright/test';

/**
 * E2E tests for Trade Plan Edge Cases (Requirement 18.3).
 * Covers: zero candidates (bearish), null trade_plan, backend errors, stale data.
 */

const sig = {
  price_above_sma50: true,
  price_above_ema20: true,
  macd_above_signal: true,
  macd_histogram_positive: true,
  volume_above_average: true,
  relative_strength_positive: true,
};

// Fixture 4: zero candidates (bearish regime, empty ranked_tickers)
const fixtureZeroCandidates = {
  scan_id: 'tp-edge-1',
  market_regime: 'bearish' as const,
  score_threshold: null,
  ranked_tickers: [],
  metadata: { timestamp: new Date().toISOString(), ticker_count: 0, duration_seconds: 0.3 },
};

// Fixture 5: candidate with trade_plan = null (plan failed)
const fixtureNullPlan = {
  scan_id: 'tp-edge-2',
  market_regime: 'bullish' as const,
  score_threshold: 65,
  ranked_tickers: [
    {
      ticker: 'FAILPLN',
      bullish_score: 75,
      signals: sig,
      current_price: 25.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 16, momentum: 14, strength: 13, confirmation: 16, stage_pattern: 16 },
      trade_plan: null,
    },
    {
      ticker: 'GOODPLN',
      bullish_score: 80,
      signals: sig,
      current_price: 60.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 18, momentum: 16, strength: 14, confirmation: 16, stage_pattern: 16 },
      trade_plan: {
        entry: 60.0,
        stop: 55.0,
        stop_pct: -8.33,
        target1: 70.0,
        target1_pct: 16.67,
        target2: 75.0,
        target2_pct: 25.0,
        risk_per_share: 5.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 11.0,
        vol_source: 'historical' as const,
        resistance: 72.0,
        target_above_resistance: false,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.55,
        calibration_available: true,
        analyst_target: null,
        analyst_low: null,
        analyst_high: null,
      },
    },
  ],
  metadata: { timestamp: new Date().toISOString(), ticker_count: 2, duration_seconds: 0.9 },
};

// Normal results fixture for stale data test
const fixtureFirstScan = {
  scan_id: 'tp-edge-3a',
  market_regime: 'bullish' as const,
  score_threshold: 65,
  ranked_tickers: [
    {
      ticker: 'FIRST',
      bullish_score: 82,
      signals: sig,
      current_price: 100.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 18, momentum: 16, strength: 14, confirmation: 18, stage_pattern: 16 },
      trade_plan: {
        entry: 100.0,
        stop: 92.0,
        stop_pct: -8.0,
        target1: 116.0,
        target1_pct: 16.0,
        target2: 124.0,
        target2_pct: 24.0,
        risk_per_share: 8.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 12.0,
        vol_source: 'options_iv' as const,
        resistance: 115.0,
        target_above_resistance: true,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.58,
        calibration_available: true,
        analyst_target: null,
        analyst_low: null,
        analyst_high: null,
      },
    },
  ],
  metadata: { timestamp: new Date().toISOString(), ticker_count: 1, duration_seconds: 0.5 },
};

test.describe('Trade Plan Edge Cases — Requirement 18.3', () => {
  test('zero candidates (bearish regime) shows no trade plan sections', async ({ page }) => {
    await page.route('**/api/v1/scan', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixtureZeroCandidates),
      });
    });

    await page.goto('/');
    await page.locator('input[placeholder*="ticker"]').fill('SPY');
    await page.locator('button:has-text("Run Scan")').click();

    // Wait for the empty state to render
    const emptyState = page.getByTestId('results-empty');
    await expect(emptyState).toBeVisible({ timeout: 15000 });

    // Should mention bearish market
    await expect(emptyState).toContainText('bearish');

    // No trade plan expand triggers should exist
    const tradePlanElements = page.locator('[data-testid^="trade-plan-expand-"]');
    await expect(tradePlanElements).toHaveCount(0);

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-edge-01-zero-candidates.png', fullPage: true });
  });

  test('candidate with trade_plan null shows "Plan unavailable"', async ({ page }) => {
    await page.route('**/api/v1/scan', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixtureNullPlan),
      });
    });

    await page.goto('/');
    await page.locator('input[placeholder*="ticker"]').fill('FAILPLN,GOODPLN');
    await page.locator('button:has-text("Run Scan")').click();

    // Wait for results table
    await page.locator('table').waitFor({ timeout: 15000 });

    // FAILPLN should show "Plan unavailable" (trade_plan = null)
    const failDetail = page.getByTestId('trade-plan-detail-FAILPLN');
    await expect(failDetail).toBeVisible();
    await expect(failDetail).toContainText('Plan unavailable');

    // GOODPLN should have an expandable trade plan
    const goodExpand = page.getByTestId('trade-plan-expand-GOODPLN');
    await expect(goodExpand).toBeVisible();

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-edge-02-null-plan.png', fullPage: true });
  });

  test('backend error displays error message without broken trade plan UI', async ({ page }) => {
    await page.route('**/api/v1/scan', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await page.goto('/');
    await page.locator('input[placeholder*="ticker"]').fill('ERROR');
    await page.locator('button:has-text("Run Scan")').click();

    // Wait for error message to appear
    const errorAlert = page.locator('[role="alert"]');
    await expect(errorAlert).toBeVisible({ timeout: 15000 });

    // No trade plan elements should be visible
    const tradePlanElements = page.locator('[data-testid^="trade-plan-expand-"]');
    await expect(tradePlanElements).toHaveCount(0);

    // No results table either
    const table = page.locator('table');
    await expect(table).not.toBeVisible();

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-edge-03-backend-error.png', fullPage: true });
  });

  test('loading state shows no stale trade plan data from previous scan', async ({ page }) => {
    let requestCount = 0;

    await page.route('**/api/v1/scan', async (route) => {
      requestCount++;
      if (requestCount === 1) {
        // First scan returns immediately with data
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(fixtureFirstScan),
        });
      } else {
        // Second scan takes a while (simulate loading)
        await new Promise((resolve) => setTimeout(resolve, 2000));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(fixtureZeroCandidates),
        });
      }
    });

    await page.goto('/');

    // First scan — get results with trade plans
    await page.locator('input[placeholder*="ticker"]').fill('FIRST');
    await page.locator('button:has-text("Run Scan")').click();
    await page.locator('table').waitFor({ timeout: 15000 });

    // Verify first scan data is visible
    const firstExpand = page.getByTestId('trade-plan-expand-FIRST');
    await expect(firstExpand).toBeVisible();

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-edge-04-first-scan.png', fullPage: true });

    // Second scan — while loading, no stale data should show
    await page.locator('input[placeholder*="ticker"]').fill('SPY');
    await page.locator('button:has-text("Run Scan")').click();

    // During loading, old trade plan data from FIRST should not be visible
    // The app clears results when starting a new scan
    await expect(firstExpand).not.toBeVisible({ timeout: 5000 });

    // No trade plan expand triggers from previous scan
    const stalePlanElements = page.locator('[data-testid^="trade-plan-expand-"]');
    await expect(stalePlanElements).toHaveCount(0);

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-edge-05-no-stale-data.png', fullPage: true });
  });
});
