import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../src/App';
import * as scanApi from '../src/services/scanApi';

// Mock the scanApi module
vi.mock('../src/services/scanApi');

describe('App Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Input Validation', () => {
    it('should display validation error when no tickers are entered', async () => {
      render(<App />);
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText(/please enter at least one ticker symbol/i)).toBeInTheDocument();
      });
    });

    it('should display validation error when only whitespace is entered', async () => {
      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, '   ');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText(/please enter at least one ticker symbol/i)).toBeInTheDocument();
      });
    });

    it('should clear error message when dismissed', async () => {
      render(<App />);
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText(/please enter at least one ticker symbol/i)).toBeInTheDocument();
      });

      // Find dismiss button by its role and type
      const dismissButtons = screen.getAllByRole('button');
      const dismissButton = dismissButtons.find(btn => btn.type === 'button' && btn.className.includes('dismiss'));
      expect(dismissButton).toBeDefined();
      fireEvent.click(dismissButton!);

      await waitFor(() => {
        expect(screen.queryByText(/please enter at least one ticker symbol/i)).not.toBeInTheDocument();
      });
    });
  });

  describe('Scan Trigger', () => {
    it('should trigger scan with valid comma-separated tickers', async () => {
      const mockResponse = {
        scan_id: 'test-scan-id',
        market_regime: 'bullish' as const,
        ranked_tickers: [
          {
            ticker: 'AAPL',
            bullish_score: 85,
            current_price: 178.50,
            signals: {
              price_above_sma50: true,
              price_above_ema20: true,
              macd_above_signal: true,
              macd_histogram_positive: true,
              volume_above_average: false,
              relative_strength_positive: true,
            },
            indicators: {
              sma_50: 175.20,
              ema_20: 177.80,
              macd_line: 1.25,
              macd_signal: 0.95,
              macd_histogram: 0.30,
              avg_volume_20: 52000000,
              relative_strength: 2.5,
            },
          },
        ],
        metadata: {
          timestamp: '2024-01-15T10:30:00Z',
          ticker_count: 1,
          duration_seconds: 2.5,
        },
      };

      vi.mocked(scanApi.executeScan).mockResolvedValue(mockResponse);

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL, MSFT, GOOGL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(scanApi.executeScan).toHaveBeenCalledWith(['AAPL', 'MSFT', 'GOOGL'], false);
      });
    });

    it('should trigger scan with valid space-separated tickers', async () => {
      const mockResponse = {
        scan_id: 'test-scan-id',
        market_regime: 'bullish' as const,
        ranked_tickers: [],
        metadata: {
          timestamp: '2024-01-15T10:30:00Z',
          ticker_count: 0,
          duration_seconds: 1.0,
        },
      };

      vi.mocked(scanApi.executeScan).mockResolvedValue(mockResponse);

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL MSFT GOOGL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(scanApi.executeScan).toHaveBeenCalledWith(['AAPL', 'MSFT', 'GOOGL'], false);
      });
    });

    it('should convert tickers to uppercase', async () => {
      const mockResponse = {
        scan_id: 'test-scan-id',
        market_regime: 'neutral' as const,
        ranked_tickers: [],
        metadata: {
          timestamp: '2024-01-15T10:30:00Z',
          ticker_count: 0,
          duration_seconds: 1.0,
        },
      };

      vi.mocked(scanApi.executeScan).mockResolvedValue(mockResponse);

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'aapl, msft');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(scanApi.executeScan).toHaveBeenCalledWith(['AAPL', 'MSFT'], false);
      });
    });

    it('should trigger scan when Enter key is pressed in input', async () => {
      const mockResponse = {
        scan_id: 'test-scan-id',
        market_regime: 'bullish' as const,
        ranked_tickers: [],
        metadata: {
          timestamp: '2024-01-15T10:30:00Z',
          ticker_count: 0,
          duration_seconds: 1.0,
        },
      };

      vi.mocked(scanApi.executeScan).mockResolvedValue(mockResponse);

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL{Enter}');

      await waitFor(() => {
        expect(scanApi.executeScan).toHaveBeenCalledWith(['AAPL'], false);
      });
    });
  });

  describe('Loading State', () => {
    it('should display loading indicator during scan', async () => {
      vi.mocked(scanApi.executeScan).mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 100))
      );

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      // Loading indicator (ScanProgress) should appear
      await waitFor(() => {
        expect(screen.getByText(/analyzing/i)).toBeInTheDocument();
      });
    });

    it('should disable input and button during scan', async () => {
      vi.mocked(scanApi.executeScan).mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 100))
      );

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i) as HTMLInputElement;
      await userEvent.type(input, 'AAPL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i }) as HTMLButtonElement;
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(input.disabled).toBe(true);
        expect(scanButton.disabled).toBe(true);
      });
    });

    it('should not trigger scan when Enter is pressed while loading', async () => {
      vi.mocked(scanApi.executeScan).mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 1000))
      );

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      // Try to trigger again with Enter
      await userEvent.type(input, '{Enter}');

      // Should only be called once
      await waitFor(() => {
        expect(scanApi.executeScan).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe('Results Display', () => {
    it('should display market regime after successful scan', async () => {
      const mockResponse = {
        scan_id: 'test-scan-id',
        market_regime: 'bullish' as const,
        ranked_tickers: [],
        metadata: {
          timestamp: '2024-01-15T10:30:00Z',
          ticker_count: 0,
          duration_seconds: 1.0,
        },
      };

      vi.mocked(scanApi.executeScan).mockResolvedValue(mockResponse);

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText(/bullish market/i)).toBeInTheDocument();
      });
    });

    it('should display ranked results table after successful scan', async () => {
      const mockResponse = {
        scan_id: 'test-scan-id',
        market_regime: 'bullish' as const,
        ranked_tickers: [
          {
            ticker: 'AAPL',
            bullish_score: 85,
            current_price: 178.50,
            signals: {
              price_above_sma50: true,
              price_above_ema20: true,
              macd_above_signal: true,
              macd_histogram_positive: true,
              volume_above_average: false,
              relative_strength_positive: true,
            },
            indicators: {
              sma_50: 175.20,
              ema_20: 177.80,
              macd_line: 1.25,
              macd_signal: 0.95,
              macd_histogram: 0.30,
              avg_volume_20: 52000000,
              relative_strength: 2.5,
            },
          },
          {
            ticker: 'MSFT',
            bullish_score: 70,
            current_price: 380.00,
            signals: {
              price_above_sma50: true,
              price_above_ema20: true,
              macd_above_signal: true,
              macd_histogram_positive: false,
              volume_above_average: true,
              relative_strength_positive: true,
            },
            indicators: {
              sma_50: 375.00,
              ema_20: 378.00,
              macd_line: 0.50,
              macd_signal: 0.60,
              macd_histogram: -0.10,
              avg_volume_20: 25000000,
              relative_strength: 1.5,
            },
          },
        ],
        metadata: {
          timestamp: '2024-01-15T10:30:00Z',
          ticker_count: 2,
          duration_seconds: 2.5,
        },
      };

      vi.mocked(scanApi.executeScan).mockResolvedValue(mockResponse);

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL, MSFT');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText('AAPL')).toBeInTheDocument();
        expect(screen.getByText('MSFT')).toBeInTheDocument();
        expect(screen.getByText('85')).toBeInTheDocument();
        expect(screen.getByText('70')).toBeInTheDocument();
      });
    });

    it('should clear previous results when starting new scan', async () => {
      const mockResponse1 = {
        scan_id: 'test-scan-id-1',
        market_regime: 'bullish' as const,
        ranked_tickers: [
          {
            ticker: 'AAPL',
            bullish_score: 85,
            current_price: 178.50,
            signals: {
              price_above_sma50: true,
              price_above_ema20: true,
              macd_above_signal: true,
              macd_histogram_positive: true,
              volume_above_average: false,
              relative_strength_positive: true,
            },
            indicators: {},
          },
        ],
        metadata: {
          timestamp: '2024-01-15T10:30:00Z',
          ticker_count: 1,
          duration_seconds: 1.0,
        },
      };

      const mockResponse2 = {
        scan_id: 'test-scan-id-2',
        market_regime: 'bearish' as const,
        ranked_tickers: [
          {
            ticker: 'TSLA',
            bullish_score: 40,
            current_price: 250.00,
            signals: {
              price_above_sma50: false,
              price_above_ema20: false,
              macd_above_signal: false,
              macd_histogram_positive: false,
              volume_above_average: true,
              relative_strength_positive: false,
            },
            indicators: {},
          },
        ],
        metadata: {
          timestamp: '2024-01-15T10:31:00Z',
          ticker_count: 1,
          duration_seconds: 1.0,
        },
      };

      vi.mocked(scanApi.executeScan)
        .mockResolvedValueOnce(mockResponse1)
        .mockResolvedValueOnce(mockResponse2);

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      
      // First scan
      await userEvent.clear(input);
      await userEvent.type(input, 'AAPL');
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText('AAPL')).toBeInTheDocument();
      });

      // Second scan
      await userEvent.clear(input);
      await userEvent.type(input, 'TSLA');
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
        expect(screen.getByText('TSLA')).toBeInTheDocument();
      });
    });
  });

  describe('Error Display', () => {
    it('should display error message after failed scan', async () => {
      vi.mocked(scanApi.executeScan).mockRejectedValue(
        new Error('Unable to connect to server')
      );

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText(/unable to connect to server/i)).toBeInTheDocument();
      });
    });

    it('should display generic error message for non-Error exceptions', async () => {
      vi.mocked(scanApi.executeScan).mockRejectedValue('Something went wrong');

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText(/scan failed\. please try again/i)).toBeInTheDocument();
      });
    });

    it('should clear error when starting new scan', async () => {
      vi.mocked(scanApi.executeScan)
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce({
          scan_id: 'test-scan-id',
          market_regime: 'neutral' as const,
          ranked_tickers: [],
          metadata: {
            timestamp: '2024-01-15T10:30:00Z',
            ticker_count: 0,
            duration_seconds: 1.0,
          },
        });

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText(/network error/i)).toBeInTheDocument();
      });

      // Start new scan
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.queryByText(/network error/i)).not.toBeInTheDocument();
      });
    });

    it('should not display results when scan fails', async () => {
      vi.mocked(scanApi.executeScan).mockRejectedValue(
        new Error('API error')
      );

      render(<App />);
      
      const input = screen.getByPlaceholderText(/enter ticker symbols/i);
      await userEvent.type(input, 'AAPL');
      
      const scanButton = screen.getByRole('button', { name: /run scan/i });
      fireEvent.click(scanButton);

      await waitFor(() => {
        expect(screen.getByText(/api error/i)).toBeInTheDocument();
      });

      expect(screen.queryByText(/ranked results/i)).not.toBeInTheDocument();
    });
  });
});
