const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface AlgoStatus {
  running: boolean;
  mode: string;
  is_market_hours: boolean;
  current_time_ist: string;
  last_cycle: string | null;
  zerodha: { connected: boolean; funds?: Record<string, number>; error?: string };
  watchlist: string[];
  model_name: string;
  read_only: boolean;
  auto_trade: boolean;
}

export interface PortfolioData {
  holdings: { ticker: string; quantity: number; avg_price: number; last_price: number; pnl: number }[];
  positions: { ticker: string; quantity: number; avg_price: number; last_price: number; pnl: number; product: string }[];
  funds: { available_cash: number; used_margin: number };
  total_value: number;
  day_pnl: number;
  error?: string;
}

export interface AlgoConfig {
  watchlist: string[];
  model_name: string;
  model_provider: string;
  read_only: boolean;
  auto_trade: boolean;
  broker_connected: boolean;
  risk: Record<string, number>;
  scheduler: Record<string, any>;
}

export interface ExecutionEntry {
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  confidence: number;
  reasoning: string;
  timestamp: string;
  result_ok: boolean;
  result_msg: string;
}

export interface RiskData {
  daily_pnl: { realized: number; unrealized: number; total: number };
  limits: Record<string, number>;
}

async function fetchJSON<T>(url: string, opts?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${url}`, opts);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export const algoTraderApi = {
  getStatus: () => fetchJSON<AlgoStatus>('/algo-trader/status'),
  startTrader: () => fetchJSON<{ message: string }>('/algo-trader/start', { method: 'POST' }),
  stopTrader: () => fetchJSON<{ message: string }>('/algo-trader/stop', { method: 'POST' }),
  getPortfolio: () => fetchJSON<PortfolioData>('/algo-trader/portfolio'),
  getSignals: () => fetchJSON<{ signals: any[] }>('/algo-trader/signals'),
  runCycle: (tickers?: string[]) =>
    fetchJSON<{ actions: number; log: ExecutionEntry[] }>('/algo-trader/run-cycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(tickers ? { tickers } : {}),
    }),
  getExecutionLog: () => fetchJSON<{ log: ExecutionEntry[] }>('/algo-trader/execution-log'),
  getConfig: () => fetchJSON<AlgoConfig>('/algo-trader/config'),
  updateConfig: (update: Record<string, any>) =>
    fetchJSON<{ message: string; config: AlgoConfig }>('/algo-trader/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    }),
  getRisk: () => fetchJSON<RiskData>('/algo-trader/risk'),
  syncPortfolio: () => fetchJSON<{ message: string; watchlist: string[] }>('/algo-trader/sync-portfolio', { method: 'POST' }),
  startScanner: () => fetchJSON<{ message: string; running: boolean }>('/algo-trader/scanner/start', { method: 'POST' }),
  stopScanner: () => fetchJSON<{ message: string; running: boolean }>('/algo-trader/scanner/stop', { method: 'POST' }),
  getScannerStatus: () => fetchJSON<{ running: boolean; last_scan_time: string | null; results: any[] }>('/algo-trader/scanner/status'),
  scanNow: () => fetchJSON<{ results: any[]; count: number; watchlist: string[] }>('/algo-trader/scanner/run-now', { method: 'POST' }),
  // Paper trading
  getPaperSummary: () => fetchJSON<any>('/algo-trader/paper/summary'),
  getPaperTrades: (limit = 50) => fetchJSON<{ trades: any[] }>(`/algo-trader/paper/trades?limit=${limit}`),
  paperOrder: (ticker: string, side: string, quantity: number) =>
    fetchJSON<any>('/algo-trader/paper/order', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, side, quantity }),
    }),
  paperReset: () => fetchJSON<any>('/algo-trader/paper/reset', { method: 'POST' }),
  // Mode switching
  switchToPaper: () => fetchJSON<any>('/algo-trader/mode/paper', { method: 'POST' }),
  requestLiveMode: () => fetchJSON<{ confirmation_token: string }>('/algo-trader/mode/live/request', { method: 'POST' }),
  switchToLive: async () => {
    const { confirmation_token } = await algoTraderApi.requestLiveMode();
    return fetchJSON<any>(
      `/algo-trader/mode/live?confirm=true&confirmation_token=${encodeURIComponent(confirmation_token)}`,
      { method: 'POST' },
    );
  },
  // Tradebook
  getTradebook: (limit = 50, ticker?: string, openOnly = false) => {
    const params = new URLSearchParams({ limit: String(limit), open_only: String(openOnly) });
    if (ticker) params.set('ticker', ticker);
    return fetchJSON<{ trades: any[]; count: number }>(`/algo-trader/tradebook?${params}`);
  },
  getTradebookStats: () => fetchJSON<any>('/algo-trader/tradebook/stats'),
  getLearningContext: (ticker?: string) =>
    fetchJSON<{ context: string }>(`/algo-trader/tradebook/learning-context${ticker ? `?ticker=${ticker}` : ''}`),
  getDailySummaries: (limit = 30) => fetchJSON<{ summaries: any[] }>(`/algo-trader/tradebook/daily?limit=${limit}`),
  recordExit: (tradeId: number, exitPrice: number, exitReason = 'manual') =>
    fetchJSON<any>(`/algo-trader/tradebook/record-exit?trade_id=${tradeId}&exit_price=${exitPrice}&exit_reason=${exitReason}`, { method: 'POST' }),
  // Daily Analysis
  getDailyAnalysis: () => fetchJSON<{ report: any }>('/algo-trader/daily-analysis'),
  generateDailyAnalysis: () => fetchJSON<{ message: string }>('/algo-trader/daily-analysis/generate', { method: 'POST' }),
  getDailyAnalysisStatus: () => fetchJSON<{ generating: boolean; penny_scanning: boolean; ready: boolean }>('/algo-trader/daily-analysis/status'),
  scheduleDailyAnalysis: () => fetchJSON<{ message: string; running: boolean }>('/algo-trader/daily-analysis/schedule', { method: 'POST' }),
  // Penny Scanner
  scanPennyStocks: () => fetchJSON<{ message: string; running: boolean }>('/algo-trader/penny-scanner/scan', { method: 'POST' }),
  getPennyScanResults: () => fetchJSON<{ scan_time: string; total_scanned: number; results: any[] }>('/algo-trader/penny-scanner/results'),
  getPennyScanStatus: () => fetchJSON<{ scanning: boolean; ready: boolean }>('/algo-trader/penny-scanner/status'),
  schedulePennyScanner: () => fetchJSON<{ message: string; running: boolean }>('/algo-trader/penny-scanner/schedule', { method: 'POST' }),
  // Review History & Diff
  getReviewHistory: () => fetchJSON<{ snapshots: any[] }>('/algo-trader/portfolio/review-history'),
  getReviewDiff: (scanA?: string, scanB?: string) => {
    const params = new URLSearchParams();
    if (scanA) params.set('scan_a', scanA);
    if (scanB) params.set('scan_b', scanB);
    const qs = params.toString();
    return fetchJSON<{ diff: any }>(`/algo-trader/portfolio/review-diff${qs ? `?${qs}` : ''}`);
  },
  // Portfolio Rebalance
  triggerRebalanceAnalysis: () => fetchJSON<{ message: string }>('/algo-trader/portfolio/rebalance-analysis', { method: 'POST' }),
  getRebalanceAnalysis: () => fetchJSON<{ result: any }>('/algo-trader/portfolio/rebalance-analysis'),
  // Messaging (Telegram / WhatsApp via OpenClaw)
  startMsgScheduler: () => fetchJSON<{ message: string; running: boolean }>('/algo-trader/whatsapp/schedule', { method: 'POST' }),
  stopMsgScheduler: () => fetchJSON<{ message: string; running: boolean }>('/algo-trader/whatsapp/stop', { method: 'POST' }),
  sendTestMessage: () => fetchJSON<{ success: boolean; message: string }>('/algo-trader/whatsapp/test', { method: 'POST' }),
  getMsgStatus: () => fetchJSON<{ scheduler_running: boolean; enabled: boolean; channel: string; target_set: boolean }>('/algo-trader/whatsapp/status'),
};
