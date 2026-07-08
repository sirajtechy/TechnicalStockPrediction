# Project Structure

## Current Organization

The project is organized as a full-stack application with separate backend and frontend:

```
TechnicalStockPrediction/
├── .git/                     # Git version control
├── .claude/                  # Claude AI specs (legacy, reference only)
│   └── spec/trade-engine/    # Original trade engine spec (requirement/design/task)
├── .kiro/                    # Kiro AI assistant configuration
│   ├── hooks/                # Agent hooks (auto-triggers)
│   ├── specs/                # Feature specifications
│   │   ├── bullish-stock-scanner/  # V3 scanner spec (complete)
│   │   └── trade-engine/           # Trade engine spec (in progress)
│   └── steering/             # AI guidance documents
├── backend/                  # Python FastAPI backend
├── frontend/                 # React TypeScript frontend
├── .gitignore                # Python and Node gitignore
├── .mcp.json                 # MCP server configuration (Massive API)
├── LICENSE                   # Apache License 2.0
└── README.md                 # Project documentation
```

## Backend Structure

The backend follows a layered architecture with clear separation of concerns:

```
backend/
├── main.py                          # FastAPI application entry point
├── config.py                        # Configuration (env vars, constants)
├── pyproject.toml                   # Ruff/mypy config
├── pytest.ini                       # Pytest config
├── requirements.txt                 # Python dependencies
├── scanner.db                       # SQLite persistence (gitignored in prod)
├── api/                             # API layer
│   ├── __init__.py
│   ├── endpoints.py                 # API route handlers
│   └── models.py                    # Pydantic request/response models
├── core/                            # Business logic layer
│   ├── __init__.py
│   ├── api_client.py                # REST API Client (Polygon aggregates)
│   ├── halal_universe.py            # Curated halal stock universe
│   ├── indicator_calculator.py      # Technical Indicator Calculator
│   ├── models.py                    # Internal data models (StockData, TechnicalIndicators)
│   ├── orchestrator.py              # Scan Orchestrator (pipeline coordination)
│   ├── pattern_detector.py          # Chart pattern detection (cup-with-handle, etc.)
│   ├── ranking_service.py           # Ranking Service (ticker sorting)
│   ├── regime_analyzer.py           # Market Regime Analyzer (SPY-based)
│   ├── scan_store.py                # SQLite persistence for scan results
│   ├── scoring_engine.py            # Scoring Engine V3 (gradient + Minervini)
│   ├── stage_classifier.py          # Weinstein Stage 2 classifier
│   └── universe_builder.py          # Universe Builder (ticker validation)
├── backtest/                        # Backtesting framework
│   ├── __init__.py
│   ├── engine.py                    # Walk-forward backtest engine
│   └── metrics.py                   # Confusion matrix, expectancy, hit rates
├── scripts/                         # Analysis and tuning scripts
│   ├── analyze_fp.py                # False positive analysis
│   ├── trade_plan_proto.py          # Trade plan prototype (validated +0.27R)
│   ├── tune_v3.py                   # V3 scoring parameter tuning
│   └── validate_v3.py              # V3 validation runner
├── utils/                           # Utility layer
│   ├── __init__.py
│   └── logging.py                   # Logging configuration
└── tests/                           # Test suite
    ├── __init__.py
    ├── unit/                        # Unit tests
    │   ├── test_api_client.py
    │   ├── test_endpoints.py
    │   ├── test_halal_universe.py
    │   ├── test_indicator_calculator.py
    │   ├── test_orchestrator.py
    │   ├── test_ranking_service.py
    │   ├── test_regime_analyzer.py
    │   ├── test_scan_store.py
    │   ├── test_scoring_engine.py
    │   └── test_universe_builder.py
    ├── property/                    # Property-based tests (hypothesis)
    │   ├── conftest.py              # Shared strategies
    │   ├── test_api_client_properties.py
    │   ├── test_indicators_properties.py
    │   ├── test_ranking_properties.py
    │   ├── test_regime_properties.py
    │   ├── test_scoring_properties.py
    │   └── test_universe_properties.py
    ├── backtest/                    # Backtest validation tests
    │   ├── test_metrics.py
    │   └── test_predicted_bullish.py
    └── integration/                 # Integration tests
        ├── test_endpoints_integration.py
        ├── test_main.py
        ├── test_scan_endpoint.py
        ├── test_scoring_pipeline.py
        ├── test_universe_api.py
        └── test_v3_pipeline.py
```

## Frontend Structure

The frontend follows a component-based architecture:

```
frontend/
├── package.json                     # Node dependencies and scripts
├── vite.config.ts                   # Vite build configuration
├── tsconfig.json                    # TypeScript configuration
├── tsconfig.app.json                # App TypeScript configuration
├── tsconfig.node.json               # Node TypeScript configuration
├── eslint.config.js                 # ESLint configuration
├── index.html                       # HTML entry point
├── .env                             # Environment variables (gitignored)
├── src/
│   ├── App.tsx                      # Main application component (state management)
│   ├── App.css                      # Application styles
│   ├── main.tsx                     # React entry point
│   ├── index.css                    # Global styles
│   ├── assets/                      # Static assets
│   ├── components/                  # React components
│   │   ├── BacktestPanel.tsx        # Backtest results display
│   │   ├── ErrorMessage.tsx         # Error display
│   │   ├── LoadingIndicator.tsx     # Loading state UI
│   │   ├── MarketRegimeBadge.tsx    # Market regime display
│   │   ├── ResultsTable.tsx         # Ranked ticker table (expandable rows)
│   │   ├── ScanButton.tsx           # Scan trigger button
│   │   └── SignalBadges.tsx         # Indicator signal badges
│   ├── services/                    # API communication
│   │   └── scanApi.ts              # Backend API client
│   ├── types/                       # TypeScript type definitions
│   │   └── scan.ts                  # Scan-related types
│   ├── utils/                       # Utility functions
│   │   └── scanReport.ts           # HTML report generation/download
│   ├── styles/                      # CSS styles
│   └── test/                        # Test utilities
├── tests/                           # Test directory
│   ├── App.test.tsx                 # Component tests
│   └── e2e/                         # End-to-end tests (Playwright)
│       ├── happy-path.spec.ts
│       ├── error-scenarios.spec.ts
│       ├── loading-states.spec.ts
│       ├── results-display.spec.ts
│       └── comprehensive-test.spec.ts
└── playwright.config.ts             # Playwright configuration
```

## Naming Conventions

### Backend (Python)
- **Packages/Modules**: lowercase with underscores (`indicator_calculator`, `api_client`)
- **Classes**: PascalCase (`IndicatorCalculator`, `ScoringEngine`, `MarketRegime`)
- **Functions/Variables**: lowercase with underscores (`calculate_sma`, `bullish_score`)
- **Constants**: uppercase with underscores (`MAX_CONCURRENT_REQUESTS`, `DEFAULT_TICKERS`)
- **Async Functions**: prefix with `async` keyword, name like regular functions

### Frontend (TypeScript/React)
- **Components**: PascalCase (`ResultsTable`, `ScanButton`)
- **Component Files**: PascalCase matching component name (`ResultsTable.tsx`)
- **Functions/Variables**: camelCase (`handleScan`, `tickerScore`)
- **Types/Interfaces**: PascalCase (`ScanResponse`, `TickerScore`)
- **Constants**: UPPER_SNAKE_CASE or camelCase based on scope

## Layered Architecture

### Backend Layers

1. **API Layer** (`api/`): HTTP interface, request/response handling
   - Minimal business logic
   - Input validation with Pydantic
   - Error handling and HTTP status codes

2. **Core Layer** (`core/`): Business logic and domain models
   - Independent of API framework
   - Contains all calculation and processing logic
   - No HTTP or presentation concerns

3. **Utility Layer** (`utils/`): Shared utilities and cross-cutting concerns
   - Logging configuration
   - Common helpers
   - No business logic

### Frontend Layers

1. **Component Layer** (`components/`): UI components
   - Presentation logic only
   - Receives data via props
   - Emits events via callbacks

2. **Service Layer** (`services/`): Business logic and API communication
   - API client functions
   - Data transformation
   - Error handling

3. **Type Layer** (`types/`): TypeScript type definitions
   - Interface definitions
   - Type aliases
   - Enums

## Component Responsibilities

### Backend Components

- **API Client** (`api_client.py`): Polygon aggregates API, retry logic, caching
- **Halal Universe** (`halal_universe.py`): Curated halal-compliant stock list
- **Universe Builder** (`universe_builder.py`): Ticker validation and universe construction
- **Market Regime Analyzer** (`regime_analyzer.py`): SPY-based bullish/bearish/neutral classification
- **Indicator Calculator** (`indicator_calculator.py`): SMA, EMA, MACD, RSI, ROC, RS computation
- **Scoring Engine** (`scoring_engine.py`): V3 gradient scoring with Minervini hard filters, penalties
- **Stage Classifier** (`stage_classifier.py`): Weinstein Stage 2 detection
- **Pattern Detector** (`pattern_detector.py`): Chart pattern recognition (cup-with-handle, etc.)
- **Ranking Service** (`ranking_service.py`): Ticker sorting and ranking
- **Scan Store** (`scan_store.py`): SQLite persistence for scan history
- **Orchestrator** (`orchestrator.py`): Two-pass pipeline coordination
- **Backtest Engine** (`backtest/engine.py`): Walk-forward backtesting with confusion matrix
- **Backtest Metrics** (`backtest/metrics.py`): Hit rate, expectancy, coverage calculations

### Frontend Components

- **App**: Main container, state management, orchestration
- **ScanButton**: User interaction trigger
- **LoadingIndicator**: Async operation feedback
- **MarketRegimeBadge**: Market condition display
- **ResultsTable**: Tabular data with expandable detail rows
- **SignalBadges**: Visual indicator signal representation
- **ErrorMessage**: Error feedback display
- **BacktestPanel**: Backtest results visualization

## File Organization Principles

1. **Separation of Concerns**: API, business logic, and utilities are separated
2. **Single Responsibility**: Each module has one clear purpose
3. **Dependency Direction**: API layer depends on core, core is independent
4. **Testability**: Core logic is easily testable without API infrastructure
5. **Modularity**: Components can be developed and tested independently

## Configuration Management

### Backend Configuration
- Environment variables in `.env` file (gitignored)
- Configuration loading in `config.py`
- Type-safe settings with Pydantic

### Frontend Configuration
- Environment variables in `.env` file (gitignored)
- Vite-specific prefix: `VITE_`
- Import via `import.meta.env`

## Testing Organization

### Backend Tests
- **Unit Tests**: Test individual functions and classes in isolation
- **Property Tests**: Test mathematical properties across random inputs
- **Integration Tests**: Test API endpoints and full pipeline

### Frontend Tests
- **Component Tests**: Test UI components with React Testing Library
- **Integration Tests**: Test user interactions and API communication
- **E2E Tests**: Test complete user workflows with Playwright (browser automation)
