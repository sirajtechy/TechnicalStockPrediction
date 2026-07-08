import Box from "@cloudscape-design/components/box";
import Badge from "@cloudscape-design/components/badge";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import type { TradePlan } from "../types/scan";

interface TradePlanDetailProps {
  plan: TradePlan;
  ticker: string;
}

function formatPct(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

function formatPrice(price: number): string {
  return `$${price.toFixed(2)}`;
}

/**
 * Expandable detail content showing a complete trade plan for a BUY candidate.
 * Displays entry/stop/targets, risk metrics, badges for warnings, and analyst data.
 */
export default function TradePlanDetail({ plan, ticker }: TradePlanDetailProps) {
  const volSourceLabel = plan.vol_source === "options_iv" ? "IV" : "Hist";

  return (
    <div data-testid={`trade-plan-detail-${ticker}`}>
      <SpaceBetween size="xs">
        {/* Row 1: Entry, Stop, Targets */}
        <Box variant="p">
          <strong>Entry:</strong> {formatPrice(plan.entry)} →{" "}
          <strong>Stop:</strong> {formatPrice(plan.stop)} ({formatPct(plan.stop_pct)}) |{" "}
          <strong>Target1:</strong> {formatPrice(plan.target1)} ({formatPct(plan.target1_pct)}) |{" "}
          <strong>Target2:</strong> {formatPrice(plan.target2)} ({formatPct(plan.target2_pct)})
        </Box>

        {/* Row 2: R:R, Expected Move, Probability */}
        <Box variant="p">
          <strong>R:R:</strong> {plan.reward_risk != null ? plan.reward_risk.toFixed(2) : "N/A"} |{" "}
          <strong>Expected Move:</strong>{" "}
          {plan.expected_move_pct != null ? `${plan.expected_move_pct.toFixed(1)}% (${volSourceLabel})` : "N/A"} |{" "}
          <strong>Probability:</strong>{" "}
          {plan.prob_hit_target1 != null ? `${Math.round(plan.prob_hit_target1 * 100)}%` : "N/A"}
        </Box>

        {/* Row 3: Resistance + Analyst */}
        <Box variant="p">
          {plan.target_above_resistance && (
            <span>
              <strong>Resistance:</strong> {formatPrice(plan.resistance)} ⚠ |{" "}
            </span>
          )}
          {plan.analyst_target != null && plan.analyst_low != null && plan.analyst_high != null && (
            <span>
              <strong>Analyst:</strong> {formatPrice(plan.analyst_low)}–{formatPrice(plan.analyst_target)}–{formatPrice(plan.analyst_high)}
            </span>
          )}
        </Box>

        {/* Badges row */}
        <SpaceBetween size="xs" direction="horizontal">
          {plan.earnings_in_window && (
            <span data-testid={`trade-plan-earnings-badge-${ticker}`}>
              <Badge color="blue">⚠ Earnings on {plan.earnings_in_window}</Badge>
            </span>
          )}
          {plan.target_above_resistance && (
            <span data-testid={`trade-plan-resistance-badge-${ticker}`}>
              <StatusIndicator type="warning">Target above resistance ({formatPrice(plan.resistance)})</StatusIndicator>
            </span>
          )}
          {plan.low_rr && (
            <span data-testid={`trade-plan-low-rr-badge-${ticker}`}>
              <StatusIndicator type="warning">Low R:R ({plan.reward_risk?.toFixed(2)})</StatusIndicator>
            </span>
          )}
        </SpaceBetween>
      </SpaceBetween>
    </div>
  );
}
