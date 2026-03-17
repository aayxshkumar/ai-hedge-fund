const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface ZerodhaStatus {
  connected: boolean;
  has_api_key: boolean;
  has_access_token: boolean;
  error?: string | null;
  user_id?: string;
  user_name?: string;
  email?: string;
  broker?: string;
  funds?: { available_cash: number; used_margin: number } | null;
}

export interface ApiKeyStatus {
  provider: string;
  is_active: boolean;
  has_key: boolean;
  last_used: string | null;
}

export interface RiskConfig {
  max_position_pct: number;
  max_portfolio_exposure: number;
  max_single_order_value: number;
  max_daily_loss_pct: number;
  max_open_positions: number;
  stop_loss_pct: number;
  take_profit_pct: number;
}

export interface SchedulerConfig {
  market_open: string;
  market_close: string;
  analysis_interval_minutes: number;
}

export interface ConnectionsStatus {
  zerodha: ZerodhaStatus;
  api_keys: ApiKeyStatus[];
  active_providers: string[];
  trading: {
    mode: string;
    auto_trade: boolean;
    trader_running: boolean;
    scanner_running: boolean;
  };
  risk: RiskConfig;
  scheduler: SchedulerConfig;
  model: { name: string; provider: string };
  watchlist_count: number;
  current_time_ist: string;
}

export interface TradingConfigUpdate {
  mode?: string;
  auto_trade?: boolean;
  max_position_pct?: number;
  max_portfolio_exposure?: number;
  max_single_order_value?: number;
  max_daily_loss_pct?: number;
  max_open_positions?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  analysis_interval_minutes?: number;
  model_name?: string;
  model_provider?: string;
}

async function fetchJSON<T>(url: string, opts?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${url}`, opts);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export const connectionsApi = {
  getStatus: () => fetchJSON<ConnectionsStatus>('/connections/status'),

  testZerodha: () => fetchJSON<ZerodhaStatus>('/connections/zerodha/test', { method: 'POST' }),

  saveKiteCredentials: (api_key: string, api_secret: string) =>
    fetchJSON<{ message: string; login_url: string | null; has_api_key: boolean }>(
      '/connections/zerodha/credentials',
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key, api_secret }),
      },
    ),

  getLoginUrl: () =>
    fetchJSON<{ login_url: string }>('/connections/zerodha/login-url'),

  exchangeToken: (request_token: string) =>
    fetchJSON<{ success?: boolean; access_token?: string; user_name?: string; error?: string }>(
      '/connections/zerodha/callback',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_token }),
      },
    ),

  updateTradingConfig: (update: TradingConfigUpdate) =>
    fetchJSON<{ message: string; mode: string; risk: RiskConfig }>('/connections/trading/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    }),

  getEnv: () => fetchJSON<{ env: Record<string, string>; path: string }>('/connections/env'),

  updateEnv: (vars: { key: string; value: string }[]) =>
    fetchJSON<{ message: string; keys: string[] }>('/connections/env', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vars }),
    }),
};
