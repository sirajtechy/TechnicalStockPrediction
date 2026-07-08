// Types for the Stock Intelligence bundle (GET /api/v1/intelligence/{ticker}).

export interface NewsItem {
  title: string | null;
  publisher: string | null;
  published_utc: string | null;
  article_url: string | null;
  description: string | null;
  sentiment: "positive" | "negative" | "neutral" | null;
  sentiment_reasoning: string | null;
}

export interface InsiderTrade {
  owner_name: string | null;
  is_director: boolean | null;
  is_officer: boolean | null;
  is_ten_percent_owner: boolean | null;
  transaction_date: string | null;
  transaction_code: string | null;
  action: string | null; // buy / sell / exercise / grant / ...
  shares: number | null;
  price: number | null;
  value: number | null;
}

export interface ShortInterest {
  settlement_date: string | null;
  short_interest: number | null;
  avg_daily_volume: number | null;
  days_to_cover: number | null;
}

export interface ShortVolume {
  date: string | null;
  short_volume: number | null;
  total_volume: number | null;
  short_volume_ratio: number | null; // % of daily volume sold short
}

export interface Dividend {
  ex_dividend_date: string | null;
  pay_date: string | null;
  cash_amount: number | null;
  frequency: number | null;
  currency: string | null;
}

export interface Macro {
  as_of: string | null;
  yield_1y: number | null;
  yield_5y: number | null;
  yield_10y: number | null;
  cpi: number | null;
}

export interface AnalystConsensus {
  rating?: string | null;
  price_target_mean?: number | null;
  price_target_low?: number | null;
  price_target_high?: number | null;
  analyst_count?: number | null;
  target?: number | null;
  low?: number | null;
  high?: number | null;
}

// Real Benzinga /benzinga/v1/earnings schema (raw dicts flow through unchanged).
export interface AnalystInsight {
  date: string | null;
  firm: string | null;
  rating: string | null;
  rating_action: string | null; // upgrades | downgrades | maintains | initiates_coverage_on | ...
  price_target: number | null;
  insight: string | null; // narrative rationale
}

export interface EarningsRow {
  date: string | null;
  date_status: string | null; // projected | confirmed
  fiscal_period: string | null; // Q1, Q2, H1, FY, ...
  time: string | null; // HH:MM:SS EST
  actual_eps: number | null;
  estimated_eps: number | null;
  eps_surprise_percent: number | null;
  actual_revenue: number | null;
  estimated_revenue: number | null;
}

export interface Fundamentals {
  pe_ratio: number | null;
  price_to_sales: number | null;
  gross_margin: number | null;
  net_margin: number | null;
  debt_to_equity: number | null;
}

export interface StockIntelligence {
  ticker: string;
  generated_utc: string;
  news: NewsItem[];
  insider_trades: InsiderTrade[];
  short_interest: ShortInterest | null;
  short_volume: ShortVolume | null;
  dividends: Dividend[];
  macro: Macro | null;
  analyst: AnalystConsensus | null;
  analyst_insights: AnalystInsight[];
  earnings: EarningsRow[];
  fundamentals: Fundamentals | null;
  /** Section names that could not be fetched (403/error) — show "unavailable", never fake. */
  unavailable: string[];
}
