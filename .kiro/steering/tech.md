# Technology Stack

## Languages

### Backend
**Python 3.10+** - Primary backend development language

### Frontend
**TypeScript/JavaScript** - Frontend development with React

## Backend Stack

### Web Framework
- **FastAPI 0.104+**: Modern, fast web framework with automatic API documentation
- **Uvicorn**: ASGI server for running FastAPI applications

### HTTP & Networking
- **httpx**: Async HTTP client for external API calls (Polygon/Massive REST)

### Data Processing
- **numpy 1.26+**: Numerical computing for indicator calculations, ATR, volatility

### API & Validation
- **Pydantic 2.4+**: Data validation and settings management
- **FastAPI middleware**: CORS support for frontend integration

### External Data Provider
- **Polygon.io (Massive)**: Market data API (premium pro plan)
  - Aggregates: `/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}` — OHLCV bars
  - Earnings: `GET /benzinga/v1/earnings` — earnings calendar dates
  - Options: `GET /v3/snapshot/options/{underlyingAsset}` — option chain with IV
  - Consensus: `GET /benzinga/v1/consensus-ratings/{ticker}` — analyst price targets
  - Auth: `apiKey` query parameter (POLYGON_TOKEN)

## Frontend Stack

### Framework & Build
- **React 18+**: UI framework
- **Vite**: Fast build tool and dev server
- **TypeScript 5.0+**: Type-safe JavaScript

### UI Library
- **Cloudscape Design System**: `@cloudscape-design/components` for UI elements

### HTTP Client
- **Fetch API**: Native browser API for HTTP requests

## Dependencies & Package Management

### Backend
The project uses pip with requirements.txt:
- Production dependencies in `requirements.txt`
- Development/testing dependencies included in the same file
- Config managed via `pyproject.toml` (ruff, mypy settings) and `pytest.ini`

### Frontend
The project uses npm with package.json:
- Runtime dependencies
- Dev dependencies for build and testing

## Environment Management

### Backend
Virtual environments for dependency isolation:
- `.venv/` directory (gitignored)
- POLYGON_TOKEN is set globally in the system shell (no .env file required)

Required environment variables:
- `POLYGON_TOKEN`: Polygon.io/Massive API key (premium pro plan)
- `API_BASE_URL`: Market data API endpoint (default: https://api.polygon.io)
- `SERVER_PORT`: Backend server port (default: 8000)
- `LOG_LEVEL`: Logging level (default: INFO)
- `DB_PATH`: SQLite database path (default: scanner.db)

### Frontend
Environment variables in `.env` files:
- `VITE_API_URL`: Backend API URL (default: http://localhost:8000)

## Development Tools

### Backend Tools
- **Testing**: pytest, hypothesis (property-based testing), pytest-asyncio, pytest-cov
- **Linting**: ruff
- **Type Checking**: mypy
- **ASGI Server**: uvicorn with reload

### Frontend Tools
- **Testing**: vitest, @testing-library/react, @testing-library/jest-dom, @testing-library/user-event, @playwright/test (E2E testing)
- **Build**: Vite with React plugin
- **Type Checking**: TypeScript compiler

## Common Commands

### Backend Commands

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Run development server (from backend/)
uvicorn main:app --reload --port 8000

# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run property-based tests only
pytest tests/property/

# Run backtest tests only
pytest tests/backtest/

# Run specific test file
pytest tests/unit/test_scoring_engine.py

# Linting
ruff check .

# Type checking
mypy .

# Run backtesting scripts
python scripts/validate_v3.py
python scripts/trade_plan_proto.py
```

### Frontend Commands

```bash
# Install dependencies (from frontend/)
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Run unit tests
npm test

# Run E2E tests with Playwright
npx playwright test

# Run E2E tests in UI mode
npx playwright test --ui

# Preview production build
npm run preview
```

## Code Quality

### Backend
- Type checking with mypy for type safety
- Ruff for fast linting and formatting
- Coverage reporting for tests (target: >80%)
- Property-based testing with hypothesis for mathematical correctness
- Backtest validation for scoring accuracy and trade plan calibration

### Frontend
- TypeScript for compile-time type safety
- React Testing Library for component testing
- ESLint integration via Vite

## API Documentation

- **Swagger UI**: Automatically generated at `/docs` endpoint
- Interactive API testing interface
- OpenAPI 3.0 specification

## Performance Considerations

### Backend
- Async/await for all I/O operations
- Connection pooling (max 5 concurrent API requests)
- In-memory caching per scan session
- Exponential backoff for retry logic (1s, 2s, 4s)
- Trade plans computed only for BUY candidates (not full universe) to minimize API cost
- 400 calendar day fetch window (yields ~274 trading bars for 252-day indicators)

### Frontend
- Lazy loading for large result sets
- Debouncing for user interactions
- Expandable detail rows for trade plan data (avoids re-rendering full table)

## Key Architectural Patterns

### Graceful Degradation
Enhancement data (earnings, options IV, analyst consensus) is optional. If any Massive endpoint fails or returns no data, the Trade Engine falls back to historical data and produces a valid plan without blocking.

### Two-Pass Scoring Pipeline
- PASS 1: Fetch all tickers, compute indicators, compute raw relative strength
- PASS 2: Apply hard filters, score with RS percentile, build trade plans for candidates only

### Calibration-Gated Shipping
No probability or target claim reaches the UI until the backtest calibration passes — positive expectancy confirmed and probability claims match realized outcomes within tolerance.
