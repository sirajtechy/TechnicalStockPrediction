"""
Bullish Stock Scanner - FastAPI Application Entry Point

This module initializes the FastAPI application, configures CORS middleware,
and defines the main application lifecycle.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.backtest_endpoints import backtest_router
from api.endpoints import router
from api.intel_endpoints import intel_router
from config import config
from core.scan_store import ScanStore
from utils.logging import get_logger, setup_logging

# Initialize logging
setup_logging()
logger = get_logger(__name__)

# Create FastAPI application
app = FastAPI(
    title="Bullish Stock Scanner",
    description="Technical analysis system for identifying potentially bullish stocks",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for MVP
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(intel_router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event():
    """
    Application startup event handler.

    Initializes the ScanStore database on application startup.
    """
    logger.info("Starting Bullish Stock Scanner API")
    logger.info("API Version: 1.0.0")
    logger.info(f"Database path: {config.DB_PATH}")

    # Initialize ScanStore
    scan_store = ScanStore(db_path=config.DB_PATH)
    await scan_store.initialize()
    logger.info("ScanStore initialized successfully")

    logger.info("Application startup complete")


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {"name": "Bullish Stock Scanner API", "version": "1.0.0", "docs": "/docs"}
