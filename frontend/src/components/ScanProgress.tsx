import { useEffect, useState } from "react";
import Box from "@cloudscape-design/components/box";
import ProgressBar from "@cloudscape-design/components/progress-bar";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Icon from "@cloudscape-design/components/icon";

interface ScanProgressProps {
  tickerCount: number;
  startTime: number; // Date.now() when scan started
}

interface PipelineStage {
  id: string;
  label: string;
  description: string;
  icon: string;
  durationWeight: number; // relative weight for progress estimation
}

const PIPELINE_STAGES: PipelineStage[] = [
  {
    id: "universe",
    label: "Building Universe",
    description: "Validating ticker symbols and filtering halal universe",
    icon: "🔍",
    durationWeight: 0.05,
  },
  {
    id: "regime",
    label: "Analyzing Market Regime",
    description: "Classifying overall market as Bullish, Neutral, or Bearish using SPY",
    icon: "📊",
    durationWeight: 0.10,
  },
  {
    id: "fetch",
    label: "Fetching Price Data",
    description: "Downloading 400 days of OHLCV history per ticker from Polygon",
    icon: "📡",
    durationWeight: 0.40,
  },
  {
    id: "indicators",
    label: "Computing Indicators",
    description: "Calculating SMA, EMA, MACD, RSI, ROC, and Relative Strength",
    icon: "🧮",
    durationWeight: 0.15,
  },
  {
    id: "scoring",
    label: "Scoring & Filtering",
    description: "Applying Minervini hard filters and gradient scoring (0-100 points)",
    icon: "⚡",
    durationWeight: 0.15,
  },
  {
    id: "trade_plans",
    label: "Building Trade Plans",
    description: "Computing ATR stops, R-multiple targets, and probability for candidates",
    icon: "📋",
    durationWeight: 0.10,
  },
  {
    id: "ranking",
    label: "Ranking Results",
    description: "Sorting candidates by bullish score and assembling response",
    icon: "🏆",
    durationWeight: 0.05,
  },
];

const FACTS = [
  "The scanner checks 6 Minervini Trend Template filters before scoring any stock",
  "Scores range from 0-100 across 5 dimensions: Trend, Momentum, Strength, Confirmation, and Stage/Pattern",
  "A stock must be above its 200-day, 150-day, AND 50-day moving averages to qualify",
  "ATR-based stops protect against catastrophic loss while allowing normal market volatility",
  "With a 2:1 reward-risk ratio, you only need to be right 34% of the time to break even",
  "The market regime gate blocks all signals during bearish markets — no false hope",
  "Stage 2 (Weinstein) marks the ideal accumulation-to-advance transition zone",
  "Extension penalties reduce scores for stocks that are too far above their averages",
  "Relative strength is ranked across the entire universe, not just vs. SPY",
  "The scanner uses 252 trading days (1 year) of data for 52-week high/low calculations",
  "Options-implied volatility gives a forward-looking view of expected stock movement",
  "The calibration table maps historical hit rates to each setup bucket (score × ATR band)",
  "Only BUY candidates get trade plans — this keeps API costs bounded to ~8-25 tickers",
  "Every probability claim is backtested: if we say 60%, it actually happened ~60% of the time",
];

function getEstimatedDuration(tickerCount: number): number {
  // Empirical: ~1s per 10 tickers + 2s baseline (regime + setup)
  // Minimum 5s for small scans
  return Math.max(5, Math.ceil(tickerCount / 10) + 2);
}

export default function ScanProgress({ tickerCount, startTime }: ScanProgressProps) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [currentFactIndex, setCurrentFactIndex] = useState(0);

  const estimatedDuration = getEstimatedDuration(tickerCount);

  // Update elapsed time every 500ms
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsedSeconds((Date.now() - startTime) / 1000);
    }, 500);
    return () => clearInterval(timer);
  }, [startTime]);

  // Rotate facts every 4 seconds
  useEffect(() => {
    const factTimer = setInterval(() => {
      setCurrentFactIndex((prev) => (prev + 1) % FACTS.length);
    }, 4000);
    return () => clearInterval(factTimer);
  }, []);

  // Calculate progress percentage (capped at 95% until done)
  const rawProgress = Math.min((elapsedSeconds / estimatedDuration) * 100, 95);
  const progress = Math.round(rawProgress);

  // Determine current stage based on progress
  let cumulativeWeight = 0;
  let currentStageIndex = 0;
  for (let i = 0; i < PIPELINE_STAGES.length; i++) {
    cumulativeWeight += PIPELINE_STAGES[i].durationWeight;
    if (rawProgress / 100 <= cumulativeWeight) {
      currentStageIndex = i;
      break;
    }
    if (i === PIPELINE_STAGES.length - 1) {
      currentStageIndex = i;
    }
  }

  const currentStage = PIPELINE_STAGES[currentStageIndex];
  const remainingSeconds = Math.max(0, Math.ceil(estimatedDuration - elapsedSeconds));

  return (
    <Box padding="l">
      <SpaceBetween size="l">
        {/* Progress bar */}
        <ProgressBar
          value={progress}
          label={`${currentStage.icon} ${currentStage.label}`}
          description={currentStage.description}
          additionalInfo={
            remainingSeconds > 0
              ? `~${remainingSeconds}s remaining · ${tickerCount} tickers`
              : "Finishing up..."
          }
        />

        {/* Pipeline stages */}
        <Box>
          <SpaceBetween size="xxs">
            {PIPELINE_STAGES.map((stage, idx) => {
              let status: "success" | "in-progress" | "pending";
              if (idx < currentStageIndex) status = "success";
              else if (idx === currentStageIndex) status = "in-progress";
              else status = "pending";

              return (
                <div
                  key={stage.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "4px 0",
                    opacity: status === "pending" ? 0.4 : 1,
                    transition: "opacity 0.3s ease",
                  }}
                >
                  <StatusIndicator type={status}>
                    <span style={{ fontSize: "13px" }}>
                      {stage.icon} {stage.label}
                    </span>
                  </StatusIndicator>
                </div>
              );
            })}
          </SpaceBetween>
        </Box>

        {/* Educational fact card */}
        <div
          style={{
            background: "rgba(56, 189, 248, 0.05)",
            borderRadius: "10px",
            padding: "16px 20px",
            borderLeft: "3px solid #38bdf8",
            border: "1px solid rgba(56, 189, 248, 0.15)",
            transition: "all 0.5s ease",
          }}
        >
          <Box variant="small" color="text-body-secondary">
            <Icon name="status-info" /> Did you know?
          </Box>
          <Box
            variant="p"
            margin={{ top: "xxs" }}
            key={currentFactIndex}
            color="text-body-secondary"
          >
            {FACTS[currentFactIndex]}
          </Box>
        </div>

        {/* Elapsed time */}
        <Box textAlign="center" color="text-body-secondary" variant="small">
          Elapsed: {Math.floor(elapsedSeconds)}s
          {elapsedSeconds > estimatedDuration + 5 && (
            <span> — Taking longer than expected (large universe or slow network)</span>
          )}
        </Box>
      </SpaceBetween>
    </Box>
  );
}
