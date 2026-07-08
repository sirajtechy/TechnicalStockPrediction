import { useMemo, useState } from "react";
import Table, { type TableProps } from "@cloudscape-design/components/table";
import Badge from "@cloudscape-design/components/badge";
import Header from "@cloudscape-design/components/header";
import Box from "@cloudscape-design/components/box";
import Popover from "@cloudscape-design/components/popover";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Link from "@cloudscape-design/components/link";
import type { TickerScore, MarketRegime } from "../types/scan";
import SignalBadges from "./SignalBadges";
import TradePlanDetail from "./TradePlanDetail";
import StockIntelligenceModal from "./StockIntelligenceModal";

interface ResultsTableProps {
  tickers: TickerScore[];
  regime?: MarketRegime;
  scoreThreshold?: number | null;
}

type RankedTicker = TickerScore & { rank: number };

// Human labels + display order for the score-breakdown components.
const BREAKDOWN_ORDER: [string, string][] = [
  ["trend", "Trend"],
  ["momentum", "Momentum"],
  ["strength", "Strength"],
  ["confirmation", "Confirmation"],
  ["stage_pattern", "Stage + Pattern"],
  ["extension_penalty", "Extension penalty"],
  ["climax_penalty", "Climax penalty"],
  ["divergence_penalty", "Divergence penalty"],
];

// --- Module-scope, pure cell renderers so column definitions stay reference-stable ---
// (Stable columns are required for Cloudscape's click-to-toggle sort direction to work.)

function getScoreColor(score: number): "green" | "blue" | "grey" {
  if (score >= 70) return "green";
  if (score >= 40) return "blue";
  return "grey";
}

function statusBadge(t: TickerScore) {
  if (t.is_candidate) return <Badge color="green">Candidate</Badge>;
  if (t.passed_hard_filters) return <Badge color="blue">Below threshold</Badge>;
  return <Badge color="grey">Failed filters</Badge>;
}

const ENTRY_ZONE_META: Record<
  string,
  { color: "green" | "grey" | "red"; short: string }
> = {
  buy_zone: { color: "green", short: "🟢 Buy Zone" },
  extended: { color: "grey", short: "🟡 Extended" },
  overbought: { color: "red", short: "🔴 Overbought" },
};

function entryTimingBadge(t: TickerScore) {
  const et = t.entry_timing;
  if (!et) return <span style={{ color: "#5f6b7a" }}>—</span>;
  const meta = ENTRY_ZONE_META[et.zone] ?? { color: "grey" as const, short: et.zone };
  const badge = (
    <Badge color={meta.color} data-testid={`entry-zone-${t.ticker}`}>
      {meta.short}
    </Badge>
  );
  return (
    <Popover
      dismissButton={false}
      position="top"
      size="medium"
      triggerType="custom"
      header={et.label}
      content={
        <Box>
          {et.reasons.map((r, i) => (
            <div key={i} style={{ marginBottom: 4 }}>
              • {r}
            </div>
          ))}
          <div style={{ marginTop: 8, fontSize: 12, color: "#5f6b7a" }}>
            {et.rsi != null && `RSI ${et.rsi}`}
            {et.dist_above_sma50_pct != null && ` · ${et.dist_above_sma50_pct}% above SMA50`}
            {et.roc_10 != null && ` · ${et.roc_10}% / 10d`}
          </div>
        </Box>
      }
    >
      <span style={{ cursor: "pointer" }}>{badge}</span>
    </Popover>
  );
}

function scoreBadge(item: TickerScore) {
  const badge = <Badge color={getScoreColor(item.bullish_score)}>{item.bullish_score}</Badge>;
  if (!item.score_breakdown) return badge;
  return (
    <Popover
      dismissButton={false}
      position="top"
      size="medium"
      triggerType="custom"
      header={`${item.ticker} — score ${item.bullish_score}`}
      content={
        <Box>
          {BREAKDOWN_ORDER.filter(([k]) => item.score_breakdown![k] !== undefined).map(([k, label]) => {
            const v = item.score_breakdown![k];
            return (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                <span>{label}</span>
                <span style={{ color: v < 0 ? "#a50e0e" : "#137333", fontWeight: 600 }}>
                  {v > 0 ? `+${v}` : v}
                </span>
              </div>
            );
          })}
        </Box>
      }
    >
      <span style={{ cursor: "pointer" }} data-testid="score-popover-trigger">
        {badge}
      </span>
    </Popover>
  );
}

/** Renders the trade plan expandable section for a candidate row. */
function TradePlanExpandable({ item }: { item: RankedTicker }) {
  if (!item.is_candidate) return null;

  if (item.trade_plan == null) {
    return (
      <div data-testid={`trade-plan-detail-${item.ticker}`}>
        <Box variant="p" color="text-status-inactive">
          Plan unavailable
        </Box>
      </div>
    );
  }

  return (
    <div data-testid={`trade-plan-expand-${item.ticker}`}>
      <ExpandableSection headerText="Trade Plan" variant="footer">
        <TradePlanDetail plan={item.trade_plan} ticker={item.ticker} />
      </ExpandableSection>
    </div>
  );
}

/**
 * Sortable table of ranked tickers. The score cell is a popover that explains the
 * score by component (when the backend supplies a breakdown).
 * Candidate rows include an expandable trade plan detail section.
 */
export default function ResultsTable({ tickers, regime, scoreThreshold }: ResultsTableProps) {
  const showStatus = tickers.some((t) => t.passed_hard_filters != null || t.is_candidate != null);
  const hasTradePlans = tickers.some((t) => t.is_candidate);

  // Ticker whose intelligence modal is open (null = closed).
  const [intelTicker, setIntelTicker] = useState<string | null>(null);

  // Stable column definitions (only the structure depends on showStatus). Keeping these
  // referentially stable is what lets a second header click reverse the sort.
  const columnDefinitions = useMemo(
    () => [
      {
        id: "rank",
        header: "Rank",
        cell: (item: RankedTicker) => <Box textAlign="center">{item.rank}</Box>,
        width: 80,
      },
      {
        id: "ticker",
        header: "Ticker",
        cell: (item: RankedTicker) => (
          <Link
            onFollow={(e) => {
              e.preventDefault();
              setIntelTicker(item.ticker);
            }}
            data-testid={`intel-open-${item.ticker}`}
          >
            <strong>{item.ticker}</strong>
          </Link>
        ),
        sortingComparator: (a: RankedTicker, b: RankedTicker) => a.ticker.localeCompare(b.ticker),
        width: 100,
      },
      {
        id: "score",
        header: "Bullish Score",
        cell: (item: RankedTicker) => scoreBadge(item),
        sortingComparator: (a: RankedTicker, b: RankedTicker) => a.bullish_score - b.bullish_score,
        width: 130,
      },
      ...(showStatus
        ? [
            {
              id: "status",
              header: "Status",
              cell: (item: RankedTicker) => statusBadge(item),
              width: 150,
            },
          ]
        : []),
      {
        id: "price",
        header: "Price",
        cell: (item: RankedTicker) => `$${item.current_price.toFixed(2)}`,
        sortingComparator: (a: RankedTicker, b: RankedTicker) => a.current_price - b.current_price,
        width: 100,
      },
      {
        id: "entry_timing",
        header: "Entry Timing",
        cell: (item: RankedTicker) => entryTimingBadge(item),
        width: 150,
      },
      {
        id: "signals",
        header: "Active Signals",
        cell: (item: RankedTicker) => <SignalBadges signals={item.signals} />,
      },
      ...(hasTradePlans
        ? [
            {
              id: "trade_plan",
              header: "Trade Plan",
              cell: (item: RankedTicker) => <TradePlanExpandable item={item} />,
            },
          ]
        : []),
    ],
    [showStatus, hasTradePlans]
  );

  const [sortingColumn, setSortingColumn] =
    useState<TableProps.SortingColumn<RankedTicker>>();
  const [sortingDescending, setSortingDescending] = useState(false);

  const ranked: RankedTicker[] = useMemo(
    () => tickers.map((ticker, index) => ({ ...ticker, rank: index + 1 })),
    [tickers]
  );

  const sortedItems = useMemo(() => {
    const cmp = sortingColumn?.sortingComparator;
    if (!cmp) return ranked;
    const out = [...ranked].sort(cmp);
    return sortingDescending ? out.reverse() : out;
  }, [ranked, sortingColumn, sortingDescending]);

  return (
    <>
    <Table
      header={
        <Header
          counter={`(${tickers.length})`}
          description={
            showStatus
              ? `All scanned stocks — Candidate = passed hard filters AND score ≥ ${scoreThreshold ?? 65}. Click a ticker for intelligence, a score for its breakdown.`
              : "Click a ticker for intelligence · click a score for its breakdown · click a column to sort"
          }
        >
          {showStatus ? "All Scanned Stocks" : "Ranked Results"}
        </Header>
      }
      columnDefinitions={columnDefinitions}
      items={sortedItems}
      variant="container"
      sortingColumn={sortingColumn}
      sortingDescending={sortingDescending}
      onSortingChange={({ detail }) => {
        setSortingColumn(detail.sortingColumn);
        setSortingDescending(detail.isDescending ?? false);
      }}
      empty={
        <Box textAlign="center" color="inherit" data-testid="results-empty">
          {regime === "bearish" ? (
            <>
              <b>No signals in a bearish market</b>
              <Box variant="p" color="inherit">
                The market is below its 200-day trend, so V3 emits zero buy candidates. Wait for the
                market to recover.
              </Box>
            </>
          ) : (
            <>
              <b>No qualifying candidates</b>
              <Box variant="p" color="inherit">
                No tickers passed the V3 filters and score threshold for this scan.
              </Box>
            </>
          )}
        </Box>
      }
    />
    <StockIntelligenceModal ticker={intelTicker} onClose={() => setIntelTicker(null)} />
    </>
  );
}
