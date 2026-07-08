// Type definitions for the Bullish Stock Scanner

export type MarketRegime = "bullish" | "bearish" | "neutral";

export interface TradePlan {
  entry: number;
  stop: number;
  stop_pct: number;
  target1: number;
  target1_pct: number;
  target2: number;
  target2_pct: number;
  risk_per_share: number;
  reward_risk: number | null;
  low_rr: boolean;
  data_unavailable: boolean;
  expected_move_pct: number | null;
  vol_source: "options_iv" | "historical";
  resistance: number;
  target_above_resistance: boolean;
  resistance_data_limited: boolean;
  earnings_in_window: string | null;
  prob_hit_target1: number | null;
  calibration_available: boolean;
  analyst_target: number | null;
  analyst_low: number | null;
  analyst_high: number | null;
}

export interface IndicatorSignals {
  price_above_sma50: boolean;
  price_above_ema20: boolean;
  macd_above_signal: boolean;
  macd_histogram_positive: boolean;
  volume_above_average: boolean;
  relative_strength_positive: boolean;
}

export type EntryZone = "buy_zone" | "extended" | "overbought";

export interface EntryTiming {
  zone: EntryZone;
  label: string;
  reasons: string[];
  rsi: number | null;
  dist_above_sma50_pct: number | null;
  proximity_to_high: number | null;
  roc_10: number | null;
}

export interface TickerScore {
  ticker: string;
  bullish_score: number;
  signals: IndicatorSignals;
  current_price: number;
  indicators: {
    sma_50?: number | null;
    ema_20?: number | null;
    macd_line?: number | null;
    macd_signal?: number | null;
    macd_histogram?: number | null;
    avg_volume_20?: number | null;
    relative_strength?: number | null;
  };
  // V3 diagnostic fields (present when include_all is requested)
  passed_hard_filters?: boolean | null;
  is_candidate?: boolean | null;
  // Per-component point contributions (trend/momentum/strength/confirmation/stage_pattern/penalties).
  score_breakdown?: Record<string, number> | null;
  // Trade plan for BUY candidates (null for non-candidates or plan failure)
  trade_plan?: TradePlan | null;
  // Entry timing zone (buy_zone / extended / overbought) — profit-taking risk warning
  entry_timing?: EntryTiming | null;
}

export interface ScanMetadata {
  timestamp: string;
  ticker_count: number;
  duration_seconds: number;
}

export interface ScanResponse {
  scan_id: string;
  market_regime: MarketRegime;
  ranked_tickers: TickerScore[];
  metadata: ScanMetadata;
  score_threshold?: number | null;
}

export interface ScanRequest {
  tickers: string[];
  include_all?: boolean;
}
