// API client for the Bullish Stock Scanner backend

import type { ScanRequest, ScanResponse } from '../types/scan';
import type { StockIntelligence } from '../types/intelligence';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Execute a stock scan with the provided tickers
 */
export async function executeScan(tickers: string[], includeAll = false): Promise<ScanResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/scan`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ tickers, include_all: includeAll } as ScanRequest),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Scan failed');
  }

  return response.json();
}

/**
 * Retrieve a previously completed scan by ID
 */
export async function getScanById(scanId: string): Promise<ScanResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/scan/${scanId}`);

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Scan not found');
  }

  return response.json();
}

/**
 * Fetch the full curated halal stock universe (single source of truth: the backend).
 */
export async function getHalalUniverse(): Promise<{ tickers: string[]; count: number }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/halal-universe`);

  if (!response.ok) {
    throw new Error('Failed to load the halal universe');
  }

  return response.json();
}

/**
 * Fetch the full "intelligence" bundle for one ticker (news+sentiment, insider trades,
 * short interest, dividends, macro, and — when entitled — analyst/earnings/fundamentals).
 */
export async function getStockIntelligence(ticker: string): Promise<StockIntelligence> {
  const response = await fetch(`${API_BASE_URL}/api/v1/intelligence/${encodeURIComponent(ticker)}`);
  if (!response.ok) {
    throw new Error('Failed to load stock intelligence');
  }
  return response.json();
}

/**
 * Check backend health status
 */
export async function checkHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health`);

  if (!response.ok) {
    throw new Error('Health check failed');
  }

  return response.json();
}
