import { useState } from "react";
import AppLayout from "@cloudscape-design/components/app-layout";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Input from "@cloudscape-design/components/input";
import Tabs from "@cloudscape-design/components/tabs";
import Button from "@cloudscape-design/components/button";
import Toggle from "@cloudscape-design/components/toggle";
import Slider from "@cloudscape-design/components/slider";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import "@cloudscape-design/global-styles/index.css";

import ScanButton from "./components/ScanButton";
import ScanProgress from "./components/ScanProgress";
import MarketRegimeBadge from "./components/MarketRegimeBadge";
import ResultsTable from "./components/ResultsTable";
import ErrorMessage from "./components/ErrorMessage";
import BacktestPanel from "./components/BacktestPanel";
import { executeScan, getHalalUniverse } from "./services/scanApi";
import { downloadScanReport } from "./utils/scanReport";
import type { ScanResponse } from "./types/scan";

function App() {
  const [tickers, setTickers] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [halalCount, setHalalCount] = useState<number | null>(null);
  const [loadingHalal, setLoadingHalal] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [hideOverbought, setHideOverbought] = useState(false);
  const [scanStartTime, setScanStartTime] = useState<number>(0);
  const [scanTickerCount, setScanTickerCount] = useState<number>(0);

  const loadAllHalal = async () => {
    setLoadingHalal(true);
    setError(null);
    try {
      const { tickers, count } = await getHalalUniverse();
      setTickers(tickers.join(","));
      setHalalCount(count);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the halal universe");
    } finally {
      setLoadingHalal(false);
    }
  };

  const handleScan = async () => {
    // Validate input
    if (!tickers.trim()) {
      setError("Please enter at least one ticker symbol");
      return;
    }

    setLoading(true);
    setError(null);
    setResults(null);

    try {
      // Parse tickers from input (comma or space separated)
      const tickerList = tickers
        .split(/[,\s]+/)
        .map((t) => t.trim().toUpperCase())
        .filter((t) => t.length > 0);

      if (tickerList.length === 0) {
        setLoading(false);
        setError("Please enter at least one valid ticker symbol");
        return;
      }

      setScanTickerCount(tickerList.length);
      setScanStartTime(Date.now());

      // Execute scan
      const data = await executeScan(tickerList, showAll);
      setResults(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (event: CustomEvent<{ key: string }>) => {
    if (event.detail.key === "Enter" && !loading) {
      handleScan();
    }
  };

  return (
    <AppLayout
      content={
        <ContentLayout
          header={
            <Header
              variant="h1"
              description="Analyze technical indicators to identify potentially bullish stocks"
            >
              Bullish Stock Scanner
            </Header>
          }
        >
          <Tabs
            tabs={[
              {
                label: "Live Scanner",
                id: "scanner",
                content: (
                  <SpaceBetween size="l">
                    <Container>
                      <SpaceBetween size="m">
                        <SpaceBetween size="xs" direction="horizontal">
                          <Button variant="link" onClick={() => setTickers("AAPL,MSFT,NVDA,GOOGL,TSLA,AVGO,LLY,JNJ,UNH,HD,COST,PFE,ABBV,TMO,ORCL,ADBE,CRM,NKE,CSCO,PG")}>Top 20 Halal</Button>
                          <Button variant="link" onClick={() => setTickers("AAPL,MSFT,NVDA,GOOGL,TSLA,AVGO,LLY,JNJ,UNH,PFE,ABBV,TMO,ABT,DHR,MRK,HD,COST,TGT,NKE,PG,KO,PEP,WMT,ORCL,ADBE,CRM,CSCO,AMD,QCOM,TXN,AMAT,BA,CAT,DE,UPS,HON,XOM,CVX,COP,LIN,APD,V,MA,PYPL,DDOG,CRWD,PANW,NOW,TSM,IBM")}>Top 50 Halal</Button>
                          <Button variant="link" onClick={() => setTickers("AAPL,MSFT,NVDA,GOOGL,AVGO,ORCL,ADBE,CRM,CSCO,AMD,QCOM,TXN,AMAT,LRCX,KLAC,MRVL,NXPI,ADI,TSM,IBM,DDOG,CRWD,PANW,NET,NOW")}>Tech</Button>
                          <Button variant="link" onClick={() => setTickers("LLY,JNJ,UNH,PFE,ABBV,TMO,ABT,DHR,MRK,BMY,AMGN,GILD,REGN,VRTX,ISRG")}>Healthcare</Button>
                          <Button variant="link" onClick={() => setTickers("XOM,CVX,COP,SLB,EOG,PSX,MPC,VLO,OXY,HAL")}>Energy</Button>
                          <Button
                            variant="link"
                            iconName="download"
                            loading={loadingHalal}
                            onClick={loadAllHalal}
                          >
                            All Halal Stocks{halalCount ? ` (${halalCount})` : ""}
                          </Button>
                        </SpaceBetween>
                        <Input
                          value={tickers}
                          onChange={({ detail }) => setTickers(detail.value)}
                          placeholder="Enter ticker symbols (e.g., AAPL, MSFT, GOOGL)"
                          disabled={loading}
                          onKeyDown={handleKeyPress}
                        />
                        <ScanButton onClick={handleScan} loading={loading} />
                        <Toggle
                          checked={showAll}
                          onChange={({ detail }) => setShowAll(detail.checked)}
                          description="Show every scanned stock with its status (Candidate / Below threshold / Failed filters), not just buy candidates."
                        >
                          Show all scanned stocks
                        </Toggle>
                      </SpaceBetween>
                    </Container>

                    {error && <ErrorMessage message={error} onDismiss={() => setError(null)} />}

                    {loading && <ScanProgress tickerCount={scanTickerCount} startTime={scanStartTime} />}

                    {results && (() => {
                      const shown = results.ranked_tickers.filter(
                        (t) =>
                          t.bullish_score >= minScore &&
                          !(hideOverbought && t.entry_timing?.zone === "overbought")
                      );
                      const overboughtCount = results.ranked_tickers.filter(
                        (t) => t.entry_timing?.zone === "overbought"
                      ).length;
                      const avg =
                        shown.length > 0
                          ? Math.round(
                              shown.reduce((s, t) => s + t.bullish_score, 0) / shown.length
                            )
                          : 0;
                      return (
                        <SpaceBetween size="m">
                          <MarketRegimeBadge regime={results.market_regime} />
                          <Container>
                            <SpaceBetween size="s">
                              <SpaceBetween size="xs" direction="horizontal">
                                <Box variant="awsui-key-label" data-testid="scan-summary">
                                  Showing {shown.length} of {results.ranked_tickers.length} ·
                                  avg score {avg} · regime {results.market_regime}
                                  {results.score_threshold ? ` (BUY ≥ ${results.score_threshold})` : ""}
                                </Box>
                                <Button
                                  iconName="download"
                                  data-testid="download-scan-report"
                                  disabled={results.ranked_tickers.length === 0}
                                  onClick={() => downloadScanReport(results)}
                                >
                                  Download Report
                                </Button>
                              </SpaceBetween>
                              <FormField label={`Minimum score: ${minScore}`}>
                                <Slider
                                  value={minScore}
                                  onChange={({ detail }) => setMinScore(detail.value)}
                                  min={0}
                                  max={100}
                                  step={5}
                                />
                              </FormField>
                              <Toggle
                                checked={hideOverbought}
                                onChange={({ detail }) => setHideOverbought(detail.checked)}
                                description={
                                  overboughtCount > 0
                                    ? `Hide ${overboughtCount} stock(s) in the overbought / profit-taking risk zone (RSI>70, stretched above average, or parabolic).`
                                    : "No overbought stocks in these results."
                                }
                              >
                                🔴 Hide overbought stocks
                              </Toggle>
                            </SpaceBetween>
                          </Container>
                          <ResultsTable
                            tickers={shown}
                            regime={results.market_regime}
                            scoreThreshold={results.score_threshold}
                          />
                        </SpaceBetween>
                      );
                    })()}
                  </SpaceBetween>
                ),
              },
              {
                label: "Backtest",
                id: "backtest",
                content: <BacktestPanel />,
              },
            ]}
          />
        </ContentLayout>
      }
      navigationHide
      toolsHide
    />
  );
}

export default App;
