const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface Strategy {
  name: string;
  description: string;
}

export interface BacktestResult {
  strategy: string;
  ticker: string;
  period: string;
  initial_capital: number;
  final_value: number;
  total_return_pct: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown_pct: number | null;
  win_rate: number;
  total_trades: number;
  avg_holding_days: number;
  equity_curve: { date: string; value: number }[];
  error: string | null;
}

export interface StrategySummary {
  strategy: string;
  description: string;
  backtests: number;
  avg_return_pct: number;
  median_return_pct: number;
  best_return_pct: number;
  worst_return_pct: number;
  avg_sharpe: number | null;
  avg_sortino: number | null;
  avg_max_drawdown: number | null;
  avg_win_rate: number;
  avg_trades: number;
  profitable_pct: number;
}

export interface BatchProgress {
  total: number;
  completed: number;
  failed: number;
  pct: number;
  elapsed_sec: number;
  eta_sec: number;
  current_strategy: string;
  current_ticker: string;
  done?: boolean;
}

export async function fetchStrategies(): Promise<Strategy[]> {
  const res = await fetch(`${API_BASE}/strategies/list`);
  return res.json();
}

export async function fetchTickers(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/strategies/tickers`);
  return res.json();
}

export async function startBatchBacktest(params?: {
  strategies?: string[];
  tickers?: string[];
  initial_capital?: number;
}): Promise<{ status: string; total_jobs?: number; message?: string }> {
  const res = await fetch(`${API_BASE}/strategies/backtest-batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params || {}),
  });
  return res.json();
}

export function streamBatchProgress(onProgress: (p: BatchProgress) => void): () => void {
  const source = new EventSource(`${API_BASE}/strategies/backtest-batch/stream`);
  source.onmessage = (e) => {
    try {
      const data: BatchProgress = JSON.parse(e.data);
      onProgress(data);
      if (data.done) source.close();
    } catch {}
  };
  source.onerror = () => source.close();
  return () => source.close();
}

export async function fetchResults(params?: {
  strategy?: string;
  ticker?: string;
  period?: string;
  limit?: number;
}): Promise<BacktestResult[]> {
  const q = new URLSearchParams();
  if (params?.strategy) q.set('strategy', params.strategy);
  if (params?.ticker) q.set('ticker', params.ticker);
  if (params?.period) q.set('period', params.period);
  if (params?.limit) q.set('limit', params.limit.toString());
  const res = await fetch(`${API_BASE}/strategies/results?${q}`);
  return res.json();
}

export async function fetchResultsSummary(): Promise<StrategySummary[]> {
  const res = await fetch(`${API_BASE}/strategies/results/summary`);
  return res.json();
}

export async function fetchHeatmap(period?: string): Promise<Record<string, Record<string, number>>> {
  const q = period ? `?period=${period}` : '';
  const res = await fetch(`${API_BASE}/strategies/heatmap${q}`);
  return res.json();
}

export async function fetchBatchStatus(): Promise<{ running: boolean; progress: BatchProgress }> {
  const res = await fetch(`${API_BASE}/strategies/status`);
  return res.json();
}
