import { test, expect } from '@playwright/test';

/**
 * Clicking a ticker opens the Stock Intelligence modal; entitled sections render,
 * unavailable (premium) sections show "Unavailable on the current data plan".
 * Deterministic via route-mock.
 */
const sig = {
  price_above_sma50: true, price_above_ema20: true, macd_above_signal: true,
  macd_histogram_positive: true, volume_above_average: false, relative_strength_positive: true,
};

test('ticker click opens intelligence modal with sections + unavailable handling', async ({ page }) => {
  await page.route('**/api/v1/scan', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        scan_id: 's1', market_regime: 'bullish', score_threshold: 65,
        ranked_tickers: [
          { ticker: 'AAA', bullish_score: 82, signals: sig, current_price: 150, indicators: {} },
        ],
        metadata: { timestamp: new Date().toISOString(), ticker_count: 1, duration_seconds: 0.2 },
      }),
    });
  });

  await page.route('**/api/v1/intelligence/AAA', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ticker: 'AAA',
        generated_utc: new Date().toISOString(),
        news: [{ title: 'AAA soars', publisher: 'Investing', published_utc: '2026-06-30T00:00:00Z', article_url: 'https://x', description: 'd', sentiment: 'positive', sentiment_reasoning: 'why' }],
        insider_trades: [{ owner_name: 'CEO', action: 'buy', shares: 1000, price: 148.5, transaction_date: '2026-06-24' }],
        short_interest: { settlement_date: '2026-06-15', short_interest: 1000000, avg_daily_volume: 500000, days_to_cover: 2.0 },
        dividends: [{ ex_dividend_date: '2026-05-01', pay_date: '2026-05-15', cash_amount: 0.24, frequency: 4, currency: 'USD' }],
        macro: { as_of: '2026-06-29', yield_1y: 3.97, yield_5y: 4.14, yield_10y: 4.38, cpi: 333.9 },
        analyst: null, earnings: [], fundamentals: null,
        unavailable: ['analyst', 'earnings', 'fundamentals'],
      }),
    });
  });

  await page.goto('/');
  await page.locator('input[placeholder*="ticker"]').fill('AAA');
  await page.locator('button:has-text("Run Scan")').click();

  // Click the ticker to open the modal
  await page.getByTestId('intel-open-AAA').click();
  await expect(page.getByText('Stock Intelligence — AAA')).toBeVisible({ timeout: 15000 });

  // Entitled sections render
  await expect(page.getByText('AAA soars')).toBeVisible();
  await expect(page.getByText(/2\.00 days to cover/)).toBeVisible();
  await expect(page.getByText(/10y yield: /)).toBeVisible();

  // Premium sections show unavailable (not fake data)
  await expect(page.getByText('Unavailable on the current data plan').first()).toBeVisible();

  await page.screenshot({ path: 'test-results/screenshots/intelligence-modal.png', fullPage: true });
});
