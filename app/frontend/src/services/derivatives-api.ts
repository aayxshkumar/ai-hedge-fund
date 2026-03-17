const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface DerivativeStrategy {
  name: string;
  description: string;
  instrument: 'options' | 'futures';
}

export interface IndexInfo {
  name: string;
  symbol: string;
}

export interface DerivativeResult {
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
  avg_pnl_per_trade: number;
  equity_curve: { date: string; value: number }[];
  error: string | null;
  instrument_type: string;
}

export interface DerivativeSummary {
  strategy: string;
  description: string;
  backtests: number;
  avg_return_pct: number;
  median_return_pct: number;
  best_return_pct: number;
  worst_return_pct: number;
  avg_sharpe: number | null;
  avg_win_rate: number;
  avg_trades: number;
  avg_pnl_per_trade: number;
  profitable_pct: number;
  instrument_type: string;
}

export interface BatchProgress {
  total: number;
  completed: number;
  failed: number;
  pct: number;
  elapsed_sec: number;
  current_strategy: string;
  current_index: string;
  done?: boolean;
}

// ── Options ──

export async function fetchOptionsStrategies(): Promise<DerivativeStrategy[]> {
  const res = await fetch(`${API_BASE}/derivatives/options/strategies`);
  return res.json();
}

export async function fetchOptionsIndices(): Promise<IndexInfo[]> {
  const res = await fetch(`${API_BASE}/derivatives/options/indices`);
  return res.json();
}

export async function startOptionsBatch(params?: {
  strategies?: string[];
  indices?: string[];
  initial_capital?: number;
  expiry_cycle?: string;
}): Promise<{ status: string; total_jobs?: number }> {
  const res = await fetch(`${API_BASE}/derivatives/options/backtest-batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params || {}),
  });
  return res.json();
}

export function streamOptionsBatchProgress(onProgress: (p: BatchProgress) => void): () => void {
  const es = new EventSource(`${API_BASE}/derivatives/options/backtest-batch/stream`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data) as BatchProgress;
    onProgress(data);
    if (data.done) es.close();
  };
  es.onerror = () => es.close();
  return () => es.close();
}

export async function fetchOptionsResults(): Promise<DerivativeResult[]> {
  const res = await fetch(`${API_BASE}/derivatives/options/results?limit=500`);
  return res.json();
}

export async function fetchOptionsSummary(): Promise<DerivativeSummary[]> {
  const res = await fetch(`${API_BASE}/derivatives/options/results/summary`);
  return res.json();
}

export async function fetchOptionsStatus(): Promise<{ running: boolean; progress: BatchProgress }> {
  const res = await fetch(`${API_BASE}/derivatives/options/status`);
  return res.json();
}

// ── Futures ──

export async function fetchFuturesStrategies(): Promise<DerivativeStrategy[]> {
  const res = await fetch(`${API_BASE}/derivatives/futures/strategies`);
  return res.json();
}

export async function fetchFuturesIndices(): Promise<IndexInfo[]> {
  const res = await fetch(`${API_BASE}/derivatives/futures/indices`);
  return res.json();
}

export async function startFuturesBatch(params?: {
  strategies?: string[];
  indices?: string[];
  initial_capital?: number;
}): Promise<{ status: string; total_jobs?: number }> {
  const res = await fetch(`${API_BASE}/derivatives/futures/backtest-batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params || {}),
  });
  return res.json();
}

export function streamFuturesBatchProgress(onProgress: (p: BatchProgress) => void): () => void {
  const es = new EventSource(`${API_BASE}/derivatives/futures/backtest-batch/stream`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data) as BatchProgress;
    onProgress(data);
    if (data.done) es.close();
  };
  es.onerror = () => es.close();
  return () => es.close();
}

export async function fetchFuturesResults(): Promise<DerivativeResult[]> {
  const res = await fetch(`${API_BASE}/derivatives/futures/results?limit=500`);
  return res.json();
}

export async function fetchFuturesSummary(): Promise<DerivativeSummary[]> {
  const res = await fetch(`${API_BASE}/derivatives/futures/results/summary`);
  return res.json();
}

export async function fetchFuturesStatus(): Promise<{ running: boolean; progress: BatchProgress }> {
  const res = await fetch(`${API_BASE}/derivatives/futures/status`);
  return res.json();
}
