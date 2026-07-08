import { test, expect } from '@playwright/test';

/**
 * E2E tests for Trade Plan in Downloaded Report (Requirement 18.2).
 * Verifies the HTML report download includes trade plan data with correct content.
 */

const sig = {
  price_above_sma50: true,
  price_above_ema20: true,
  macd_above_signal: true,
  macd_histogram_positive: true,
  volume_above_average: true,
  relative_strength_positive: true,
};

// Fixture with trade plans including earnings and resistance annotations
const fixtureReport = {
  scan_id: 'tp-report-1',
  market_regime: 'bullish' as const,
  score_threshold: 65,
  ranked_tickers: [
    {
      ticker: 'EARNTK',
      bullish_score: 80,
      signals: sig,
      current_price: 100.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 18, momentum: 16, strength: 14, confirmation: 16, stage_pattern: 16 },
      trade_plan: {
        entry: 100.0,
        stop: 92.0,
        stop_pct: -8.0,
        target1: 116.0,
        target1_pct: 16.0,
        target2: 132.0,
        target2_pct: 32.0,
        risk_per_share: 8.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 14.5,
        vol_source: 'options_iv' as const,
        resistance: 120.0,
        target_above_resistance: false,
        resistance_data_limited: false,
        earnings_in_window: '2025-03-10',
        prob_hit_target1: 0.48,
        calibration_available: true,
        analyst_target: 125.0,
        analyst_low: 110.0,
        analyst_high: 140.0,
      },
    },
    {
      ticker: 'RESTK',
      bullish_score: 76,
      signals: sig,
      current_price: 50.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 16, momentum: 14, strength: 14, confirmation: 16, stage_pattern: 16 },
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
        expected_move_pct: 10.0,
        vol_source: 'historical' as const,
        resistance: 55.0,
        target_above_resistance: true,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.60,
        calibration_available: true,
        analyst_target: null,
        analyst_low: null,
        analyst_high: null,
      },
    },
    {
      ticker: 'NORMTK',
      bullish_score: 72,
      signals: sig,
      current_price: 80.0,
      indicators: {},
      passed_hard_filters: true,
      is_candidate: true,
      score_breakdown: { trend: 14, momentum: 14, strength: 12, confirmation: 16, stage_pattern: 16 },
      trade_plan: {
        entry: 80.0,
        stop: 74.0,
        stop_pct: -7.5,
        target1: 92.0,
        target1_pct: 15.0,
        target2: 98.0,
        target2_pct: 22.5,
        risk_per_share: 6.0,
        reward_risk: 2.0,
        low_rr: false,
        data_unavailable: false,
        expected_move_pct: 9.8,
        vol_source: 'historical' as const,
        resistance: 95.0,
        target_above_resistance: false,
        resistance_data_limited: false,
        earnings_in_window: null,
        prob_hit_target1: 0.55,
        calibration_available: true,
        analyst_target: 95.0,
        analyst_low: 85.0,
        analyst_high: 105.0,
      },
    },
  ],
  metadata: { timestamp: new Date().toISOString(), ticker_count: 3, duration_seconds: 1.0 },
};

test.describe('Trade Plan Report — Requirement 18.2', () => {
  test('clicking download triggers HTML file download', async ({ page }) => {
    await page.route('**/api/v1/scan', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixtureReport),
      });
    });

    await page.goto('/');
    await page.locator('input[placeholder*="ticker"]').fill('EARNTK,RESTK,NORMTK');
    await page.locator('button:has-text("Run Scan")').click();

    const downloadBtn = page.getByTestId('download-scan-report');
    await expect(downloadBtn).toBeVisible({ timeout: 15000 });

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-report-01-before-download.png', fullPage: true });

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      downloadBtn.click(),
    ]);

    expect(download.suggestedFilename()).toMatch(/^scan-report-\d{4}-\d{2}-\d{2}\.html$/);
  });

  test('downloaded report contains Trade Plan section with entry/stop/target1/target2/R:R/expected move/probability', async ({ page }) => {
    await page.route('**/api/v1/scan', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixtureReport),
      });
    });

    await page.goto('/');
    await page.locator('input[placeholder*="ticker"]').fill('EARNTK,RESTK,NORMTK');
    await page.locator('button:has-text("Run Scan")').click();

    const downloadBtn = page.getByTestId('download-scan-report');
    await expect(downloadBtn).toBeVisible({ timeout: 15000 });

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      downloadBtn.click(),
    ]);

    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const c of stream) chunks.push(c as Buffer);
    const html = Buffer.concat(chunks).toString('utf-8');

    // Report should have Trade Plan section header
    expect(html).toContain('Trade Plan');

    // EARNTK plan data
    expect(html).toContain('EARNTK');
    expect(html).toContain('100.00'); // entry
    expect(html).toContain('92.00');  // stop
    expect(html).toContain('116.00'); // target1
    expect(html).toContain('132.00'); // target2
    expect(html).toContain('2.00');   // R:R
    expect(html).toContain('14.50');  // expected move
    expect(html).toContain('48.00');  // probability (0.48 * 100)

    // RESTK plan data
    expect(html).toContain('RESTK');
    expect(html).toContain('58.00');  // target1
    expect(html).toContain('62.00');  // target2

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-report-02-download-verified.png', fullPage: true });
  });

  test('report includes earnings warning text for tickers with earnings_in_window', async ({ page }) => {
    await page.route('**/api/v1/scan', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixtureReport),
      });
    });

    await page.goto('/');
    await page.locator('input[placeholder*="ticker"]').fill('EARNTK');
    await page.locator('button:has-text("Run Scan")').click();

    const downloadBtn = page.getByTestId('download-scan-report');
    await expect(downloadBtn).toBeVisible({ timeout: 15000 });

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      downloadBtn.click(),
    ]);

    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const c of stream) chunks.push(c as Buffer);
    const html = Buffer.concat(chunks).toString('utf-8');

    // Should contain the earnings date warning
    expect(html).toContain('2025-03-10');
    // The earnings row should have special styling class
    expect(html).toContain('tp-row-earnings');

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-report-03-earnings-warning.png', fullPage: true });
  });

  test('report includes resistance annotation for tickers with target_above_resistance', async ({ page }) => {
    await page.route('**/api/v1/scan', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixtureReport),
      });
    });

    await page.goto('/');
    await page.locator('input[placeholder*="ticker"]').fill('RESTK');
    await page.locator('button:has-text("Run Scan")').click();

    const downloadBtn = page.getByTestId('download-scan-report');
    await expect(downloadBtn).toBeVisible({ timeout: 15000 });

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      downloadBtn.click(),
    ]);

    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const c of stream) chunks.push(c as Buffer);
    const html = Buffer.concat(chunks).toString('utf-8');

    // RESTK has target_above_resistance = true, so resistance cell should have warning class
    expect(html).toContain('tp-warn');
    expect(html).toContain('55.00'); // resistance price
    expect(html).toContain('⚠');    // warning symbol

    await page.screenshot({ path: 'test-results/screenshots/trade-plan-report-04-resistance-annotation.png', fullPage: true });
  });
});
