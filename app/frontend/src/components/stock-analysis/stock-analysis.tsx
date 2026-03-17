import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchAnalysts,
  type AnalystInfo,
} from '@/services/analysis-api';
import { formatINR } from '@/lib/format-inr';
import {
  XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, Area, AreaChart, ReferenceLine, BarChart, Bar,
} from 'recharts';
import {
  ChevronDown,
  ChevronRight,
  Clock,
  Compass,
  EyeOff,
  Eye,
  Loader2,
  RefreshCw,
  Search,
  TrendingUp,
  TrendingDown,
  Minus,
  Trash2,
  X,
  Sparkles,
  Activity,
  BarChart3,
  Target,
  Shield,
  Users,
  Zap,
  BookOpen,
} from 'lucide-react';
import { useNotifications } from '@/contexts/notifications-context';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface DetailedResult {
  ticker: string;
  current_price: number | null;
  decision: { action?: string; confidence?: number; reasoning?: string; quantity?: number };
  technical: Record<string, any>;
  fundamentals: Record<string, any>;
  price_history: { date: string; open: number; high: number; low: number; close: number; volume: number }[];
  analyst_signals?: Record<string, any> | null;
  target_price?: number;
  stop_loss?: number;
  time_horizon?: string;
  risk_reward_ratio?: number;
}

function ActionBadge({ action }: { action: string }) {
  const upper = action?.toUpperCase() || 'HOLD';
  if (upper.includes('BUY') || upper === 'BULLISH')
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
        <TrendingUp size={13} /> {upper.replace('_', ' ')}
      </span>
    );
  if (upper.includes('SELL') || upper === 'BEARISH')
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-red-500/15 text-red-400 border border-red-500/20">
        <TrendingDown size={13} /> {upper.replace('_', ' ')}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/20">
      <Minus size={13} /> HOLD
    </span>
  );
}

const HORIZON_CONFIG: Record<string, { label: string; color: string }> = {
  intraday:   { label: 'Intraday',  color: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/20' },
  swing_1w:   { label: '1W Swing',  color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20' },
  short_1m:   { label: '1M Short',  color: 'bg-blue-500/15 text-blue-400 border-blue-500/20' },
  medium_3m:  { label: '3M Medium', color: 'bg-purple-500/15 text-purple-400 border-purple-500/20' },
  'long_6m+': { label: '6M+ Long',  color: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/20' },
};

function TimeHorizonBadge({ horizon }: { horizon?: string }) {
  if (!horizon) return null;
  const cfg = HORIZON_CONFIG[horizon] || { label: horizon.replace('_', ' '), color: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/20' };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold border ${cfg.color}`}>
      <Clock size={10} /> {cfg.label}
    </span>
  );
}

function ConfidenceMeter({ value }: { value: number }) {
  const normalized = (value == null || isNaN(value)) ? 0 : (value > 1 ? value / 100 : value);
  const pct = Math.round(Math.max(0, Math.min(100, normalized * 100)));
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2.5">
      <div className="w-28 h-2.5 bg-muted rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-muted-foreground">{pct}%</span>
    </div>
  );
}

function MetricCard({ label, value, sub }: { label: string; value: string | number | null | undefined; sub?: string }) {
  return (
    <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
      <div className="text-sm font-semibold font-mono">{value ?? '—'}</div>
      {sub && <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function GaugeBar({ value, min, max, label, unit }: { value: number | null; min: number; max: number; label: string; unit?: string }) {
  if (value === null || value === undefined) return null;
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  const color = value > 70 ? 'bg-red-500' : value > 50 ? 'bg-amber-500' : value > 30 ? 'bg-emerald-500' : 'bg-blue-500';
  return (
    <div>
      <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
        <span>{label}</span>
        <span className="font-mono">{value}{unit}</span>
      </div>
      <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

type TabKey = 'overview' | 'technical' | 'fundamentals' | 'analysts' | 'risk';

const TAB_CONFIG: { key: TabKey; label: string; icon: any }[] = [
  { key: 'overview', label: 'Overview', icon: Target },
  { key: 'technical', label: 'Technical', icon: Activity },
  { key: 'fundamentals', label: 'Fundamentals', icon: BarChart3 },
  { key: 'analysts', label: 'Analysts', icon: Users },
  { key: 'risk', label: 'Risk', icon: Shield },
];

function TickerDetail({ data, defaultCollapsed }: { data: DetailedResult; defaultCollapsed?: boolean }) {
  const [tab, setTab] = useState<TabKey>('overview');
  const [collapsed, setCollapsed] = useState(defaultCollapsed ?? false);
  const tech = data.technical || {};
  const fund = data.fundamentals || {};
  const decision = data.decision || {};

  const fmtLargeINR = (v: number | null | undefined) => {
    if (v == null) return '—';
    if (v >= 1e12) return `₹${(v / 1e12).toFixed(2)}T`;
    if (v >= 1e9) return `₹${(v / 1e9).toFixed(2)}B`;
    if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)}Cr`;
    if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)}L`;
    return formatINR(v, 0);
  };

  const fmtPct = (v: number | null | undefined) => v != null ? `${(v * 100).toFixed(2)}%` : '—';

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      {/* Header — always visible, clickable to toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full text-left p-5 border-b cursor-pointer hover:bg-accent/20 transition-colors"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {collapsed ? <ChevronRight size={16} className="text-muted-foreground" /> : <ChevronDown size={16} className="text-muted-foreground" />}
            <div>
              <div className="flex items-center gap-3">
                <span className="text-xl font-bold">{data.ticker.replace('.NS', '')}</span>
                <span className="text-sm text-muted-foreground">{fund.short_name || data.ticker}</span>
              </div>
              {fund.sector && <span className="text-xs text-muted-foreground">{fund.sector} · {fund.industry}</span>}
            </div>
          </div>
          <div className="flex items-center gap-4">
            {data.current_price && <span className="text-2xl font-bold font-mono">{formatINR(data.current_price, 2)}</span>}
            <ActionBadge action={decision.action || 'hold'} />
            <TimeHorizonBadge horizon={data.time_horizon || (data.analyst_signals?.target_analyst_agent as any)?.time_horizon} />
          </div>
        </div>
        {!collapsed && decision.reasoning && (
          <p className="text-sm text-muted-foreground mt-3 leading-relaxed">{decision.reasoning}</p>
        )}
        {!collapsed && (
          <div className="flex items-center gap-6 mt-3 flex-wrap">
            <ConfidenceMeter value={decision.confidence || 0} />
            {data.target_price && (
              <span className="text-xs">
                <span className="text-muted-foreground">Target: </span>
                <span className="font-mono font-medium text-emerald-400">{formatINR(data.target_price, 2)}</span>
              </span>
            )}
            {data.stop_loss && (
              <span className="text-xs">
                <span className="text-muted-foreground">Stop Loss: </span>
                <span className="font-mono font-medium text-red-400">{formatINR(data.stop_loss, 2)}</span>
              </span>
            )}
            {(data.risk_reward_ratio || (data.analyst_signals?.target_analyst_agent as any)?.risk_reward_ratio) && (
              <span className="text-xs">
                <span className="text-muted-foreground">R:R </span>
                <span className="font-mono font-medium">{(data.risk_reward_ratio || (data.analyst_signals?.target_analyst_agent as any)?.risk_reward_ratio)?.toFixed(2)}</span>
              </span>
            )}
          </div>
        )}
      </button>

      {collapsed ? null : <>
      {/* Tabs */}
      <div className="flex border-b">
        {TAB_CONFIG.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-colors cursor-pointer ${
              tab === t.key ? 'border-b-2 border-primary text-foreground' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <t.icon size={12} /> {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="p-5">
        {tab === 'overview' && (
          <div className="space-y-5">
            {data.price_history.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Price (90 Days)</h4>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.price_history}>
                      <defs>
                        <linearGradient id={`grad-${data.ticker}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
                          <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={d => d.slice(5)} stroke="hsl(var(--muted-foreground))" />
                      <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" tickFormatter={v => `₹${v}`} />
                      <RTooltip
                        contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 11 }}
                        formatter={(v: any) => [formatINR(Number(v), 2), 'Price']}
                      />
                      {data.target_price && <ReferenceLine y={data.target_price} stroke="#22c55e" strokeDasharray="3 3" label={{ value: 'Target', fontSize: 9, fill: '#22c55e' }} />}
                      {data.stop_loss && <ReferenceLine y={data.stop_loss} stroke="#ef4444" strokeDasharray="3 3" label={{ value: 'SL', fontSize: 9, fill: '#ef4444' }} />}
                      <Area type="monotone" dataKey="close" stroke="hsl(var(--primary))" fill={`url(#grad-${data.ticker})`} strokeWidth={1.5} dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <MetricCard label="52W High" value={fund.fifty_two_week_high ? formatINR(fund.fifty_two_week_high, 2) : undefined} />
              <MetricCard label="52W Low" value={fund.fifty_two_week_low ? formatINR(fund.fifty_two_week_low, 2) : undefined} />
              <MetricCard label="Market Cap" value={fmtLargeINR(fund.market_cap)} />
              <MetricCard label="Volume (Avg)" value={fund.avg_volume?.toLocaleString()} />
            </div>
          </div>
        )}

        {tab === 'technical' && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <MetricCard label="Trend" value={tech.trend} />
              <MetricCard label="RSI (14)" value={tech.rsi} sub={tech.rsi > 70 ? 'Overbought' : tech.rsi < 30 ? 'Oversold' : 'Neutral'} />
              <MetricCard label="MACD" value={tech.macd} sub={`Signal: ${tech.macd_signal}`} />
              <MetricCard label="EMA 50" value={tech.ema_50 ? formatINR(tech.ema_50, 2) : undefined} />
              <MetricCard label="EMA 200" value={tech.ema_200 ? formatINR(tech.ema_200, 2) : undefined} />
              <MetricCard label="MACD Histogram" value={tech.macd_histogram} />
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <MetricCard label="Bollinger Upper" value={tech.bollinger_upper ? formatINR(tech.bollinger_upper, 2) : undefined} />
              <MetricCard label="Bollinger Mid" value={tech.bollinger_mid ? formatINR(tech.bollinger_mid, 2) : undefined} />
              <MetricCard label="Bollinger Lower" value={tech.bollinger_lower ? formatINR(tech.bollinger_lower, 2) : undefined} />
              <MetricCard label="Support" value={tech.support ? formatINR(tech.support, 2) : undefined} />
              <MetricCard label="Resistance" value={tech.resistance ? formatINR(tech.resistance, 2) : undefined} />
            </div>
            <div className="space-y-3">
              <GaugeBar value={tech.rsi} min={0} max={100} label="RSI" />
            </div>
            {data.price_history.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Volume</h4>
                <div className="h-32">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.price_history.slice(-30)}>
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={d => d.slice(8)} stroke="hsl(var(--muted-foreground))" />
                      <YAxis tick={{ fontSize: 9 }} stroke="hsl(var(--muted-foreground))" tickFormatter={v => `${(v / 1e6).toFixed(0)}M`} />
                      <Bar dataKey="volume" fill="hsl(var(--primary))" opacity={0.5} radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        )}

        {tab === 'fundamentals' && (
          <div className="space-y-4">
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Valuation</h4>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <MetricCard label="P/E Ratio" value={fund.pe_ratio?.toFixed(2)} />
              <MetricCard label="P/B Ratio" value={fund.pb_ratio?.toFixed(2)} />
              <MetricCard label="EPS" value={fund.eps ? formatINR(fund.eps, 2) : undefined} />
              <MetricCard label="Book Value" value={fund.book_value ? formatINR(fund.book_value, 2) : undefined} />
            </div>
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Profitability</h4>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <MetricCard label="Revenue" value={fmtLargeINR(fund.revenue)} />
              <MetricCard label="Profit Margin" value={fmtPct(fund.profit_margin)} />
              <MetricCard label="Operating Margin" value={fmtPct(fund.operating_margin)} />
              <MetricCard label="ROE" value={fmtPct(fund.roe)} />
            </div>
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Financial Health</h4>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <MetricCard label="Debt/Equity" value={fund.debt_to_equity?.toFixed(2)} />
              <MetricCard label="Current Ratio" value={fund.current_ratio?.toFixed(2)} />
              <MetricCard label="Free Cash Flow" value={fmtLargeINR(fund.free_cash_flow)} />
              <MetricCard label="Dividend Yield" value={fmtPct(fund.dividend_yield)} />
            </div>
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Market</h4>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <MetricCard label="Market Cap" value={fmtLargeINR(fund.market_cap)} />
              <MetricCard label="Beta" value={fund.beta?.toFixed(2)} />
              <MetricCard label="Shares Outstanding" value={fund.shares_outstanding ? `${(fund.shares_outstanding / 1e7).toFixed(2)} Cr` : undefined} />
              <MetricCard label="Avg Volume" value={fund.avg_volume?.toLocaleString()} />
            </div>
          </div>
        )}

        {tab === 'analysts' && (() => {
          const raw = data.analyst_signals;
          if (raw == null || typeof raw !== 'object') {
            return (
              <div className="flex flex-col items-center justify-center py-12 gap-3">
                <Loader2 size={20} className="animate-spin text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Analysts are still processing...</p>
                <p className="text-xs text-muted-foreground/60">This can take a minute — the AI agents are analyzing multiple data sources.</p>
              </div>
            );
          }
          const entries = Object.entries(raw).filter(([, v]) => v != null && typeof v === 'object');
          if (entries.length === 0) {
            return (
              <div className="flex flex-col items-center justify-center py-12 gap-3">
                <Users size={20} className="text-muted-foreground" />
                <p className="text-sm text-muted-foreground">No analyst signals returned for this ticker.</p>
                <p className="text-xs text-muted-foreground/60">Try re-running the analysis or selecting different analysts.</p>
              </div>
            );
          }
          return (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground mb-2">{entries.length} analyst{entries.length !== 1 ? 's' : ''} reported signals</p>
              {entries.map(([analyst, signal]: [string, any]) => {
                const sigStr = typeof signal?.signal === 'string' ? signal.signal : '';
                const sigUpper = sigStr.toUpperCase();
                const conf = typeof signal?.confidence === 'number' ? signal.confidence : null;
                const reasoning = typeof signal?.reasoning === 'string' ? signal.reasoning : '';
                return (
                  <div key={analyst} className="p-3.5 rounded-lg border bg-muted/20">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium capitalize">{analyst.replace(/_/g, ' ')}</span>
                      <div className="flex items-center gap-3">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                          sigUpper.includes('BUY') || sigUpper.includes('BULLISH') ? 'bg-emerald-500/15 text-emerald-400' :
                          sigUpper.includes('SELL') || sigUpper.includes('BEARISH') ? 'bg-red-500/15 text-red-400' :
                          'bg-amber-500/15 text-amber-400'
                        }`}>
                          {sigStr || 'N/A'}
                        </span>
                        {conf != null && <span className="text-xs font-mono text-muted-foreground">{Math.round(conf > 1 ? conf : conf * 100)}%</span>}
                      </div>
                    </div>
                    {reasoning && <p className="text-xs text-muted-foreground leading-relaxed">{reasoning}</p>}
                  </div>
                );
              })}
            </div>
          );
        })()}

        {tab === 'risk' && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <MetricCard label="Annualized Volatility" value={tech.volatility_annual ? `${(tech.volatility_annual * 100).toFixed(1)}%` : undefined} />
              <MetricCard label="Max Drawdown (90D)" value={tech.max_drawdown_90d ? `${(tech.max_drawdown_90d * 100).toFixed(1)}%` : undefined} />
              <MetricCard label="Beta" value={fund.beta?.toFixed(2)} sub={fund.beta > 1 ? 'Higher than market' : fund.beta < 1 ? 'Lower than market' : 'Market level'} />
            </div>
            <div className="space-y-3">
              <GaugeBar value={tech.volatility_annual ? tech.volatility_annual * 100 : null} min={0} max={80} label="Volatility" unit="%" />
              <GaugeBar value={tech.max_drawdown_90d ? Math.abs(tech.max_drawdown_90d * 100) : null} min={0} max={50} label="Max Drawdown" unit="%" />
              <GaugeBar value={fund.beta ? fund.beta * 50 : null} min={0} max={100} label="Beta Risk" />
            </div>
            {data.target_price && data.stop_loss && data.current_price && (
              <div className="p-4 rounded-lg border bg-muted/20">
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Risk/Reward</h4>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <div className="text-[10px] text-muted-foreground">Upside</div>
                    <div className="text-sm font-mono font-semibold text-emerald-400">
                      {((data.target_price - data.current_price) / data.current_price * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-muted-foreground">Downside</div>
                    <div className="text-sm font-mono font-semibold text-red-400">
                      {((data.stop_loss - data.current_price) / data.current_price * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-muted-foreground">R:R Ratio</div>
                    <div className="text-sm font-mono font-semibold">
                      {Math.abs((data.target_price - data.current_price) / (data.stop_loss - data.current_price)).toFixed(2)}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      </>}
    </div>
  );
}

// ── Daily Analysis Section ────────────────────────────────────────────

interface DailyVerdict {
  ticker: string; action: string; score: number; confidence: number; reasoning: string;
  target_price: number; stop_loss: number; time_horizon: string; risk_reward_ratio: number;
  bullish_pct?: number; bearish_pct?: number; total_agents?: number;
  current_price?: number; change_1d_pct?: number; change_5d_pct?: number;
}

interface DailyReport {
  generated_at?: string;
  market_overview?: { index: string; last_close?: number; change_1d_pct?: number; change_5d_pct?: number; trend?: string };
  verdict_summary?: { total: number; buys: number; sells: number; holds: number; top_buys?: any[]; top_sells?: any[] };
  strong_buys?: { ticker: string; action: string; score: number; confidence: number; reasoning: string; target_price: number; stop_loss: number; time_horizon: string; risk_reward_ratio: number; signal: string; current_price?: number; change_1d_pct?: number; enriched?: any }[];
  target_signals?: { ticker: string; signal: string; target_price: number; stop_loss: number; time_horizon: string; risk_reward_ratio: number; confidence: number; reasoning: string; enriched?: any; meta_action?: string; meta_score?: number; meta_confidence?: number }[];
  all_verdicts?: DailyVerdict[];
  batch_tickers?: string[];
  portfolio_balance?: { current_allocation?: Record<string, number>; recommended_profile?: string; recommended_allocation?: Record<string, number>; suggestions?: any[]; short_term_picks?: any[] };
}

interface StockDetail {
  ticker: string;
  current_price: number | null;
  technical: Record<string, any>;
  fundamentals: Record<string, any>;
  price_history: { date: string; open: number; high: number; low: number; close: number; volume: number }[];
  verdict: Record<string, any>;
  analyst_signals: Record<string, any>;
  penny_scan?: Record<string, any>;
  reviewed?: boolean;
}

function StockDetailPanel({ ticker, onClose }: { ticker: string; onClose: () => void }) {
  const [data, setData] = useState<StockDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const controller = new AbortController();
    const cleanTicker = ticker.replace('.NS', '').replace('.BO', '');
    fetch(`${API_BASE}/algo-trader/daily-analysis/stock/${cleanTicker}`, { signal: controller.signal })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch((e) => { if (e.name !== 'AbortError') setLoading(false); });
    return () => controller.abort();
  }, [ticker]);

  if (loading) {
    return (
      <div className="border-t border-border/30 bg-muted/10 p-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> Loading {ticker.replace('.NS', '')} details...
        </div>
      </div>
    );
  }

  if (!data || !data.current_price) {
    return (
      <div className="border-t border-border/30 bg-muted/10 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">No data available for {ticker.replace('.NS', '')}</span>
          <button onClick={onClose} className="p-1 hover:bg-accent/20 rounded cursor-pointer"><X size={14} /></button>
        </div>
      </div>
    );
  }

  const tech = data.technical || {};
  const fund = data.fundamentals || {};
  const verdict = data.verdict || {};
  const signals = data.analyst_signals || {};

  return (
    <div className="border-t border-amber-500/20 bg-gradient-to-b from-amber-500/5 to-transparent p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-base font-bold">{ticker.replace('.NS', '')}</span>
          <span className="text-lg font-mono font-semibold">{formatINR(data.current_price, 2)}</span>
          {fund.short_name && <span className="text-[10px] text-muted-foreground">{fund.short_name}</span>}
        </div>
        <button onClick={onClose} className="p-1.5 hover:bg-accent/20 rounded-lg cursor-pointer"><X size={14} /></button>
      </div>

      {/* Mini chart */}
      {data.price_history.length > 0 && (
        <div className="h-32">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data.price_history.slice(-30)}>
              <defs>
                <linearGradient id={`grad-${ticker}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" hide />
              <YAxis domain={['auto', 'auto']} hide />
              <RTooltip
                contentStyle={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 8, fontSize: 11 }}
                formatter={(v: number) => [formatINR(v, 2), 'Price']}
                labelFormatter={(l: string) => l}
              />
              <Area type="monotone" dataKey="close" stroke="#f59e0b" fill={`url(#grad-${ticker})`} strokeWidth={1.5} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Technicals */}
        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold text-amber-400 uppercase tracking-wider">Technical</div>
          {tech.rsi != null && <div className="text-[10px]"><span className="text-zinc-500">RSI:</span> <span className={tech.rsi > 70 ? 'text-red-400' : tech.rsi < 30 ? 'text-emerald-400' : 'text-foreground'}>{tech.rsi}</span></div>}
          {tech.trend && <div className="text-[10px]"><span className="text-zinc-500">Trend:</span> <span className={tech.trend === 'Bullish' ? 'text-emerald-400' : 'text-red-400'}>{tech.trend}</span></div>}
          {tech.macd != null && <div className="text-[10px]"><span className="text-zinc-500">MACD:</span> <span className="font-mono">{tech.macd}</span></div>}
          {tech.volatility_annual != null && <div className="text-[10px]"><span className="text-zinc-500">Volatility:</span> <span className="font-mono">{(tech.volatility_annual * 100).toFixed(1)}%</span></div>}
          {tech.support && <div className="text-[10px]"><span className="text-zinc-500">Support:</span> <span className="text-emerald-400 font-mono">{formatINR(tech.support, 2)}</span></div>}
          {tech.resistance && <div className="text-[10px]"><span className="text-zinc-500">Resistance:</span> <span className="text-red-400 font-mono">{formatINR(tech.resistance, 2)}</span></div>}
        </div>

        {/* Fundamentals */}
        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold text-blue-400 uppercase tracking-wider">Fundamental</div>
          {fund.pe_ratio && <div className="text-[10px]"><span className="text-zinc-500">P/E:</span> <span className="font-mono">{fund.pe_ratio.toFixed(1)}</span></div>}
          {fund.pb_ratio && <div className="text-[10px]"><span className="text-zinc-500">P/B:</span> <span className="font-mono">{fund.pb_ratio.toFixed(1)}</span></div>}
          {fund.market_cap && <div className="text-[10px]"><span className="text-zinc-500">Mkt Cap:</span> <span className="font-mono">{formatINR(fund.market_cap / 1e7, 0)} Cr</span></div>}
          {fund.dividend_yield != null && <div className="text-[10px]"><span className="text-zinc-500">Div Yield:</span> <span className="font-mono">{(fund.dividend_yield * 100).toFixed(2)}%</span></div>}
          {fund.sector && <div className="text-[10px]"><span className="text-zinc-500">Sector:</span> {fund.sector}</div>}
          {fund.roe != null && <div className="text-[10px]"><span className="text-zinc-500">ROE:</span> <span className="font-mono">{(fund.roe * 100).toFixed(1)}%</span></div>}
        </div>

        {/* Verdict */}
        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold text-purple-400 uppercase tracking-wider">AI Verdict</div>
          {verdict.action ? (
            <>
              <div className="text-[10px]"><ActionBadge action={verdict.action} /></div>
              {verdict.score != null && <div className="text-[10px]"><span className="text-zinc-500">Score:</span> <span className="font-mono">{verdict.score > 0 ? '+' : ''}{Number(verdict.score).toFixed(3)}</span></div>}
              {verdict.confidence != null && <div className="text-[10px]"><span className="text-zinc-500">Confidence:</span> <span className="font-mono">{(Number(verdict.confidence) * 100).toFixed(0)}%</span></div>}
              {verdict.reasoning && <p className="text-[10px] text-zinc-500 leading-relaxed">{String(verdict.reasoning).slice(0, 120)}</p>}
            </>
          ) : data.penny_scan ? (
            <>
              <div className="text-[10px] text-amber-400 font-semibold">Penny Scanner</div>
              <div className="text-[10px]"><span className="text-zinc-500">Score:</span> <span className="font-mono">{data.penny_scan.score}</span></div>
              <div className="text-[10px]"><span className="text-zinc-500">Target:</span> <span className="text-emerald-400 font-mono">{formatINR(data.penny_scan.target_price, 2)}</span></div>
              <div className="text-[10px]"><span className="text-zinc-500">Stop Loss:</span> <span className="text-red-400 font-mono">{formatINR(data.penny_scan.stop_loss, 2)}</span></div>
              <div className="text-[10px]"><span className="text-zinc-500">Horizon:</span> <span className="capitalize">{(data.penny_scan.time_horizon || '').replace(/_/g, ' ')}</span></div>
              {data.penny_scan.reasoning && <p className="text-[10px] text-zinc-500 leading-relaxed">{data.penny_scan.reasoning}</p>}
            </>
          ) : (
            <div className="text-[10px] text-zinc-500">Not in portfolio review</div>
          )}
        </div>

        {/* Agent Signals */}
        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider">
            {Object.keys(signals).length > 0 ? 'Agent Signals' : data.penny_scan ? 'Scanner Indicators' : 'Agent Signals'}
          </div>
          {Object.keys(signals).length > 0 ? (
            Object.entries(signals).slice(0, 6).map(([agent, sig]: [string, any]) => (
              <div key={agent} className="text-[10px] flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${sig?.signal?.includes('bull') || sig?.signal?.includes('buy') ? 'bg-emerald-400' : sig?.signal?.includes('bear') || sig?.signal?.includes('sell') ? 'bg-red-400' : 'bg-zinc-500'}`} />
                <span className="text-zinc-500 truncate w-20">{agent.replace('_agent', '').replace(/_/g, ' ')}</span>
                <span className="capitalize">{sig?.signal || 'n/a'}</span>
              </div>
            ))
          ) : data.penny_scan ? (
            <>
              <div className="text-[10px] flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${data.penny_scan.ema_trend === 'up' ? 'bg-emerald-400' : data.penny_scan.ema_trend === 'down' ? 'bg-red-400' : 'bg-zinc-500'}`} />
                <span className="text-zinc-500 w-20">EMA trend</span>
                <span className="capitalize">{data.penny_scan.ema_trend}</span>
              </div>
              <div className="text-[10px] flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${data.penny_scan.rsi >= 40 && data.penny_scan.rsi <= 65 ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                <span className="text-zinc-500 w-20">RSI</span>
                <span>{data.penny_scan.rsi?.toFixed(1)}</span>
              </div>
              <div className="text-[10px] flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${data.penny_scan.adx > 25 ? 'bg-emerald-400' : 'bg-zinc-500'}`} />
                <span className="text-zinc-500 w-20">ADX</span>
                <span>{data.penny_scan.adx?.toFixed(1)}</span>
              </div>
              <div className="text-[10px] flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${data.penny_scan.momentum_5d > 2 ? 'bg-emerald-400' : data.penny_scan.momentum_5d < -2 ? 'bg-red-400' : 'bg-zinc-500'}`} />
                <span className="text-zinc-500 w-20">Mom 5d</span>
                <span>{data.penny_scan.momentum_5d?.toFixed(1)}%</span>
              </div>
              {data.penny_scan.volume_surge && (
                <div className="text-[10px] flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  <span className="text-zinc-500 w-20">Vol surge</span>
                  <span>{data.penny_scan.relative_volume?.toFixed(1)}x</span>
                </div>
              )}
            </>
          ) : (
            <div className="text-[10px] text-zinc-500">No signals available</div>
          )}
        </div>
      </div>
    </div>
  );
}

function DailyStockCard({ ticker, price, target, stopLoss, horizon, children, onExpand, isExpanded, badge, badgeColor }: {
  ticker: string; price: number; target: number; stopLoss: number; horizon: string;
  children?: React.ReactNode; onExpand: () => void; isExpanded: boolean;
  badge?: string; badgeColor?: 'emerald' | 'blue' | 'amber';
}) {
  const cleanTicker = ticker.replace('.NS', '').replace('.BO', '');
  const risk = price - stopLoss;
  const reward = target - price;
  const rr = risk > 0 ? (reward / risk) : 0;
  const badgeClasses = badgeColor === 'emerald' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
    : badgeColor === 'blue' ? 'bg-blue-500/20 text-blue-400 border-blue-500/30'
    : 'bg-amber-500/20 text-amber-400 border-amber-500/30';
  return (
    <div className={`rounded-lg border transition-colors ${isExpanded ? 'border-amber-500/40 bg-amber-500/5' : 'border-border/40 bg-muted/20 hover:border-border/60'}`}>
      <button onClick={onExpand} className="w-full text-left p-3 space-y-2 cursor-pointer">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{cleanTicker}</span>
            {badge && <span className={`text-[9px] px-1.5 py-0.5 rounded border font-semibold ${badgeClasses}`}>{badge}</span>}
          </div>
          <span className="text-xs font-mono">{formatINR(price, 2)}</span>
        </div>
        {children}
        <div className="flex items-center gap-3 text-[10px]">
          <TimeHorizonBadge horizon={horizon} />
          {target > 0 && <span><span className="text-zinc-500">Target: </span><span className="text-emerald-400 font-mono">{formatINR(target, 2)}</span></span>}
          {stopLoss > 0 && <span><span className="text-zinc-500">SL: </span><span className="text-red-400 font-mono">{formatINR(stopLoss, 2)}</span></span>}
          {rr > 0 && <span><span className="text-zinc-500">R:R </span><span className="font-mono">{rr.toFixed(1)}</span></span>}
        </div>
      </button>
      {isExpanded && <StockDetailPanel ticker={ticker} onClose={onExpand} />}
    </div>
  );
}

/* ── Penny Scanner Section (Full AI Pipeline) ─────────────────────── */

interface PennyScanStock {
  ticker: string; last_close: number; current_price?: number; target_price: number; stop_loss: number;
  risk_reward: number; time_horizon: string; rsi?: number; adx?: number; ema_trend: string;
  momentum_5d: number; momentum_20d?: number; volume_surge: boolean; relative_volume: number;
  avg_volume_20d: number; swing_high: number; swing_low: number; reasoning: string;
  recommendation?: string; ai_action?: string; ai_score?: number; ai_confidence?: number;
  ai_reasoning?: string; technical_score?: number; signal?: string;
  signal_breakdown?: Record<string, number>; price_updated_at?: string; change_1d_pct?: number;
  score?: number;
}

interface PennyScanData {
  scan_time: string | null;
  total_scanned: number;
  total_scans?: number;
  prices_refreshed_at?: string;
  strong_buys?: PennyScanStock[];
  buys?: PennyScanStock[];
  results: PennyScanStock[];
  all_analyzed?: PennyScanStock[];
  last_batch?: string[];
}

interface PennyProgress {
  stage: string; detail: string; stocks_done: number; stocks_total: number; started_at?: string;
}

const PENNY_STAGE_LABELS: Record<string, string> = {
  starting: 'Initializing',
  init: 'Building stock universe',
  scanning: 'Technical pre-filter',
  enriching: 'Enriching candidates',
  ai_agents: 'Running AI agents + swarm',
  meta_analysis: 'Meta-analyst fusion',
  finalizing: 'Filtering for buy signals',
  done: 'Complete',
};

function PennyScanSection() {
  const [data, setData] = useState<PennyScanData | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState<PennyProgress | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [expandedStock, setExpandedStock] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchResults = async (withLivePrices = false) => {
    try {
      const url = withLivePrices
        ? `${API_BASE}/algo-trader/penny-scanner/results?refresh_prices=true`
        : `${API_BASE}/algo-trader/penny-scanner/results`;
      const r = await fetch(url);
      const d = await r.json();
      setData(d);
    } catch { /* ignore */ }
  };

  const handleRefreshPrices = async () => {
    setRefreshing(true);
    await fetchResults(true);
    setRefreshing(false);
  };

  useEffect(() => {
    fetchResults();
    // Check if a scan is already running
    fetch(`${API_BASE}/algo-trader/penny-scanner/status`).then(r => r.json()).then(st => {
      if (st.scanning) {
        setScanning(true);
        if (st.progress) setProgress(st.progress);
        startPolling();
      }
    }).catch(() => {});
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // Listen for SSE progress events
  useEffect(() => {
    const handleSSE = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.type === 'penny_progress') {
        setProgress({ stage: detail.stage, detail: detail.detail, stocks_done: detail.stocks_done, stocks_total: detail.stocks_total });
      }
    };
    window.addEventListener('sse-event', handleSSE);
    return () => window.removeEventListener('sse-event', handleSSE);
  }, []);

  const startPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    let ticks = 0;
    pollRef.current = setInterval(async () => {
      ticks++;
      try {
        const resp = await fetch(`${API_BASE}/algo-trader/penny-scanner/status`);
        const st = await resp.json();
        if (st.progress) setProgress(st.progress);
        if (!st.scanning) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setScanning(false);
          setProgress(null);
          await fetchResults();
        }
      } catch { /* ignore */ }
      if (ticks > 300) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setScanning(false);
        setProgress(null);
        await fetchResults();
      }
    }, 4000);
  };

  const handleScan = async () => {
    setScanning(true);
    setProgress({ stage: 'starting', detail: 'Initializing...', stocks_done: 0, stocks_total: 0 });
    try {
      await fetch(`${API_BASE}/algo-trader/penny-scanner/scan`, { method: 'POST' });
      startPolling();
    } catch { setScanning(false); setProgress(null); }
  };

  const toggleStock = (t: string) => setExpandedStock(prev => prev === t ? null : t);

  const strongBuys = data?.strong_buys ?? [];
  const regularBuys = data?.buys ?? [];
  const allBuys = [...strongBuys, ...regularBuys];
  const totalScans = data?.total_scans ?? 0;

  return (
    <div className="rounded-xl border border-amber-500/30 bg-card/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-accent/20 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <TrendingUp size={16} className="text-amber-400" />
          <span className="text-sm font-semibold">Penny AI Scanner</span>
          {strongBuys.length > 0 && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-semibold">{strongBuys.length} Strong Buy</span>
          )}
          {regularBuys.length > 0 && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 font-semibold">{regularBuys.length} Buy</span>
          )}
          {totalScans > 0 && (
            <span className="text-[10px] text-muted-foreground/50">{totalScans} scan{totalScans > 1 ? 's' : ''}</span>
          )}
          {data?.scan_time && (
            <span className="text-[10px] text-muted-foreground">{new Date(data.scan_time).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
          )}
          {scanning && <Loader2 size={12} className="animate-spin text-amber-400" />}
        </div>
        <div className="flex items-center gap-2">
          {expanded && allBuys.length > 0 && !scanning && (
            <button
              onClick={(e) => { e.stopPropagation(); handleRefreshPrices(); }}
              disabled={refreshing}
              className="text-[10px] px-2.5 py-1 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors disabled:opacity-50 cursor-pointer"
            >
              {refreshing ? <Loader2 size={10} className="animate-spin inline mr-1" /> : <RefreshCw size={10} className="inline mr-1" />}
              {refreshing ? 'Refreshing...' : 'Live Prices'}
            </button>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); handleScan(); }}
            disabled={scanning}
            className="text-[10px] px-2.5 py-1 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 transition-colors disabled:opacity-50 cursor-pointer"
          >
            {scanning ? <Loader2 size={10} className="animate-spin inline mr-1" /> : <Search size={10} className="inline mr-1" />}
            {scanning ? 'AI Scanning...' : 'Discover New Penny Stocks'}
          </button>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-amber-500/20 px-5 py-4">
          {scanning && progress && (
            <div className="mb-4 rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 text-amber-400">
                  <Loader2 size={12} className="animate-spin" />
                  <span className="font-medium">{PENNY_STAGE_LABELS[progress.stage] || progress.stage}</span>
                  {progress.started_at && <ElapsedTimer startedAt={progress.started_at} />}
                </div>
                {progress.stocks_total > 0 && (
                  <span className="text-[10px] text-zinc-400">{progress.stocks_done}/{progress.stocks_total}</span>
                )}
              </div>
              <p className="text-[11px] text-zinc-400">{progress.detail}</p>
              {progress.stocks_total > 0 && (
                <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-amber-500 transition-all duration-500"
                    style={{ width: `${Math.min(100, (progress.stocks_done / progress.stocks_total) * 100)}%` }}
                  />
                </div>
              )}
              <p className="text-[10px] text-zinc-500">Full AI analysis takes 2-5 minutes per batch</p>
            </div>
          )}

          {!scanning && allBuys.length === 0 && (
            <div className="text-center py-6 text-sm text-muted-foreground">
              {totalScans > 0
                ? 'No AI buy signals found yet. Click Discover New Penny Stocks to scan more.'
                : 'Click Discover New Penny Stocks to run a full AI analysis on sub-₹100 stocks.'}
            </div>
          )}

          {strongBuys.length > 0 && (
            <div className="mb-4">
              <h4 className="text-xs font-semibold text-emerald-400 mb-2 flex items-center gap-1.5">
                <TrendingUp size={12} /> Strong Buys ({strongBuys.length})
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {strongBuys.map(p => (
                  <PennyAICard key={p.ticker} stock={p} isExpanded={expandedStock === p.ticker} onToggle={() => toggleStock(p.ticker)} rec="strong_buy" />
                ))}
              </div>
            </div>
          )}

          {regularBuys.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-blue-400 mb-2 flex items-center gap-1.5">
                <TrendingUp size={12} /> Buys ({regularBuys.length})
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {regularBuys.map(p => (
                  <PennyAICard key={p.ticker} stock={p} isExpanded={expandedStock === p.ticker} onToggle={() => toggleStock(p.ticker)} rec="buy" />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PennyAICard({ stock: p, isExpanded, onToggle, rec }: { stock: PennyScanStock; isExpanded: boolean; onToggle: () => void; rec: string }) {
  const cleanTicker = p.ticker.replace('.NS', '').replace('.BO', '');
  const price = p.current_price || p.last_close;
  const badgeColor = rec === 'strong_buy' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-blue-500/20 text-blue-400 border-blue-500/30';
  const badgeText = rec === 'strong_buy' ? 'Strong Buy' : 'Buy';
  return (
    <div className={`rounded-lg border transition-colors ${isExpanded ? 'border-amber-500/40 bg-amber-500/5' : 'border-border/40 bg-muted/20 hover:border-border/60'}`}>
      <button onClick={onToggle} className="w-full text-left p-3 space-y-2 cursor-pointer">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{cleanTicker}</span>
            <span className={`text-[9px] px-1.5 py-0.5 rounded border font-semibold ${badgeColor}`}>{badgeText}</span>
          </div>
          <span className="text-xs font-mono">{formatINR(price, 2)}</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {p.ai_score != null && <span className="text-[10px] text-amber-400 font-mono">AI: {p.ai_score.toFixed(3)}</span>}
          {p.ai_confidence != null && <span className="text-[10px] text-zinc-400">conf {(p.ai_confidence * 100).toFixed(0)}%</span>}
          {p.change_1d_pct != null && <span className={`text-[10px] ${p.change_1d_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{p.change_1d_pct >= 0 ? '+' : ''}{p.change_1d_pct.toFixed(1)}%</span>}
          {p.rsi != null && <span className="text-[10px] text-zinc-400">RSI {p.rsi.toFixed(0)}</span>}
          {p.volume_surge && <span className="text-[10px] text-amber-400">Vol {p.relative_volume.toFixed(1)}x</span>}
          {p.price_updated_at && <span className="text-[9px] text-emerald-500/60">LIVE</span>}
        </div>
        <div className="flex items-center gap-3 text-[10px]">
          <TimeHorizonBadge horizon={p.time_horizon} />
          {p.target_price > 0 && <span><span className="text-zinc-500">Target: </span><span className="text-emerald-400 font-mono">{formatINR(p.target_price, 2)}</span></span>}
          {p.stop_loss > 0 && <span><span className="text-zinc-500">SL: </span><span className="text-red-400 font-mono">{formatINR(p.stop_loss, 2)}</span></span>}
          {p.risk_reward > 0 && <span><span className="text-zinc-500">R:R </span><span className="font-mono">{p.risk_reward.toFixed(1)}</span></span>}
        </div>
        {p.ai_reasoning && <p className="text-[10px] text-zinc-500 leading-relaxed line-clamp-2">{p.ai_reasoning}</p>}
        {p.signal_breakdown && Object.keys(p.signal_breakdown).length > 0 && (
          <div className="flex items-center gap-2 text-[10px]">
            {p.signal_breakdown.bullish_pct != null && <span className="text-emerald-400">{p.signal_breakdown.bullish_pct.toFixed(0)}% bullish</span>}
            {p.signal_breakdown.bearish_pct != null && <span className="text-red-400">{p.signal_breakdown.bearish_pct.toFixed(0)}% bearish</span>}
            <span className="text-zinc-500">({p.signal_breakdown.total || 0} agents)</span>
          </div>
        )}
      </button>
      {isExpanded && <StockDetailPanel ticker={p.ticker} onClose={onToggle} />}
    </div>
  );
}

/* ── Market Discovery Section — Strong Buys Only ─────────────────── */

interface DiscoveryStock {
  ticker: string; discovered_at?: string; current_price: number | null; change_1d_pct: number | null;
  rsi: number | null; trend: string; ema50: number | null; ema200: number | null;
  high_52w: number | null; low_52w: number | null; action: string; score: number;
  confidence: number; reasoning: string; target_price: number; stop_loss: number;
  time_horizon: string; risk_reward_ratio: number; signal: string;
  signal_breakdown?: { bullish: number; bearish: number; neutral: number; total: number; bullish_pct: number; bearish_pct: number };
  analyst_signals?: Record<string, { signal: string; confidence: number; reasoning?: string }>;
}

interface DiscoveryReport {
  generated_at?: string;
  strong_buys?: DiscoveryStock[];
  buys?: DiscoveryStock[];
  all_analyzed?: DiscoveryStock[];
  total_scans?: number;
  last_batch?: string[];
}

const STAGE_LABELS: Record<string, string> = {
  starting: 'Initializing',
  init: 'Building stock universe',
  enriching: 'Fetching live technicals',
  ai_agents: 'Running AI swarm (21 agents)',
  meta_analysis: 'Running meta-analyst fusion',
  finalizing: 'Saving results',
};

function ElapsedTimer({ startedAt }: { startedAt: string | null }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!startedAt) return;
    const start = new Date(startedAt).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - start) / 1000));
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, [startedAt]);
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  return <span className="font-mono text-[11px]">{m}:{s.toString().padStart(2, '0')}</span>;
}

function DiscoverySection() {
  const [report, setReport] = useState<DiscoveryReport | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [running, setRunning] = useState(false);
  const [schedulerOn, setSchedulerOn] = useState(false);
  const [expandedStock, setExpandedStock] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ stage: string; detail: string; stocks_done: number; stocks_total: number; started_at: string } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchResults = async () => {
    try {
      const r = await fetch(`${API_BASE}/algo-trader/discovery/results`);
      const d = await r.json();
      if (d.report) setReport(d.report);
    } catch { /* ignore */ }
  };

  const fetchStatus = async () => {
    try {
      const r = await fetch(`${API_BASE}/algo-trader/discovery/status`);
      const d = await r.json();
      setSchedulerOn(d.scheduler_running || false);
      if (d.running) {
        setRunning(true);
        if (d.progress) setProgress(d.progress);
      } else {
        setRunning(prev => {
          if (prev) fetchResults();
          return false;
        });
        setProgress(null);
      }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    fetchResults();
    fetchStatus();

    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/algo-trader/stream`);
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === 'discovery_progress') {
            setProgress(prev => ({
              stage: data.stage || prev?.stage || '',
              detail: data.detail || '',
              stocks_done: data.stocks_done ?? prev?.stocks_done ?? 0,
              stocks_total: data.stocks_total ?? prev?.stocks_total ?? 0,
              started_at: prev?.started_at || new Date().toISOString(),
            }));
          } else if (data.type === 'discovery' && data.msg?.includes('complete')) {
            setRunning(false);
            setProgress(null);
            fetchResults();
          }
        } catch { /* ignore */ }
      };
    } catch { /* SSE not available */ }

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (es) es.close();
    };
  }, []);

  const handleDiscover = async () => {
    setRunning(true);
    setExpanded(true);
    setProgress({ stage: 'starting', detail: 'Initializing...', stocks_done: 0, stocks_total: 4, started_at: new Date().toISOString() });
    try {
      const resp = await fetch(`${API_BASE}/algo-trader/discovery/generate`, { method: 'POST' });
      const d = await resp.json();
      if (!d.running) {
        setRunning(false);
        setProgress(null);
        return;
      }
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const sr = await fetch(`${API_BASE}/algo-trader/discovery/status`);
          const st = await sr.json();
          if (st.progress) setProgress(prev => ({ ...prev, ...st.progress }));
          if (!st.running) {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setRunning(false);
            setProgress(null);
            await fetchResults();
          }
        } catch { /* ignore */ }
      }, 4000);
    } catch {
      setRunning(false);
      setProgress(null);
    }
  };

  const toggleScheduler = async () => {
    try {
      if (schedulerOn) {
        await fetch(`${API_BASE}/algo-trader/discovery/schedule/stop`, { method: 'POST' });
        setSchedulerOn(false);
      } else {
        await fetch(`${API_BASE}/algo-trader/discovery/schedule`, { method: 'POST' });
        setSchedulerOn(true);
      }
    } catch { /* ignore */ }
  };

  const handleClear = async () => {
    await fetch(`${API_BASE}/algo-trader/discovery/clear`, { method: 'POST' });
    setReport(null);
  };

  const toggleStock = (t: string) => setExpandedStock(prev => prev === t ? null : t);

  const strongBuys = report?.strong_buys || [];
  const buys = report?.buys || [];
  const totalBuySignals = strongBuys.length + buys.length;

  return (
    <div className="rounded-xl border border-emerald-500/30 bg-card/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-accent/20 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <Zap size={16} className="text-emerald-400" />
          <span className="text-sm font-semibold">AI Discovery</span>
          {running && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 animate-pulse flex items-center gap-1">
              <Loader2 size={8} className="animate-spin" /> SCANNING
            </span>
          )}
          {!running && strongBuys.length > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
              {strongBuys.length} strong
            </span>
          )}
          {!running && buys.length > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-400 border border-blue-500/20">
              {buys.length} buy
            </span>
          )}
          {report?.total_scans ? (
            <span className="text-[10px] text-muted-foreground">{report.total_scans} scans</span>
          ) : null}
          {schedulerOn && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 animate-pulse">AUTO</span>
          )}
          {!running && report?.generated_at && (
            <span className="text-[10px] text-muted-foreground">{new Date(report.generated_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); toggleScheduler(); }}
            className={`text-[10px] px-2.5 py-1 rounded-md border transition-colors cursor-pointer ${
              schedulerOn
                ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/20'
                : 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20 hover:bg-emerald-500/10 hover:text-emerald-400 hover:border-emerald-500/20'
            }`}
          >
            {schedulerOn ? 'Stop Auto' : 'Auto (1h)'}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); handleDiscover(); }}
            disabled={running}
            className="text-[10px] px-2.5 py-1 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors disabled:opacity-50 cursor-pointer"
          >
            {running ? <Loader2 size={10} className="animate-spin inline mr-1" /> : <Zap size={10} className="inline mr-1" />}
            {running ? 'Scanning...' : 'Discover Now'}
          </button>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-emerald-500/20 px-5 py-4 space-y-4">
          {running && progress && (
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium text-emerald-400">
                  <Loader2 size={14} className="animate-spin" />
                  {STAGE_LABELS[progress.stage] || progress.stage || 'Processing...'}
                </div>
                <div className="flex items-center gap-2 text-emerald-400/70">
                  <Clock size={12} />
                  <ElapsedTimer startedAt={progress.started_at || null} />
                </div>
              </div>
              {progress.detail && (
                <p className="text-xs text-emerald-400/60">{progress.detail}</p>
              )}
              {progress.stocks_total > 0 && (
                <div className="space-y-1">
                  <div className="flex justify-between text-[10px] text-emerald-400/50">
                    <span>Progress</span>
                    <span>{progress.stocks_done}/{progress.stocks_total} stocks</span>
                  </div>
                  <div className="h-1.5 bg-emerald-900/30 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-emerald-500/60 rounded-full transition-all duration-700"
                      style={{ width: `${Math.max(5, (progress.stocks_done / progress.stocks_total) * 100)}%` }}
                    />
                  </div>
                </div>
              )}
              <p className="text-[10px] text-emerald-400/40">
                Full AI swarm analysis takes 2–5 minutes per stock. Please wait...
              </p>
            </div>
          )}

          {running && !progress && (
            <div className="flex items-center gap-2 text-sm text-emerald-400 py-4 justify-center">
              <Loader2 size={14} className="animate-spin" /> Starting discovery scan...
            </div>
          )}

          {!running && totalBuySignals === 0 && (
            <div className="text-center py-6 text-sm text-muted-foreground">
              No buy signals discovered yet. Click <strong>Discover Now</strong> or enable <strong>Auto (1h)</strong> to scan 4 random stocks every hour with full AI analysis.
            </div>
          )}

          {totalBuySignals > 0 && (
            <>
              {report?.last_batch && (
                <div className="text-[10px] text-zinc-500">
                  Last batch: {report.last_batch.join(', ')} — {report.total_scans} total scans
                  <button onClick={handleClear} className="ml-3 text-red-400 hover:text-red-300 cursor-pointer">Clear all</button>
                </div>
              )}

              {strongBuys.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <Zap size={10} /> Strong Buys ({strongBuys.length})
                  </h4>
                  <div className="space-y-3">
                    {strongBuys.map(s => (
                      <DiscoveryStockCard key={s.ticker} stock={s} />
                    ))}
                  </div>
                </div>
              )}

              {buys.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-semibold text-blue-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <TrendingUp size={10} /> Buys ({buys.length})
                  </h4>
                  <div className="space-y-3">
                    {buys.map(s => (
                      <DiscoveryStockCard key={s.ticker} stock={s} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Daily Analysis Section (AI-powered analysis, separate from penny scan) ── */

function DailyAnalysisSection() {
  const [report, setReport] = useState<DailyReport | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [expandedStock, setExpandedStock] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchReport = async () => {
    try {
      const resp = await fetch(`${API_BASE}/algo-trader/daily-analysis`);
      const d = await resp.json();
      if (d.report) setReport(d.report);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    fetchReport();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await fetch(`${API_BASE}/algo-trader/daily-analysis/generate`, { method: 'POST' });
      if (pollRef.current) clearInterval(pollRef.current);
      let ticks = 0;
      pollRef.current = setInterval(async () => {
        ticks++;
        try {
          const resp = await fetch(`${API_BASE}/algo-trader/daily-analysis/status`);
          const st = await resp.json();
          if (!st.generating) {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setGenerating(false);
            await fetchReport();
          }
        } catch { /* ignore */ }
        if (ticks > 60) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setGenerating(false);
          await fetchReport();
        }
      }, 3000);
    } catch { setGenerating(false); }
  };

  const toggleStock = (ticker: string) => setExpandedStock(prev => prev === ticker ? null : ticker);

  const mkt = report?.market_overview;
  const vs = report?.verdict_summary;

  return (
    <div className="rounded-xl border border-blue-500/30 bg-card/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-accent/20 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <Sparkles size={16} className="text-blue-400" />
          <span className="text-sm font-semibold">Daily Analysis</span>
          {report?.generated_at && (
            <span className="text-[10px] text-muted-foreground">{new Date(report.generated_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
          )}
          {mkt?.trend && (
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
              mkt.trend === 'bullish' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'
            }`}>
              {mkt.index} {mkt.trend === 'bullish' ? '▲' : '▼'} {mkt.change_1d_pct?.toFixed(1)}%
            </span>
          )}
          {vs && vs.total > 0 && (
            <span className="text-[10px] text-muted-foreground">{vs.buys}B / {vs.holds}H / {vs.sells}S</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {generating && (
            <span className="text-[10px] text-blue-400 flex items-center gap-1">
              <Loader2 size={10} className="animate-spin" /> Generating...
            </span>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); handleGenerate(); }}
            disabled={generating}
            className="text-[10px] px-2.5 py-1 rounded-md bg-blue-500/10 text-blue-400 border border-blue-500/20 hover:bg-blue-500/20 transition-colors disabled:opacity-50 cursor-pointer"
          >
            {generating ? <Loader2 size={10} className="animate-spin inline mr-1" /> : <RefreshCw size={10} className="inline mr-1" />}
            {generating ? 'Generating...' : 'Generate Analysis'}
          </button>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-blue-500/20 px-5 py-4 space-y-5">

          {!report && !generating && (
            <div className="text-center py-6 text-sm text-muted-foreground">
              No daily analysis available. Click <strong>Generate Analysis</strong> to run full AI review with targets, verdicts, and portfolio recommendations.
            </div>
          )}

          {generating && (
            <div className="flex items-center gap-2 text-sm text-blue-400 py-4 justify-center">
              <Loader2 size={14} className="animate-spin" /> Running AI analysis... this may take a minute
            </div>
          )}

          {/* Strong Buys — prominent section */}
          {report?.strong_buys && report.strong_buys.length > 0 && (
            <div>
              <h3 className="flex items-center gap-2 text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-3">
                <TrendingUp size={13} /> Strong Buys ({report.strong_buys.length})
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {report.strong_buys.map((sb: any) => {
                  const tk = sb.ticker;
                  const isBig = sb.action?.toLowerCase().includes('strong');
                  return (
                    <div key={tk} className={`rounded-lg border transition-colors ${expandedStock === tk ? 'border-emerald-500/40 bg-emerald-500/5' : isBig ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-border/40 bg-muted/20'}`}>
                      <button onClick={() => toggleStock(tk)} className="w-full text-left p-3 space-y-2 cursor-pointer">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold">{tk.replace('.NS', '')}</span>
                            <ActionBadge action={sb.action} />
                          </div>
                          {sb.current_price && <span className="text-xs font-mono">{formatINR(sb.current_price, 2)}</span>}
                        </div>
                        <div className="flex items-center gap-3 text-[10px]">
                          {sb.target_price > 0 && <span><span className="text-zinc-500">Target: </span><span className="text-emerald-400 font-mono">{formatINR(sb.target_price, 2)}</span></span>}
                          {sb.stop_loss > 0 && <span><span className="text-zinc-500">SL: </span><span className="text-red-400 font-mono">{formatINR(sb.stop_loss, 2)}</span></span>}
                          {sb.time_horizon && <TimeHorizonBadge horizon={sb.time_horizon} />}
                          {sb.risk_reward_ratio > 0 && <span><span className="text-zinc-500">R:R </span><span className="font-mono">{sb.risk_reward_ratio.toFixed(1)}</span></span>}
                          <span className="text-zinc-500 ml-auto">Conf: <span className="font-mono">{(Number(sb.confidence || 0) * 100).toFixed(0)}%</span></span>
                        </div>
                        {sb.reasoning && <p className="text-[10px] text-zinc-500 leading-relaxed">{sb.reasoning.slice(0, 150)}</p>}
                      </button>
                      {expandedStock === tk && <StockDetailPanel ticker={tk} onClose={() => toggleStock(tk)} />}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Target Signals table */}
          {report?.target_signals && report.target_signals.length > 0 && (
            <div>
              <h3 className="flex items-center gap-2 text-xs font-semibold text-blue-400 uppercase tracking-wider mb-3">
                <Target size={13} /> Price Targets & Signals ({report.target_signals.length})
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-zinc-500 border-b border-border/30">
                      <th className="text-left py-1.5 px-2">Ticker</th>
                      <th className="text-left py-1.5 px-2">Action</th>
                      <th className="text-left py-1.5 px-2">Signal</th>
                      <th className="text-right py-1.5 px-2">Target</th>
                      <th className="text-right py-1.5 px-2">Stop Loss</th>
                      <th className="text-center py-1.5 px-2">Horizon</th>
                      <th className="text-right py-1.5 px-2">R:R</th>
                      <th className="text-right py-1.5 px-2">Conf</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.target_signals.map((t: any) => (
                      <React.Fragment key={t.ticker}>
                        <tr onClick={() => toggleStock(t.ticker)} className={`border-b border-border/20 cursor-pointer transition-colors ${expandedStock === t.ticker ? 'bg-blue-500/5' : 'hover:bg-accent/10'}`}>
                          <td className="py-1.5 px-2 font-semibold">{t.ticker.replace('.NS', '')}</td>
                          <td className="py-1.5 px-2">{t.meta_action ? <ActionBadge action={t.meta_action} /> : <span className="text-zinc-500">—</span>}</td>
                          <td className="py-1.5 px-2"><span className={`${t.signal === 'bullish' ? 'text-emerald-400' : t.signal === 'bearish' ? 'text-red-400' : 'text-zinc-400'}`}>{t.signal}</span></td>
                          <td className="py-1.5 px-2 text-right font-mono text-emerald-400">{formatINR(t.target_price, 2)}</td>
                          <td className="py-1.5 px-2 text-right font-mono text-red-400">{formatINR(t.stop_loss, 2)}</td>
                          <td className="py-1.5 px-2 text-center"><TimeHorizonBadge horizon={t.time_horizon} /></td>
                          <td className="py-1.5 px-2 text-right font-mono">{t.risk_reward_ratio?.toFixed(2)}</td>
                          <td className="py-1.5 px-2 text-right font-mono">{t.confidence?.toFixed(0)}%</td>
                        </tr>
                        {expandedStock === t.ticker && <tr><td colSpan={8} className="p-0"><StockDetailPanel ticker={t.ticker} onClose={() => toggleStock(t.ticker)} /></td></tr>}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* All Analyzed Stocks — full batch */}
          {report?.all_verdicts && report.all_verdicts.length > 0 && (
            <div>
              <h3 className="flex items-center gap-2 text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
                <BarChart3 size={13} /> All Analyzed ({report.all_verdicts.length})
              </h3>
              <div className="overflow-x-auto max-h-80 overflow-y-auto">
                <table className="w-full text-[11px]">
                  <thead className="sticky top-0 bg-card z-10">
                    <tr className="text-zinc-500 border-b border-border/30">
                      <th className="text-left py-1.5 px-2">Ticker</th>
                      <th className="text-left py-1.5 px-2">Verdict</th>
                      <th className="text-right py-1.5 px-2">Score</th>
                      <th className="text-right py-1.5 px-2">Price</th>
                      <th className="text-right py-1.5 px-2">1D</th>
                      <th className="text-center py-1.5 px-2">Agents</th>
                      <th className="text-right py-1.5 px-2">Bull%</th>
                      <th className="text-right py-1.5 px-2">Conf</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.all_verdicts.map((v: DailyVerdict) => {
                      const act = v.action?.toLowerCase() || 'hold';
                      const isBuy = act.includes('buy');
                      const isSell = act.includes('sell');
                      return (
                        <React.Fragment key={v.ticker}>
                          <tr
                            onClick={() => toggleStock(v.ticker)}
                            className={`border-b border-border/20 cursor-pointer transition-colors ${
                              expandedStock === v.ticker ? (isBuy ? 'bg-emerald-500/5' : isSell ? 'bg-red-500/5' : 'bg-accent/10')
                              : 'hover:bg-accent/10'
                            }`}
                          >
                            <td className="py-1.5 px-2 font-semibold">{v.ticker.replace('.NS', '').replace('.BO', '')}</td>
                            <td className="py-1.5 px-2"><ActionBadge action={v.action} /></td>
                            <td className={`py-1.5 px-2 text-right font-mono ${v.score > 0 ? 'text-emerald-400' : v.score < 0 ? 'text-red-400' : 'text-zinc-400'}`}>
                              {v.score > 0 ? '+' : ''}{v.score.toFixed(2)}
                            </td>
                            <td className="py-1.5 px-2 text-right font-mono">{v.current_price ? formatINR(v.current_price, 2) : '—'}</td>
                            <td className={`py-1.5 px-2 text-right font-mono ${(v.change_1d_pct || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {v.change_1d_pct != null ? `${v.change_1d_pct >= 0 ? '+' : ''}${v.change_1d_pct.toFixed(1)}%` : '—'}
                            </td>
                            <td className="py-1.5 px-2 text-center">{v.total_agents || '—'}</td>
                            <td className={`py-1.5 px-2 text-right font-mono ${(v.bullish_pct || 0) > 50 ? 'text-emerald-400' : (v.bullish_pct || 0) < 30 ? 'text-red-400' : 'text-zinc-400'}`}>
                              {v.bullish_pct != null ? `${v.bullish_pct.toFixed(0)}%` : '—'}
                            </td>
                            <td className="py-1.5 px-2 text-right font-mono">{(Number(v.confidence || 0) * 100).toFixed(0)}%</td>
                          </tr>
                          {expandedStock === v.ticker && (
                            <tr>
                              <td colSpan={8} className="p-0">
                                <div className="px-3 py-2 bg-accent/5 border-b border-border/20">
                                  <p className="text-[10px] text-zinc-500 leading-relaxed mb-1">{v.reasoning}</p>
                                  <div className="flex gap-3 text-[10px] mt-1">
                                    {v.target_price > 0 && <span><span className="text-zinc-500">Target: </span><span className="text-emerald-400 font-mono">{formatINR(v.target_price, 2)}</span></span>}
                                    {v.stop_loss > 0 && <span><span className="text-zinc-500">SL: </span><span className="text-red-400 font-mono">{formatINR(v.stop_loss, 2)}</span></span>}
                                    {v.time_horizon && <TimeHorizonBadge horizon={v.time_horizon} />}
                                  </div>
                                </div>
                                <StockDetailPanel ticker={v.ticker} onClose={() => toggleStock(v.ticker)} />
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Portfolio Balance */}
          {report?.portfolio_balance?.current_allocation && Object.keys(report.portfolio_balance.current_allocation).length > 0 && (
            <div>
              <h3 className="flex items-center gap-2 text-xs font-semibold text-purple-400 uppercase tracking-wider mb-3">
                <BarChart3 size={13} /> Portfolio Balance
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-[10px] text-zinc-500 mb-2">Current Allocation</div>
                  {(['large', 'mid', 'small'] as const).map(cat => {
                    const pct = report!.portfolio_balance!.current_allocation![cat] || 0;
                    const color = cat === 'large' ? 'bg-blue-500' : cat === 'mid' ? 'bg-purple-500' : 'bg-amber-500';
                    return (
                      <div key={cat} className="flex items-center gap-2 mb-1.5">
                        <span className="text-[10px] w-12 capitalize text-zinc-400">{cat}</span>
                        <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden"><div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} /></div>
                        <span className="text-[10px] font-mono w-10 text-right">{pct}%</span>
                      </div>
                    );
                  })}
                </div>
                <div>
                  <div className="text-[10px] text-zinc-500 mb-1">Recommended ({report.portfolio_balance.recommended_profile})</div>
                  {(['large', 'mid', 'small'] as const).map(cat => {
                    const pct = report!.portfolio_balance!.recommended_allocation?.[cat] || 0;
                    const color = cat === 'large' ? 'bg-blue-500/50' : cat === 'mid' ? 'bg-purple-500/50' : 'bg-amber-500/50';
                    return (
                      <div key={cat} className="flex items-center gap-2 mb-1.5">
                        <span className="text-[10px] w-12 capitalize text-zinc-400">{cat}</span>
                        <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden"><div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} /></div>
                        <span className="text-[10px] font-mono w-10 text-right">{pct}%</span>
                      </div>
                    );
                  })}
                </div>
              </div>
              {report.portfolio_balance.suggestions && report.portfolio_balance.suggestions.length > 0 && (
                <div className="mt-3 space-y-1">
                  {report.portfolio_balance.suggestions.map((s: any, i: number) => (
                    <div key={i} className={`text-[10px] px-2 py-1 rounded border ${
                      s.action === 'trim' ? 'border-red-500/20 bg-red-500/5 text-red-400' : 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400'
                    }`}>
                      <span className="font-semibold uppercase">{s.action}</span> {s.ticker && `${s.ticker} — `}{s.reason}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Portfolio Suggestions */}
          {report?.portfolio_balance?.short_term_picks && report.portfolio_balance.short_term_picks.length > 0 && (
            <div>
              <h3 className="flex items-center gap-2 text-xs font-semibold text-blue-400 uppercase tracking-wider mb-3">
                <Target size={13} /> Portfolio Additions
              </h3>
              <div className="space-y-2">
                {report.portfolio_balance.short_term_picks.map((p: any, i: number) => {
                  const tk = p.ticker || `pick-${i}`;
                  return (
                    <div key={tk} className={`rounded-lg border transition-colors ${expandedStock === tk ? 'border-blue-500/40' : 'border-border/40 bg-muted/20'}`}>
                      <button onClick={() => toggleStock(tk)} className="w-full flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-accent/10 transition-colors">
                        <span className="text-sm font-semibold w-24">{(p.ticker || '').replace('.NS', '')}</span>
                        <TimeHorizonBadge horizon={p.time_horizon} />
                        {p.price > 0 && <span className="text-xs font-mono">{formatINR(p.price, 2)}</span>}
                        {p.target_price > 0 && <span className="text-[10px]"><span className="text-zinc-500">Target: </span><span className="text-emerald-400 font-mono">{formatINR(p.target_price, 2)}</span></span>}
                        <span className="text-[10px] text-zinc-600 capitalize ml-auto">{p.source?.replace('_', ' ')}</span>
                      </button>
                      {expandedStock === tk && <StockDetailPanel ticker={tk} onClose={() => toggleStock(tk)} />}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Analysis Library — browse all saved analyses inline ── */

interface HistoryEntry {
  id: string;
  type: 'analysis' | 'flow' | 'discovery' | 'daily' | 'penny';
  timestamp: string | null;
  tickers: string[];
  model: string | null;
  strong_buys_count?: number;
  buys_count?: number;
}

const TYPE_BADGE: Record<string, { label: string; cls: string }> = {
  analysis:  { label: 'Analysis',  cls: 'bg-blue-500/15 text-blue-400 border-blue-500/20' },
  flow:      { label: 'Flow',      cls: 'bg-purple-500/15 text-purple-400 border-purple-500/20' },
  discovery: { label: 'Discovery', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20' },
  daily:     { label: 'Daily',     cls: 'bg-amber-500/15 text-amber-400 border-amber-500/20' },
  penny:     { label: 'Penny',     cls: 'bg-orange-500/15 text-orange-400 border-orange-500/20' },
};

function AnalysisLibrary() {
  const [expanded, setExpanded] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeType, setActiveType] = useState<string | null>(null);
  const [viewerData, setViewerData] = useState<any>(null);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchHistory = useCallback(() => {
    fetch(`${API_BASE}/hedge-fund/analysis-history?limit=30`)
      .then(r => r.json())
      .then(d => {
        const entries: HistoryEntry[] = (d.history || []).map((h: any) => ({
          ...h,
          type: h.type || (h.id?.includes('_discovery_') ? 'discovery' : h.id?.includes('_daily_') ? 'daily' : h.id?.includes('_penny_') ? 'penny' : h.id?.includes('_flow_') ? 'flow' : 'analysis'),
        }));
        setHistory(entries);
      })
      .catch(() => {});
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // Auto-refresh: poll every 30s when expanded, plus SSE-driven refresh on scan completion
  useEffect(() => {
    if (!expanded) return;
    const iv = setInterval(fetchHistory, 30000);
    return () => clearInterval(iv);
  }, [expanded, fetchHistory]);

  useEffect(() => {
    const sse = new EventSource(`${API_BASE}/algo-trader/stream`);
    let debounce: ReturnType<typeof setTimeout> | null = null;
    const refresh = () => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(fetchHistory, 1500);
    };
    sse.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        const t = d.type || '';
        const msg = (d.msg || '').toLowerCase();
        if (t === 'penny_scan' && msg.includes('complete')) refresh();
        else if (t === 'penny_progress' && d.stage === 'done') refresh();
        else if (t === 'discovery' && msg.includes('complete')) refresh();
        else if (t === 'daily_analysis' && msg.includes('ready')) refresh();
        else if (t === 'flow_complete' || t === 'analysis_complete') refresh();
      } catch { /* ignore */ }
    };
    return () => { sse.close(); if (debounce) clearTimeout(debounce); };
  }, [fetchHistory]);

  const openViewer = async (entry: HistoryEntry) => {
    if (activeId === entry.id) {
      setActiveId(null);
      setViewerData(null);
      setActiveType(null);
      return;
    }
    setActiveId(entry.id);
    setActiveType(entry.type);
    setViewerLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/hedge-fund/analysis-history/${entry.id}`);
      if (!resp.ok) throw new Error('Failed to load');
      setViewerData(await resp.json());
    } catch {
      setViewerData(null);
    } finally {
      setViewerLoading(false);
    }
  };

  const closeViewer = () => {
    setActiveId(null);
    setViewerData(null);
    setActiveType(null);
  };

  const deleteOne = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeletingId(id);
    try {
      await fetch(`${API_BASE}/hedge-fund/analysis-history/${id}`, { method: 'DELETE' });
      if (activeId === id) closeViewer();
      fetchHistory();
    } catch {} finally {
      setDeletingId(null);
    }
  };

  const deleteAll = async () => {
    if (!window.confirm('Delete all saved analyses? This cannot be undone.')) return;
    try {
      await fetch(`${API_BASE}/hedge-fund/analysis-history`, { method: 'DELETE' });
      closeViewer();
      fetchHistory();
    } catch {}
  };

  const fmtDate = (ts: string | null) => {
    if (!ts) return '—';
    return new Date(ts).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  };

  const cleanTicker = (t: string) => t.replace('.NS', '').replace('.BO', '');

  return (
    <div className="rounded-xl border border-indigo-500/30 bg-card/50 overflow-hidden">
      <button
        onClick={() => { const next = !expanded; setExpanded(next); if (next) fetchHistory(); }}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-accent/20 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <BookOpen size={16} className="text-indigo-400" />
          <span className="text-sm font-semibold">Analysis Library</span>
          {history.length > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-400 border border-indigo-500/20">
              {history.length} saved
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {expanded && history.length > 0 && (
            <button
              onClick={(e) => { e.stopPropagation(); deleteAll(); }}
              className="text-[10px] text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-red-500/10 transition-colors cursor-pointer"
            >
              Clear All
            </button>
          )}
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-indigo-500/20 px-5 py-4 space-y-4">
          {history.length === 0 ? (
            <p className="text-xs text-muted-foreground py-2 text-center">No saved analyses yet. Run an analysis to see it here.</p>
          ) : (
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {history.map(h => {
                const badge = TYPE_BADGE[h.type] || TYPE_BADGE.analysis;
                const isActive = activeId === h.id;
                return (
                  <div key={h.id}>
                    <div className={`flex items-center gap-2 rounded-lg transition-colors ${isActive ? 'bg-indigo-500/10 border border-indigo-500/25' : 'hover:bg-accent/30'}`}>
                      <button
                        onClick={() => openViewer(h)}
                        className="flex-1 text-left px-3 py-2.5 cursor-pointer flex items-center gap-2 min-w-0"
                      >
                        <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border flex-shrink-0 ${badge.cls}`}>
                          {badge.label}
                        </span>
                        <span className="text-xs font-medium truncate">
                          {h.tickers.length > 0 ? h.tickers.map(cleanTicker).join(', ') : 'Unknown'}
                        </span>
                        {h.strong_buys_count != null && h.strong_buys_count > 0 && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/20 flex-shrink-0">
                            {h.strong_buys_count} {h.type === 'daily' ? 'buy' : 'strong'}
                          </span>
                        )}
                        {h.buys_count != null && h.buys_count > 0 && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-500/15 text-blue-400 border border-blue-500/20 flex-shrink-0">
                            {h.type === 'daily' ? `${h.buys_count} total buys` : `${h.buys_count} buy`}
                          </span>
                        )}
                        <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0 ml-auto">{fmtDate(h.timestamp)}</span>
                      </button>
                      <button
                        onClick={(e) => deleteOne(h.id, e)}
                        className="p-1.5 rounded hover:bg-red-500/15 text-muted-foreground hover:text-red-400 transition-colors cursor-pointer flex-shrink-0 mr-1"
                        title="Delete this analysis"
                      >
                        {deletingId === h.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      </button>
                    </div>

                    {isActive && (
                      <div className="mt-2 mb-3 rounded-lg border border-indigo-500/20 bg-card overflow-hidden">
                        <div className="flex items-center justify-between px-4 py-2 border-b border-border/30 bg-accent/10">
                          <span className="text-xs font-medium flex items-center gap-2">
                            <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border ${badge.cls}`}>{badge.label}</span>
                            {h.tickers.map(cleanTicker).join(', ')}
                            {h.model && <span className="text-muted-foreground">· {h.model}</span>}
                          </span>
                          <button onClick={closeViewer} className="text-muted-foreground hover:text-foreground cursor-pointer p-1 rounded hover:bg-accent/30">
                            <X size={14} />
                          </button>
                        </div>
                        <div className="p-4">
                          {viewerLoading ? (
                            <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-8">
                              <Loader2 size={14} className="animate-spin" /> Loading analysis...
                            </div>
                          ) : !viewerData ? (
                            <p className="text-xs text-muted-foreground text-center py-4">Failed to load analysis data.</p>
                          ) : (
                            <AnalysisViewer type={activeType || 'analysis'} data={viewerData} />
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AnalysisViewer({ type: rawType, data }: { type: string; data: any }) {
  const type = rawType
    || (data.all_verdicts ? 'daily'
      : data.results && !data.all_analyzed ? (data.decisions ? 'flow' : 'analysis')
      : data.strong_buys || data.all_analyzed ? (data.scan_time || data.total_scans != null ? 'penny' : 'discovery')
      : data.decisions ? 'flow'
      : 'analysis');

  if (type === 'penny') {
    const strongBuys = data.strong_buys || [];
    const regularBuys = data.buys || [];
    const allAnalyzed = data.all_analyzed || [];
    const hasBuySignals = strongBuys.length > 0 || regularBuys.length > 0;
    return (
      <div className="space-y-4">
        <div className="flex gap-3 text-[11px] text-zinc-400">
          <span>Scanned: <span className="text-foreground font-semibold">{data.total_scanned || allAnalyzed.length}</span></span>
          {data.scan_time && <span className="text-[10px] text-muted-foreground">{new Date(data.scan_time).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>}
        </div>
        {strongBuys.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Zap size={12} /> Strong Buys ({strongBuys.length})
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {strongBuys.map((s: any) => (
                <PennyLibraryCard key={s.ticker} stock={s} rec="strong_buy" />
              ))}
            </div>
          </div>
        )}
        {regularBuys.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <TrendingUp size={12} /> Buys ({regularBuys.length})
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {regularBuys.map((s: any) => (
                <PennyLibraryCard key={s.ticker} stock={s} rec="buy" />
              ))}
            </div>
          </div>
        )}
        {allAnalyzed.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
              All Analyzed ({allAnalyzed.length})
            </h4>
            <div className="overflow-x-auto max-h-48 overflow-y-auto">
              <table className="w-full text-[10px]">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="text-zinc-500 border-b border-border/30">
                    <th className="text-left py-1 px-1.5">Ticker</th>
                    <th className="text-left py-1 px-1.5">AI Verdict</th>
                    <th className="text-right py-1 px-1.5">Score</th>
                    <th className="text-right py-1 px-1.5">Price</th>
                    <th className="text-right py-1 px-1.5">Conf</th>
                  </tr>
                </thead>
                <tbody>
                  {allAnalyzed.map((s: any) => {
                    const act = (s.ai_action || s.recommendation || 'watch').toLowerCase();
                    const isBuy = act.includes('buy');
                    return (
                      <tr key={s.ticker} className={`border-b border-border/10 ${isBuy ? 'bg-emerald-500/5' : ''}`}>
                        <td className="py-1 px-1.5 font-semibold">{(s.ticker || '').replace('.NS', '').replace('.BO', '')}</td>
                        <td className="py-1 px-1.5"><ActionBadge action={s.ai_action || s.recommendation || 'watch'} /></td>
                        <td className={`py-1 px-1.5 text-right font-mono ${(s.ai_score || s.score || 0) > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {((s.ai_score || s.score || 0) > 0 ? '+' : '')}{(s.ai_score || s.score || 0).toFixed(2)}
                        </td>
                        <td className="py-1 px-1.5 text-right font-mono">{s.current_price || s.last_close ? formatINR(s.current_price || s.last_close, 2) : '—'}</td>
                        <td className="py-1 px-1.5 text-right font-mono">{s.ai_confidence ? `${(s.ai_confidence * 100).toFixed(0)}%` : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {!hasBuySignals && allAnalyzed.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-4">No penny scan data in this save.</p>
        )}
      </div>
    );
  }

  if (type === 'daily') {
    const mkt = data.market_overview;
    const vs = data.verdict_summary;
    const allVerdicts: DailyVerdict[] = data.all_verdicts || [];
    const strongBuys = data.strong_buys || [];
    return (
      <div className="space-y-4">
        {mkt && (
          <div className="flex items-center gap-3 text-[11px]">
            <span className="font-semibold">{mkt.index}</span>
            {mkt.last_close && <span className="font-mono">{formatINR(mkt.last_close, 2)}</span>}
            {mkt.change_1d_pct != null && (
              <span className={mkt.change_1d_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                {mkt.change_1d_pct >= 0 ? '+' : ''}{mkt.change_1d_pct.toFixed(2)}%
              </span>
            )}
            {mkt.trend && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                mkt.trend === 'bullish' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'
              }`}>{mkt.trend}</span>
            )}
          </div>
        )}
        {vs && (
          <div className="flex gap-3 text-[11px]">
            <span className="text-zinc-400">Total: <span className="font-semibold text-foreground">{vs.total}</span></span>
            <span className="text-emerald-400 font-semibold">{vs.buys} Buy</span>
            <span className="text-zinc-400 font-semibold">{vs.holds} Hold</span>
            <span className="text-red-400 font-semibold">{vs.sells} Sell</span>
          </div>
        )}
        {strongBuys.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <TrendingUp size={12} /> Strong Buys ({strongBuys.length})
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {strongBuys.map((sb: any) => (
                <div key={sb.ticker} className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-2.5 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold">{sb.ticker.replace('.NS', '')}</span>
                    <ActionBadge action={sb.action} />
                  </div>
                  <div className="flex gap-2 text-[10px]">
                    {sb.current_price && <span className="font-mono">{formatINR(sb.current_price, 2)}</span>}
                    {sb.target_price > 0 && <span className="text-emerald-400 font-mono">T: {formatINR(sb.target_price, 2)}</span>}
                  </div>
                  {sb.reasoning && <p className="text-[9px] text-zinc-500 leading-relaxed">{sb.reasoning.slice(0, 120)}</p>}
                </div>
              ))}
            </div>
          </div>
        )}
        {allVerdicts.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
              All Analyzed ({allVerdicts.length})
            </h4>
            <div className="overflow-x-auto max-h-64 overflow-y-auto">
              <table className="w-full text-[10px]">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="text-zinc-500 border-b border-border/30">
                    <th className="text-left py-1 px-1.5">Ticker</th>
                    <th className="text-left py-1 px-1.5">Verdict</th>
                    <th className="text-right py-1 px-1.5">Score</th>
                    <th className="text-right py-1 px-1.5">Price</th>
                    <th className="text-right py-1 px-1.5">Bull%</th>
                    <th className="text-right py-1 px-1.5">Conf</th>
                  </tr>
                </thead>
                <tbody>
                  {allVerdicts.map((v: DailyVerdict) => {
                    const act = v.action?.toLowerCase() || '';
                    const isBuy = act.includes('buy');
                    const isSell = act.includes('sell');
                    return (
                      <tr key={v.ticker} className={`border-b border-border/10 ${isBuy ? 'bg-emerald-500/5' : isSell ? 'bg-red-500/5' : ''}`}>
                        <td className="py-1 px-1.5 font-semibold">{v.ticker.replace('.NS', '').replace('.BO', '')}</td>
                        <td className="py-1 px-1.5"><ActionBadge action={v.action} /></td>
                        <td className={`py-1 px-1.5 text-right font-mono ${v.score > 0 ? 'text-emerald-400' : v.score < 0 ? 'text-red-400' : 'text-zinc-400'}`}>
                          {v.score > 0 ? '+' : ''}{v.score.toFixed(2)}
                        </td>
                        <td className="py-1 px-1.5 text-right font-mono">{v.current_price ? formatINR(v.current_price, 2) : '—'}</td>
                        <td className={`py-1 px-1.5 text-right font-mono ${(v.bullish_pct || 0) > 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {v.bullish_pct != null ? `${v.bullish_pct.toFixed(0)}%` : '—'}
                        </td>
                        <td className="py-1 px-1.5 text-right font-mono">{(Number(v.confidence || 0) * 100).toFixed(0)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {allVerdicts.length === 0 && strongBuys.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-4">No verdict data in this daily analysis.</p>
        )}
      </div>
    );
  }

  if (type === 'analysis') {
    const results: Record<string, DetailedResult> = data.results || {};
    if (Object.keys(results).length === 0) return <p className="text-xs text-muted-foreground text-center py-4">No analysis results in this save.</p>;
    return (
      <div className="space-y-4">
        {Object.entries(results).map(([ticker, tickerData]) => (
          <TickerDetail key={ticker} data={tickerData as DetailedResult} defaultCollapsed />
        ))}
      </div>
    );
  }

  if (type === 'discovery') {
    const batch = new Set((data.last_batch || []).map((t: string) => t.replace('.NS', '').replace('.BO', '')));
    const inBatch = (s: DiscoveryStock) => batch.size === 0 || batch.has(s.ticker.replace('.NS', '').replace('.BO', ''));
    const strongBuys = (data.strong_buys || []).filter(inBatch) as DiscoveryStock[];
    const regularBuys = (data.buys || []).filter(inBatch) as DiscoveryStock[];
    const allAnalyzed = (data.all_analyzed || []).filter(inBatch) as DiscoveryStock[];
    const hasBuySignals = strongBuys.length > 0 || regularBuys.length > 0;
    return (
      <div className="space-y-4">
        {strongBuys.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Zap size={12} /> Strong Buys ({strongBuys.length})
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {strongBuys.map(s => (
                <DiscoveryStockCard key={s.ticker} stock={s} />
              ))}
            </div>
          </div>
        )}
        {regularBuys.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <TrendingUp size={12} /> Buys ({regularBuys.length})
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {regularBuys.map(s => (
                <DiscoveryStockCard key={s.ticker} stock={s} />
              ))}
            </div>
          </div>
        )}
        {allAnalyzed.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
              All Analyzed ({allAnalyzed.length})
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {allAnalyzed.map(s => (
                <DiscoveryStockCard key={s.ticker} stock={s} />
              ))}
            </div>
          </div>
        )}
        {!hasBuySignals && allAnalyzed.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-4">No stocks in this discovery save.</p>
        )}
      </div>
    );
  }

  if (type === 'flow') {
    const decisions = data.decisions || data.results || {};
    const tickers = data.tickers || Object.keys(decisions);
    if (tickers.length === 0 && Object.keys(decisions).length === 0) {
      return <p className="text-xs text-muted-foreground text-center py-4">No flow data in this save.</p>;
    }
    if (data.results && typeof data.results === 'object') {
      return (
        <div className="space-y-4">
          {Object.entries(data.results).map(([ticker, tickerData]) => (
            <TickerDetail key={ticker} data={tickerData as DetailedResult} defaultCollapsed />
          ))}
        </div>
      );
    }
    return (
      <div className="space-y-3">
        {Object.entries(decisions).map(([ticker, dec]: [string, any]) => (
          <div key={ticker} className="rounded-lg border border-border/40 bg-muted/20 p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-bold">{ticker.replace('.NS', '')}</span>
              <ActionBadge action={dec.action || dec.signal || 'hold'} />
            </div>
            {dec.confidence != null && (
              <div className="mb-2"><ConfidenceMeter value={dec.confidence} /></div>
            )}
            {dec.reasoning && <p className="text-[10px] text-zinc-500 leading-relaxed">{dec.reasoning}</p>}
            {dec.quantity != null && <span className="text-[10px] text-muted-foreground">Qty: {dec.quantity}</span>}
          </div>
        ))}
      </div>
    );
  }

  return <p className="text-xs text-muted-foreground text-center py-4">Unknown analysis type.</p>;
}

function PennyLibraryCard({ stock: s, rec }: { stock: any; rec: string }) {
  const ticker = (s.ticker || '').replace('.NS', '').replace('.BO', '');
  const price = s.current_price || s.last_close;
  const badgeColor = rec === 'strong_buy'
    ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
    : 'bg-blue-500/20 text-blue-400 border-blue-500/30';
  const badgeText = rec === 'strong_buy' ? 'Strong Buy' : 'Buy';
  return (
    <div className="rounded-lg border border-border/40 bg-muted/20 p-2.5 space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold">{ticker}</span>
          <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border ${badgeColor}`}>{badgeText}</span>
        </div>
        {price > 0 && <span className="text-[11px] font-mono">{formatINR(price, 2)}</span>}
      </div>
      <div className="flex gap-2 text-[10px] flex-wrap">
        {s.ai_score != null && <span className="text-zinc-400">AI Score: <span className="font-mono">{(s.ai_score > 0 ? '+' : '')}{s.ai_score.toFixed(2)}</span></span>}
        {s.ai_confidence != null && <span className="text-zinc-400">Conf: <span className="font-mono">{(s.ai_confidence * 100).toFixed(0)}%</span></span>}
        {s.target_price > 0 && <span><span className="text-zinc-500">T: </span><span className="text-emerald-400 font-mono">{formatINR(s.target_price, 2)}</span></span>}
        {s.stop_loss > 0 && <span><span className="text-zinc-500">SL: </span><span className="text-red-400 font-mono">{formatINR(s.stop_loss, 2)}</span></span>}
      </div>
      {(s.ai_reasoning || s.reasoning) && <p className="text-[9px] text-zinc-500 leading-relaxed">{(s.ai_reasoning || s.reasoning).slice(0, 150)}</p>}
    </div>
  );
}

function DiscoveryStockCard({ stock: s }: { stock: DiscoveryStock }) {
  const [expanded, setExpanded] = useState(false);
  const sb = s.signal_breakdown;
  const agents = s.analyst_signals || {};
  const agentEntries = Object.entries(agents);
  const borderColor = s.action?.toLowerCase().includes('buy')
    ? 'border-emerald-500/20 bg-emerald-500/5'
    : s.action?.toLowerCase().includes('sell')
    ? 'border-red-500/20 bg-red-500/5'
    : 'border-border/40 bg-muted/20';

  return (
    <div className={`rounded-lg border ${borderColor} overflow-hidden`}>
      <button onClick={() => setExpanded(!expanded)} className="w-full text-left p-3 space-y-2 cursor-pointer hover:bg-accent/10 transition-colors">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold">{s.ticker.replace('.NS', '')}</span>
            <ActionBadge action={s.action} />
            {sb && sb.total > 0 && (
              <span className="text-[9px] text-zinc-500 font-mono">
                {sb.bullish}B/{sb.bearish}S/{sb.neutral}N
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {s.current_price != null && <span className="text-xs font-mono">{formatINR(s.current_price, 2)}</span>}
            {s.change_1d_pct != null && (
              <span className={`text-[10px] ${s.change_1d_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {s.change_1d_pct >= 0 ? '+' : ''}{s.change_1d_pct.toFixed(1)}%
              </span>
            )}
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </div>
        </div>
        <div className="flex items-center gap-3 text-[10px] flex-wrap">
          {s.rsi != null && <span className="text-zinc-400">RSI {s.rsi.toFixed(0)}</span>}
          {s.trend && <span className={s.trend === 'Bullish' ? 'text-emerald-400' : s.trend === 'Bearish' ? 'text-red-400' : 'text-zinc-400'}>{s.trend}</span>}
          {s.target_price > 0 && <span><span className="text-zinc-500">Target: </span><span className="text-emerald-400 font-mono">{formatINR(s.target_price, 2)}</span></span>}
          {s.stop_loss > 0 && <span><span className="text-zinc-500">SL: </span><span className="text-red-400 font-mono">{formatINR(s.stop_loss, 2)}</span></span>}
          {s.time_horizon && <TimeHorizonBadge horizon={s.time_horizon} />}
          {s.risk_reward_ratio > 0 && <span className="text-zinc-400">R:R {s.risk_reward_ratio.toFixed(1)}</span>}
          <span className="text-zinc-500 ml-auto font-mono">Score: {s.score > 0 ? '+' : ''}{s.score.toFixed(3)}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-border/20 px-3 py-3 space-y-3 bg-card/50">
          {/* AI Verdict Summary */}
          <div className="space-y-1.5">
            <div className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">AI Verdict</div>
            <div className="flex items-center gap-3 text-[11px]">
              <ActionBadge action={s.action} />
              <span className="font-mono">Score: <span className={s.score > 0 ? 'text-emerald-400' : s.score < 0 ? 'text-red-400' : ''}>{s.score > 0 ? '+' : ''}{s.score.toFixed(3)}</span></span>
              <span className="font-mono">Conf: {(Number(s.confidence || 0) * 100).toFixed(0)}%</span>
            </div>
            {sb && sb.total > 0 && (
              <div className="flex items-center gap-2 text-[10px]">
                <span className="text-emerald-400">{sb.bullish} bullish ({sb.bullish_pct?.toFixed(0)}%)</span>
                <span className="text-red-400">{sb.bearish} bearish ({sb.bearish_pct?.toFixed(0)}%)</span>
                <span className="text-zinc-400">{sb.neutral} neutral</span>
                <span className="text-zinc-500">/ {sb.total} agents</span>
              </div>
            )}
            {s.reasoning && <p className="text-[10px] text-zinc-500 leading-relaxed">{s.reasoning}</p>}
          </div>

          {/* Technical Snapshot */}
          <div className="space-y-1">
            <div className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">Technicals</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[10px]">
              {s.current_price != null && <div className="bg-muted/30 rounded px-2 py-1"><span className="text-zinc-500">Price: </span><span className="font-mono">{formatINR(s.current_price, 2)}</span></div>}
              {s.rsi != null && <div className="bg-muted/30 rounded px-2 py-1"><span className="text-zinc-500">RSI: </span><span className={`font-mono ${s.rsi > 70 ? 'text-red-400' : s.rsi < 30 ? 'text-emerald-400' : ''}`}>{s.rsi.toFixed(1)}</span></div>}
              {s.ema50 != null && <div className="bg-muted/30 rounded px-2 py-1"><span className="text-zinc-500">EMA50: </span><span className="font-mono">{formatINR(s.ema50, 2)}</span></div>}
              {s.ema200 != null && <div className="bg-muted/30 rounded px-2 py-1"><span className="text-zinc-500">EMA200: </span><span className="font-mono">{formatINR(s.ema200, 2)}</span></div>}
              {s.high_52w != null && <div className="bg-muted/30 rounded px-2 py-1"><span className="text-zinc-500">52W H: </span><span className="font-mono">{formatINR(s.high_52w, 2)}</span></div>}
              {s.low_52w != null && <div className="bg-muted/30 rounded px-2 py-1"><span className="text-zinc-500">52W L: </span><span className="font-mono">{formatINR(s.low_52w, 2)}</span></div>}
              {s.target_price > 0 && <div className="bg-muted/30 rounded px-2 py-1"><span className="text-zinc-500">Target: </span><span className="font-mono text-emerald-400">{formatINR(s.target_price, 2)}</span></div>}
              {s.stop_loss > 0 && <div className="bg-muted/30 rounded px-2 py-1"><span className="text-zinc-500">SL: </span><span className="font-mono text-red-400">{formatINR(s.stop_loss, 2)}</span></div>}
            </div>
          </div>

          {/* Agent Signals */}
          {agentEntries.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">Agent Signals ({agentEntries.length})</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                {agentEntries
                  .sort((a, b) => (b[1].confidence || 0) - (a[1].confidence || 0))
                  .map(([name, sig]) => {
                    const sigLower = (sig.signal || '').toLowerCase();
                    const isBull = sigLower === 'bullish' || sigLower === 'buy';
                    const isBear = sigLower === 'bearish' || sigLower === 'sell';
                    const color = isBull ? 'text-emerald-400' : isBear ? 'text-red-400' : 'text-zinc-400';
                    const bg = isBull ? 'bg-emerald-500/5 border-emerald-500/10' : isBear ? 'bg-red-500/5 border-red-500/10' : 'bg-muted/20 border-border/20';
                    const cleanName = name.replace(/_agent$/, '').replace(/_/g, ' ');
                    const conf = typeof sig.confidence === 'number' ? (sig.confidence > 1 ? sig.confidence : sig.confidence * 100) : 0;
                    return (
                      <div key={name} className={`rounded border ${bg} px-2 py-1.5 text-[10px]`}>
                        <div className="flex items-center justify-between">
                          <span className="capitalize font-medium truncate mr-2">{cleanName}</span>
                          <div className="flex items-center gap-1.5 flex-shrink-0">
                            <span className={`font-semibold ${color}`}>{sig.signal}</span>
                            <span className="text-zinc-500 font-mono">{conf.toFixed(0)}%</span>
                          </div>
                        </div>
                        {sig.reasoning && (
                          <p className="text-[9px] text-zinc-600 mt-0.5 leading-relaxed line-clamp-2">{sig.reasoning}</p>
                        )}
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {/* Stock Detail Panel */}
          <StockDetailPanel ticker={s.ticker} onClose={() => setExpanded(false)} />

          {s.discovered_at && (
            <span className="text-[9px] text-zinc-600 block">
              Discovered: {new Date(s.discovered_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export function StockAnalysis() {
  const [tickerInput, setTickerInput] = useState('');
  const [selectedTickers, setSelectedTickers] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<{ symbol: string; exchange: string }[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const [analysts, setAnalysts] = useState<AnalystInfo[]>([]);
  const [selectedAnalysts, setSelectedAnalysts] = useState<string[]>([]);
  const [showAnalystDropdown, setShowAnalystDropdown] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, DetailedResult> | null>(null);
  const [hideResults, setHideResults] = useState(false);

  const { addNotification } = useNotifications();

  // SSE listener for analyst view changes and other events
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/algo-trader/stream`);
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === 'signal_flip') {
            addNotification({
              type: 'review',
              title: `Signal Flip: ${(data.ticker || '').replace('.NS', '')}`,
              message: `${data.from} → ${data.to} (score ${data.score_delta > 0 ? '+' : ''}${data.score_delta?.toFixed(3) || ''})`,
              data,
            });
          } else if (data.type === 'review_changes') {
            const s = data.summary || {};
            if (s.signal_flips > 0 || s.improved > 0 || s.declined > 0) {
              addNotification({
                type: 'review',
                title: 'Analyst Review Updated',
                message: `${s.signal_flips || 0} signal flips, ${s.improved || 0} improved, ${s.declined || 0} declined`,
                data,
              });
            }
          } else if (data.type === 'strong_buy_found') {
            const tk = (data.ticker || '').replace('.NS', '');
            addNotification({
              type: 'trade',
              title: `Strong Buy: ${tk}`,
              message: data.msg || `${tk} identified as strong buy by AI swarm`,
              data,
            });
          } else if (data.type === 'buy_found') {
            const tk = (data.ticker || '').replace('.NS', '');
            addNotification({
              type: 'trade',
              title: `Buy Signal: ${tk}`,
              message: data.msg || `${tk} identified as buy by AI swarm`,
              data,
            });
          } else if (data.type === 'discovery' && data.msg?.includes('complete')) {
            addNotification({ type: 'info', title: 'Discovery Complete', message: data.msg });
          } else if (data.type === 'penny_scan' && data.msg?.includes('complete')) {
            addNotification({ type: 'penny_scan', title: 'Penny Scan Complete', message: data.msg });
          } else if (data.type === 'daily_analysis' && data.msg?.includes('ready')) {
            addNotification({ type: 'daily_analysis', title: 'Daily Analysis Ready', message: data.msg });
          }
        } catch { /* ignore parse errors */ }
      };
    } catch { /* SSE not available */ }
    return () => { if (es) es.close(); };
  }, [addNotification]);

  useEffect(() => {
    fetchAnalysts().then(loaded => {
      setAnalysts(loaded);
      setSelectedAnalysts(loaded.map(a => a.key));
    }).catch(() => {});
  }, []);

  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const handleTickerInput = (val: string) => {
    setTickerInput(val.toUpperCase());
    if (val.length === 0) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const resp = await fetch(`${API_BASE}/stocks/search?q=${encodeURIComponent(val)}&limit=12`);
        if (!resp.ok) return;
        const data = await resp.json();
        const res = (data.results || [])
          .map((r: { symbol: string; exchange: string }) => ({ symbol: r.symbol, exchange: r.exchange || 'NSE' }))
          .filter((r: { symbol: string }) => !selectedTickers.includes(r.symbol));
        setSuggestions(res);
        setShowSuggestions(res.length > 0);
      } catch {
        setShowSuggestions(false);
      }
    }, 250);
  };

  const addTicker = (t: string) => {
    if (!selectedTickers.includes(t)) setSelectedTickers(prev => [...prev, t]);
    setTickerInput('');
    setShowSuggestions(false);
  };

  const removeTicker = (t: string) => setSelectedTickers(prev => prev.filter(x => x !== t));

  const toggleAnalyst = (key: string) => {
    setSelectedAnalysts(prev => prev.includes(key) ? prev.filter(x => x !== key) : [...prev, key]);
  };

  const handleAnalyze = useCallback(async () => {
    if (selectedTickers.length === 0) return;
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const body: any = { tickers: selectedTickers };
      if (selectedAnalysts.length > 0) body.analysts = selectedAnalysts;
      const resp = await fetch(`${API_BASE}/hedge-fund/analyze-detailed`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error(`Analysis failed (${resp.status})`);
      const data = await resp.json();
      setResults(data.results);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, [selectedTickers, selectedAnalysts]);

  return (
    <div className="h-full overflow-y-auto bg-background">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Stock Analysis</h1>
          <p className="text-muted-foreground text-sm mt-1">
            AI-powered detailed analysis using Claude Opus 4.6 — technical, fundamental, and multi-analyst perspectives
          </p>
        </div>

        <div className="rounded-xl border bg-card p-5 space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Search Indian Stocks (NSE + BSE)</label>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                value={tickerInput}
                onChange={e => handleTickerInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && suggestions.length > 0) addTicker(suggestions[0].symbol);
                }}
                placeholder="Search NSE & BSE stocks (870+ available)..."
                className="w-full pl-9 pr-4 py-2.5 text-sm rounded-lg border bg-background focus:outline-none focus:ring-2 focus:ring-primary/30 transition-shadow"
              />
              {showSuggestions && suggestions.length > 0 && (
                <div className="absolute z-50 mt-1 w-full rounded-xl border bg-popover shadow-xl max-h-48 overflow-y-auto">
                  {suggestions.map(s => (
                    <button
                      key={s.symbol}
                      onClick={() => addTicker(s.symbol)}
                      className="w-full text-left px-4 py-2 text-sm hover:bg-accent transition-colors cursor-pointer flex items-center justify-between"
                    >
                      <span>
                        <span className="font-medium">{s.symbol.replace('.NS', '').replace('.BO', '')}</span>
                        <span className="text-muted-foreground ml-1 text-xs">{s.symbol.endsWith('.BO') ? '.BO' : '.NS'}</span>
                      </span>
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${s.exchange === 'BSE' ? 'bg-amber-500/15 text-amber-400' : 'bg-blue-500/15 text-blue-400'}`}>
                        {s.exchange}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selectedTickers.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {selectedTickers.map(t => (
                  <span key={t} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-full bg-primary/10 text-primary border border-primary/20">
                    {t.replace('.NS', '')}
                    <button onClick={() => removeTicker(t)} className="hover:text-destructive transition-colors cursor-pointer"><X size={11} /></button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Analysts (optional)</label>
            <div className="relative">
              <button
                onClick={() => setShowAnalystDropdown(!showAnalystDropdown)}
                className="w-full flex items-center justify-between px-3 py-2.5 text-sm rounded-lg border bg-background hover:bg-accent/30 transition-colors cursor-pointer"
              >
                <span className="text-muted-foreground">
                  {selectedAnalysts.length === analysts.length ? `All ${analysts.length} analysts selected` : selectedAnalysts.length === 0 ? 'None selected' : `${selectedAnalysts.length} of ${analysts.length} selected`}
                </span>
                <ChevronDown size={14} />
              </button>
              {showAnalystDropdown && (
                <div className="absolute z-50 mt-1 w-full rounded-xl border bg-popover shadow-xl max-h-56 overflow-y-auto">
                  {analysts.map(a => (
                    <button
                      key={a.key}
                      onClick={() => toggleAnalyst(a.key)}
                      className="w-full flex items-center gap-3 px-4 py-2 text-sm hover:bg-accent text-left cursor-pointer"
                    >
                      <span className={`w-3.5 h-3.5 rounded border flex items-center justify-center text-[9px] ${
                        selectedAnalysts.includes(a.key) ? 'bg-primary border-primary text-primary-foreground' : 'border-muted-foreground'
                      }`}>
                        {selectedAnalysts.includes(a.key) && '✓'}
                      </span>
                      <div>
                        <div className="font-medium">{a.display_name}</div>
                        <div className="text-[10px] text-muted-foreground">{a.description}</div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <button
            onClick={handleAnalyze}
            disabled={loading || selectedTickers.length === 0}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors cursor-pointer"
          >
            {loading ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Analyzing with Claude Opus 4.6...</>
            ) : (
              <><Sparkles className="w-4 h-4" /> Analyze {selectedTickers.length} Stock{selectedTickers.length !== 1 ? 's' : ''}</>
            )}
          </button>
        </div>

        {/* ── Live Sections ── */}
        <PennyScanSection />
        <DiscoverySection />
        <DailyAnalysisSection />

        {/* ── Saved Analysis Library ── */}
        <AnalysisLibrary />

        {error && (
          <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>
        )}

        {results && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Detailed Analysis Results</h2>
              <button
                onClick={() => setHideResults(!hideResults)}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer px-2.5 py-1.5 rounded-lg hover:bg-accent/30"
              >
                {hideResults ? <Eye size={13} /> : <EyeOff size={13} />}
                {hideResults ? 'Show Details' : 'Hide Details'}
              </button>
            </div>
            {!hideResults && Object.entries(results).map(([ticker, data]) => (
              <TickerDetail key={ticker} data={data} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
