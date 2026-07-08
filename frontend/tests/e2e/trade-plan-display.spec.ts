import { test, expect } from '@playwright/test';

/**
 * E2E tests for Trade Plan Display (Requirement 18.1).
 * All tests mock the backend API via route interception with realistic fixtures.
 */

// --- Shared signal object for fixture brevity ---
const sig = {
  price_above_sma50: true,
  price_above_ema20: true,
  macd_above_signal: true,
  macd_histogram_positive: true,
  volume_above_average: true,
  relative_strength_positive: true,
};

// --- Fixture 1: 3 candidates — earnings, resistance, low_rr ---
const fixtureCandidates = {
  scan_id: 'tp-display-1',
  market_regime: 'bullish' as const,
  score_threshold: 65,
  ranked_tickers: [
    {
      ticker: 'EARN',
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
        target2: 130.0,
        target2_pct: 30.0,
        risk_per_share: 8.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 12.5,
        vol_source: 'options_iv' as const,
        resistance: 120.0,
        target_above_resistance: false,
        resistance_data_limited: false,
        earnings_in_window: '2025-02-15',
        prob_hit_target1: 0.55,
        calibration_available: true,
        analyst_target: 125.0,
        analyst_low: 110.0,
        analyst_high: 140.0,
      },
    },
    {
      ticker: 'RESIST',
      bullish_score: 78,
      signals: sig,
      current_price: 50.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 16, momentum: 14, strength: 14, confirmation: 18, stage_pattern: 16 },
      trade_plan: {
        entry: 50.0,
        stop: 46.0,
        stop_pct: -8.0,
        target1: 58.0,
        target1_pct: 16.0,
        target2: 62.0,
        target2_pct: 24.0,
        risk_per_share: 4.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 10.2,
        vol_source: 'historical' as const,
        resistance: 55.0,
        target_above_resistance: true,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.62,
        calibration_available: true,
        analyst_target: null,
        analyst_low: null,
        analyst_high: null,
      },
    },
    {
      ticker: 'LOWRR',
      bullish_score: 70,
      signals: sig,
      current_price: 200.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 14, momentum: 14, strength: 12, confirmation: 16, stage_pattern: 14 },
      trade_plan: {
        entry: 200.0,
        stop: 188.0,
        stop_pct: -6.0,
        target1: 214.0,
        target1_pct: 7.0,
        target2: 224.0,
        target2_pct: 12.0,
        risk_per_share: 12.0,
        reward_risk: 1.17,
        low_rr: true,
        data_unavailable: false,
        expected_move_pct: 8.3,
        vol_source: 'historical' as const,
        resistance: 220.0,
        target_above_resistance: false,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.48,
        calibration_available: true,
        analyst_target: 230.0,
        analyst_low: 210.0,
        analyst_high: 250.0,
      },
    },
  ],
  metadata: { timestamp: new Date().toISOString(), ticker_count: 3, duration_seconds: 1.2 },
};

// --- Fixture 2: vol_source variants ---
const fixtureVolSource = {
  scan_id: 'tp-display-2',
  market_regime: 'bullish' as const,
  score_threshold: 65,
  ranked_tickers: [
    {
      ticker: 'IVTK',
      bullish_score: 80,
      signals: sig,
      current_price: 75.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 18, momentum: 16, strength: 14, confirmation: 16, stage_pattern: 16 },
      trade_plan: {
        entry: 75.0,
        stop: 69.0,
        stop_pct: -8.0,
        target1: 87.0,
        target1_pct: 16.0,
        target2: 93.0,
        target2_pct: 24.0,
        risk_per_share: 6.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 11.0,
        vol_source: 'options_iv' as const,
        resistance: 90.0,
        target_above_resistance: false,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.58,
        calibration_available: true,
        analyst_target: null,
        analyst_low: null,
        analyst_high: null,
      },
    },
    {
      ticker: 'HISTTK',
      bullish_score: 72,
      signals: sig,
      current_price: 30.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 14, momentum: 14, strength: 12, confirmation: 16, stage_pattern: 16 },
      trade_plan: {
        entry: 30.0,
        stop: 27.0,
        stop_pct: -10.0,
        target1: 36.0,
        target1_pct: 20.0,
        target2: 39.0,
        target2_pct: 30.0,
        risk_per_share: 3.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 9.5,
        vol_source: 'historical' as const,
        resistance: 38.0,
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
  metadata: { timestamp: new Date().toISOString(), ticker_count: 2, duration_seconds: 0.8 },
};

// --- Fixture 3: analyst data on some tickers, null on others ---
const fixtureAnalyst = {
  scan_id: 'tp-display-3',
  market_regime: 'bullish' as const,
  score_threshold: 65,
  ranked_tickers: [
    {
      ticker: 'ANLST',
      bullish_score: 85,
      signals: sig,
      current_price: 60.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 18, momentum: 18, strength: 14, confirmation: 18, stage_pattern: 17 },
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
        expected_move_pct: 11.5,
        vol_source: 'options_iv' as const,
        resistance: 72.0,
        target_above_resistance: false,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.60,
        calibration_available: true,
        analyst_target: 75.0,
        analyst_low: 65.0,
        analyst_high: 85.0,
      },
    },
    {
      ticker: 'NOANLST',
      bullish_score: 74,
      signals: sig,
      current_price: 40.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 14, momentum: 14, strength: 14, confirmation: 16, stage_pattern: 16 },
      trade_plan: {
        entry: 40.0,
        stop: 36.0,
        stop_pct: -10.0,
        target1: 48.0,
        target1_pct: 20.0,
        target2: 52.0,
        target2_pct: 30.0,
        risk_per_share: 4.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 9.0,
        vol_source: 'historical' as const,
        resistance: 50.0,
        target_above_resistance: false,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.52,
        calibration_available: true,
        analyst_target: null,
        analyst_low: null,
        analyst_high: null,
      },
    },
  ],
  metadata: { timestamp: new Date().toISOString(), ticker_count: 2, duration_seconds: 0.7 },
};

// Helper: mock the scan endpoint and trigger a scan
async function setupScanWithFixture(page: import('@playwright/test').Page, fixture: object) {
  await page.route('**/api/v1/scan', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixture),
    });
  });

  await page.goto('/');
  await page.locator('input[placeholder*="ticker"]').fill('TEST');
  await page.locator('button:has-text("Run Scan")').click();

  // Wait for results table to appear
  await page.locator('table').waitFor({ timeout: 15000 });
}

test.describe('Trade Plan Display — Requirement 18.1', () => {
  test('each candidate row shows a Trade Plan expand trigger', async ({ page }) => {
    await setupScanWithFixture(page, fixtureCandidates);

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-display-01-table.png', fullPage: true });

    // Each candidate should have a trade plan expand trigger
    for (const ticker of ['EARN', 'RESIST', 'LOWRR']) {
      const expandTrigger = page.getByTestId(`trade-plan-expand-${ticker}`);
      await expect(expandTrigger).toBeVisible();
    }
  });

  test('expanded detail shows entry, stop, target1, target2, R:R, expected move, probability', async ({ page }) => {
    await setupScanWithFixture(page, fixtureCandidates);

    // Expand the EARN trade plan
    const expandSection = page.getByTestId('trade-plan-expand-EARN');
    await expandSection.locator('button, [role="button"]').first().click();

    // Wait for the detail to render
    const detail = page.getByTestId('trade-plan-detail-EARN');
    await expect(detail).toBeVisible();

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-display-02-expanded.png', fullPage: true });

    // Verify all key fields are present
    await expect(detail).toContainText('$100.00'); // entry
    await expect(detail).toContainText('$92.00');  // stop
    await expect(detail).toContainText('-8.0%');   // stop_pct
    await expect(detail).toContainText('$116.00'); // target1
    await expect(detail).toContainText('16.0%');   // target1_pct
    await expect(detail).toContainText('$130.00'); // target2
    await expect(detail).toContainText('30.0%');   // target2_pct
    await expect(detail).toContainText('2.00');    // R:R
    await expect(detail).toContainText('12.5%');   // expected move
    await expect(detail).toContainText('55%');     // probability (0.55 * 100)
  });

  test('target_above_resistance shows resistance warning badge', async ({ page }) => {
    await setupScanWithFixture(page, fixtureCandidates);

    // Expand RESIST ticker (has target_above_resistance = true)
    const expandSection = page.getByTestId('trade-plan-expand-RESIST');
    await expandSection.locator('button, [role="button"]').first().click();

    const resistanceBadge = page.getByTestId('trade-plan-resistance-badge-RESIST');
    await expect(resistanceBadge).toBeVisible();
    await expect(resistanceBadge).toContainText('Target above resistance');

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-display-03-resistance-badge.png', fullPage: true });
  });

  test('low_rr shows low R:R warning', async ({ page }) => {
    await setupScanWithFixture(page, fixtureCandidates);

    // Expand LOWRR ticker (has low_rr = true)
    const expandSection = page.getByTestId('trade-plan-expand-LOWRR');
    await expandSection.locator('button, [role="button"]').first().click();

    const lowRrBadge = page.getByTestId('trade-plan-low-rr-badge-LOWRR');
    await expect(lowRrBadge).toBeVisible();
    await expect(lowRrBadge).toContainText('Low R:R');

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-display-04-low-rr-badge.png', fullPage: true });
  });

  test('earnings_in_window shows Earnings badge with date', async ({ page }) => {
    await setupScanWithFixture(page, fixtureCandidates);

    // Expand EARN ticker (has earnings_in_window = '2025-02-15')
    const expandSection = page.getByTestId('trade-plan-expand-EARN');
    await expandSection.locator('button, [role="button"]').first().click();

    const earningsBadge = page.getByTestId('trade-plan-earnings-badge-EARN');
    await expect(earningsBadge).toBeVisible();
    await expect(earningsBadge).toContainText('Earnings on 2025-02-15');

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-display-05-earnings-badge.png', fullPage: true });
  });

  test('vol_source options_iv shows IV label; historical shows Hist label', async ({ page }) => {
    await setupScanWithFixture(page, fixtureVolSource);

    // Expand IVTK (vol_source = "options_iv")
    const expandIv = page.getByTestId('trade-plan-expand-IVTK');
    await expandIv.locator('button, [role="button"]').first().click();
    const detailIv = page.getByTestId('trade-plan-detail-IVTK');
    await expect(detailIv).toBeVisible();
    await expect(detailIv).toContainText('IV');

    // Expand HISTTK (vol_source = "historical")
    const expandHist = page.getByTestId('trade-plan-expand-HISTTK');
    await expandHist.locator('button, [role="button"]').first().click();
    const detailHist = page.getByTestId('trade-plan-detail-HISTTK');
    await expect(detailHist).toBeVisible();
    await expect(detailHist).toContainText('Hist');

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-display-06-vol-source.png', fullPage: true });
  });

  test('analyst_target populated shows analyst range; null shows no analyst section', async ({ page }) => {
    await setupScanWithFixture(page, fixtureAnalyst);

    // Expand ANLST (has analyst data)
    const expandAnlst = page.getByTestId('trade-plan-expand-ANLST');
    await expandAnlst.locator('button, [role="button"]').first().click();
    const detailAnlst = page.getByTestId('trade-plan-detail-ANLST');
    await expect(detailAnlst).toBeVisible();
    await expect(detailAnlst).toContainText('Analyst');
    await expect(detailAnlst).toContainText('$65.00');
    await expect(detailAnlst).toContainText('$75.00');
    await expect(detailAnlst).toContainText('$85.00');

    // Expand NOANLST (analyst_target = null)
    const expandNoAnlst = page.getByTestId('trade-plan-expand-NOANLST');
    await expandNoAnlst.locator('button, [role="button"]').first().click();
    const detailNoAnlst = page.getByTestId('trade-plan-detail-NOANLST');
    await expect(detailNoAnlst).toBeVisible();
    // Should NOT contain analyst label in that section (no analyst data)
    await expect(detailNoAnlst).not.toContainText('Analyst');

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-display-07-analyst.png', fullPage: true });
  });

  test('collapsing an expanded section returns to compact view', async ({ page }) => {
    await setupScanWithFixture(page, fixtureCandidates);

    // Expand EARN
    const expandSection = page.getByTestId('trade-plan-expand-EARN');
    const toggleButton = expandSection.locator('button, [role="button"]').first();
    await toggleButton.click();

    const detail = page.getByTestId('trade-plan-detail-EARN');
    await expect(detail).toBeVisible();

    // Collapse it
    await toggleButton.click();

    // Detail should no longer be visible (collapsed)
    await expect(detail).not.toBeVisible();

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-display-08-collapsed.png', fullPage: true });
  });
});
