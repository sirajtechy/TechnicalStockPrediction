import { useEffect, useState } from "react";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import Badge from "@cloudscape-design/components/badge";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Header from "@cloudscape-design/components/header";
import Spinner from "@cloudscape-design/components/spinner";
import Link from "@cloudscape-design/components/link";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { getStockIntelligence } from "../services/scanApi";
import type { StockIntelligence } from "../types/intelligence";

interface Props {
  ticker: string | null;
  onClose: () => void;
}

const sentimentColor = (s: string | null): "green" | "red" | "grey" =>
  s === "positive" ? "green" : s === "negative" ? "red" : "grey";

function Section({
  title,
  unavailable,
  empty,
  children,
}: {
  title: string;
  unavailable: boolean;
  empty: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div data-testid={`intel-section-${title.toLowerCase().replace(/\W+/g, "-")}`}>
      <Header variant="h3">{title}</Header>
      {unavailable ? (
        <StatusIndicator type="info">
          Unavailable on the current data plan
        </StatusIndicator>
      ) : empty ? (
        <Box color="text-status-inactive">No data.</Box>
      ) : (
        children
      )}
    </div>
  );
}

/** A clean, professional modal presenting all intelligence for one stock. */
export default function StockIntelligenceModal({ ticker, onClose }: Props) {
  const [data, setData] = useState<StockIntelligence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    setData(null);
    setError(null);
    setLoading(true);
    getStockIntelligence(ticker)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [ticker]);

  const un = (name: string) => data?.unavailable.includes(name) ?? false;

  return (
    <Modal
      visible={ticker !== null}
      onDismiss={onClose}
      size="large"
      header={`🔍 Stock Intelligence — ${ticker ?? ""}`}
      data-testid="intel-modal"
    >
      {loading && (
        <Box textAlign="center" padding="l">
          <Spinner size="large" /> Loading intelligence…
        </Box>
      )}
      {error && <StatusIndicator type="error">{error}</StatusIndicator>}
      {data && (
        <SpaceBetween size="l">
          {/* News + sentiment */}
          <Section title="News &amp; Sentiment" unavailable={un("news")} empty={data.news.length === 0}>
            <SpaceBetween size="s">
              {data.news.map((n, i) => (
                <div key={i} style={{ borderLeft: "3px solid #e6ebf1", paddingLeft: 12 }}>
                  <SpaceBetween size="xxs" direction="horizontal">
                    {n.sentiment && <Badge color={sentimentColor(n.sentiment)}>{n.sentiment}</Badge>}
                    <Box variant="small" color="text-status-inactive">
                      {n.publisher} · {n.published_utc?.slice(0, 10)}
                    </Box>
                  </SpaceBetween>
                  <Box variant="p">
                    {n.article_url ? (
                      <Link href={n.article_url} external>
                        {n.title}
                      </Link>
                    ) : (
                      n.title
                    )}
                  </Box>
                </div>
              ))}
            </SpaceBetween>
          </Section>

          {/* Key metrics grid */}
          <ColumnLayout columns={4} variant="text-grid">
            <Section title="Short Interest" unavailable={un("short_interest")} empty={!data.short_interest}>
              {data.short_interest && (
                <SpaceBetween size="xxs">
                  <Box><b>{(data.short_interest.days_to_cover ?? 0).toFixed(2)}</b> days to cover</Box>
                  <Box variant="small">{((data.short_interest.short_interest ?? 0) / 1e6).toFixed(1)}M shares short</Box>
                  <Box variant="small" color="text-status-inactive">as of {data.short_interest.settlement_date}</Box>
                </SpaceBetween>
              )}
            </Section>

            <Section title="Short Volume" unavailable={un("short_volume")} empty={!data.short_volume}>
              {data.short_volume && (
                <SpaceBetween size="xxs">
                  <Box><b>{(data.short_volume.short_volume_ratio ?? 0).toFixed(1)}%</b> of volume sold short</Box>
                  <Box variant="small" color="text-status-inactive">as of {data.short_volume.date}</Box>
                </SpaceBetween>
              )}
            </Section>

            <Section title="Analyst Target" unavailable={un("analyst")} empty={!data.analyst}>
              {data.analyst && (
                <SpaceBetween size="xxs">
                  {data.analyst.rating && (
                    <Badge color={/buy/i.test(data.analyst.rating) ? "green" : /sell/i.test(data.analyst.rating) ? "red" : "grey"}>
                      {data.analyst.rating.replace(/_/g, " ")}
                    </Badge>
                  )}
                  <Box>
                    <b>${(data.analyst.price_target_mean ?? data.analyst.target ?? 0).toFixed(2)}</b> target
                  </Box>
                  <Box variant="small">
                    ${(data.analyst.price_target_low ?? data.analyst.low ?? 0).toFixed(0)} – $
                    {(data.analyst.price_target_high ?? data.analyst.high ?? 0).toFixed(0)}
                    {data.analyst.analyst_count ? ` · ${data.analyst.analyst_count} analysts` : ""}
                  </Box>
                </SpaceBetween>
              )}
            </Section>

            <Section title="Macro" unavailable={un("macro")} empty={!data.macro}>
              {data.macro && (
                <SpaceBetween size="xxs">
                  <Box variant="small">10y yield: <b>{data.macro.yield_10y}%</b></Box>
                  <Box variant="small">CPI: {data.macro.cpi}</Box>
                </SpaceBetween>
              )}
            </Section>
          </ColumnLayout>

          {/* Insider trades */}
          <Section title="Insider Trades" unavailable={un("insider_trades")} empty={data.insider_trades.length === 0}>
            <SpaceBetween size="xxs">
              {data.insider_trades.slice(0, 6).map((t, i) => (
                <Box key={i} variant="small">
                  <Badge color={t.action === "buy" ? "green" : t.action === "sell" ? "red" : "grey"}>
                    {t.action}
                  </Badge>{" "}
                  {t.owner_name} · {t.shares?.toLocaleString()} sh
                  {t.price != null ? ` @ $${t.price.toFixed(2)}` : ""} · {t.transaction_date}
                </Box>
              ))}
            </SpaceBetween>
          </Section>

          {/* Analyst insights — per-firm rating actions with rationale */}
          <Section
            title="Analyst Insights"
            unavailable={un("analyst_insights")}
            empty={data.analyst_insights.length === 0}
          >
            <SpaceBetween size="s">
              {data.analyst_insights.slice(0, 4).map((a, i) => (
                <div key={i} style={{ borderLeft: "3px solid #e6ebf1", paddingLeft: 12 }}>
                  <SpaceBetween size="xxs" direction="horizontal">
                    {a.rating && (
                      <Badge
                        color={
                          /buy|outperform|overweight/i.test(a.rating)
                            ? "green"
                            : /sell|underperform|underweight/i.test(a.rating)
                              ? "red"
                              : "grey"
                        }
                      >
                        {a.rating}
                      </Badge>
                    )}
                    <Box variant="small" color="text-status-inactive">
                      {a.firm}
                      {a.rating_action ? ` · ${a.rating_action.replace(/_/g, " ")}` : ""}
                      {a.price_target != null ? ` · $${a.price_target.toFixed(0)} PT` : ""}
                      {a.date ? ` · ${a.date}` : ""}
                    </Box>
                  </SpaceBetween>
                  {a.insight && (
                    <Box variant="small">
                      {a.insight.length > 280 ? `${a.insight.slice(0, 280)}…` : a.insight}
                    </Box>
                  )}
                </div>
              ))}
            </SpaceBetween>
          </Section>

          {/* Dividends + Earnings + Fundamentals */}
          <ColumnLayout columns={3} variant="text-grid">
            <Section title="Dividends" unavailable={un("dividends")} empty={data.dividends.length === 0}>
              {data.dividends[0] && (
                <SpaceBetween size="xxs">
                  <Box><b>${data.dividends[0].cash_amount}</b> / share</Box>
                  <Box variant="small">ex-date {data.dividends[0].ex_dividend_date}</Box>
                </SpaceBetween>
              )}
            </Section>

            <Section title="Earnings" unavailable={un("earnings")} empty={data.earnings.length === 0}>
              {data.earnings[0] && (
                <SpaceBetween size="xxs">
                  <Box><b>{data.earnings[0].date}</b> ({data.earnings[0].date_status})</Box>
                  <Box variant="small">EPS est: {data.earnings[0].estimated_eps ?? "—"}</Box>
                  {data.earnings[0].actual_eps != null && (
                    <Box variant="small">
                      EPS actual: {data.earnings[0].actual_eps}
                      {data.earnings[0].eps_surprise_percent != null
                        ? ` (${data.earnings[0].eps_surprise_percent > 0 ? "+" : ""}${data.earnings[0].eps_surprise_percent.toFixed(1)}%)`
                        : ""}
                    </Box>
                  )}
                </SpaceBetween>
              )}
            </Section>

            <Section title="Fundamentals" unavailable={un("fundamentals")} empty={!data.fundamentals}>
              {data.fundamentals && (
                <SpaceBetween size="xxs">
                  <Box variant="small">P/E: {data.fundamentals.pe_ratio ?? "—"}</Box>
                  <Box variant="small">Net margin: {data.fundamentals.net_margin ?? "—"}</Box>
                </SpaceBetween>
              )}
            </Section>
          </ColumnLayout>

          <Box variant="small" color="text-status-inactive" textAlign="center">
            Data via Massive. Sections marked "unavailable" require the corresponding data
            entitlement on your plan. Generated {data.generated_utc.slice(0, 19)}Z.
          </Box>
        </SpaceBetween>
      )}
    </Modal>
  );
}
