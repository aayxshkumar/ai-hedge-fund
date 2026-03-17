import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { formatINR, formatINRCompact } from '@/lib/format-inr';
import {
  Activity,
  ArrowDown,
  ArrowUp,
  BarChart3,
  Bot,
  Briefcase,
  ChevronDown,
  ChevronRight,
  Clock,
  IndianRupee,
  Loader2,
  Minus,
  RefreshCw,
  Shield,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
  Wallet,
  WifiOff,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useNotifications } from '@/contexts/notifications-context';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// ── Types ────────────────────────────────────────────────

interface StockAnalysis {
  rsi: number | null;
  macd: number;
  macd_signal: number;
  ema50: number;
  ema200: number;
  bb_upper: number;
  bb_lower: number;
  trend: string;
  volatility: number;
  max_drawdown: number;
  high_52w: number;
  low_52w: number;
}

interface SignalBreakdown {
  bullish: number;
  bearish: number;
  neutral: number;
  total: number;
  bullish_pct: number;
  bearish_pct: number;
}

interface AnalystVerdict {
  action: string;
  confidence: number;
  reasoning: string;
  score?: number;
  signal_breakdown?: SignalBreakdown;
  analyst_signals?: Record<string, any>;
}

interface PortfolioStock {
  ticker: string;
  yf_ticker: string;
  type: 'holding' | 'position';
  product?: string;
  quantity: number;
  avg_price: number;
  last_price: number;
  invested_value: number;
  current_value: number;
  pnl: number;
  pnl_pct: number;
  analysis: StockAnalysis | null;
  mini_chart?: { d: string; c: number }[];
  signal: string;
  signal_color: string;
}

interface PortfolioSummary {
  cash: number;
  used_margin: number;
  total_invested: number;
  total_current: number;
  total_pnl: number;
  total_pnl_pct: number;
  portfolio_value: number;
  num_holdings: number;
  num_positions: number;
}

interface PortfolioData {
  stocks: PortfolioStock[];
  summary: PortfolioSummary;
  broker_connected: boolean;
}

interface ReviewChanges {
  signal_flips: { ticker: string; from: string; to: string; score_delta: number }[];
  score_changes: { ticker: string; delta: number; direction: string }[];
  biggest_movers: { ticker: string; delta: number; direction: string; cur_score: number }[];
  new_tickers: string[];
  removed_tickers: string[];
  summary: {
    total_compared: number;
    signal_flips: number;
    improved: number;
    declined: number;
    new_count: number;
    removed_count: number;
  };
  current_timestamp: string;
  previous_timestamp: string;
}

interface AnalystReviewData {
  review: {
    timestamp: string;
    tickers: string[];
    verdicts: Record<string, AnalystVerdict>;
    model_used: string;
    stocks_reviewed: number;
    changes?: ReviewChanges;
  } | null;
  timestamp: string | null;
  running: boolean;
}

// ── Shared components ────────────────────────────────────

function VerdictBadge({ action }: { action: string }) {
  const n = (action || 'hold').toLowerCase();
  const isBuy = n.includes('buy') || n.includes('bull') || n.includes('long');
  const isSell = n.includes('sell') || n.includes('bear') || n.includes('short');
  const strong = n.includes('strong');
  const cls = isBuy
    ? strong ? 'bg-emerald-500/20 text-emerald-300 border-emerald-400/30' : 'bg-green-500/15 text-green-400 border-green-500/30'
    : isSell
    ? strong ? 'bg-red-500/20 text-red-300 border-red-400/30' : 'bg-red-500/15 text-red-400 border-red-500/30'
    : 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30';
  const Icon = isBuy ? TrendingUp : isSell ? TrendingDown : Shield;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold rounded-full border ${cls}`}>
      <Icon className="w-3 h-3" /> {action.toUpperCase()}
    </span>
  );
}

function ConfidenceBar({ value, wide }: { value: number; wide?: boolean }) {
  const pct = Math.min(100, Math.max(0, (value > 1 ? value : value * 100)));
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className={`flex-1 ${wide ? 'h-2.5' : 'h-1.5'} bg-zinc-800 rounded-full overflow-hidden`}>
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`${wide ? 'text-xs' : 'text-[10px]'} font-mono text-zinc-400 w-8 text-right`}>{pct.toFixed(0)}%</span>
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
        <span>{label}</span><span className="font-mono">{value.toFixed(1)}{unit}</span>
      </div>
      <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function MiniSparkline({ data, positive }: { data: { d: string; c: number }[]; positive: boolean }) {
  if (!data || data.length < 2) return null;
  return (
    <ResponsiveContainer width="100%" height={40}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={positive ? 'sparkGreen' : 'sparkRed'} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={positive ? '#10b981' : '#ef4444'} stopOpacity={0.3} />
            <stop offset="100%" stopColor={positive ? '#10b981' : '#ef4444'} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="c" stroke={positive ? '#10b981' : '#ef4444'} fill={`url(#${positive ? 'sparkGreen' : 'sparkRed'})`} strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function SummaryCard({ icon: Icon, label, value, sub, color }: {
  icon: React.ElementType; label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <Card className="bg-panel border-border/50">
      <CardContent className="p-3 flex items-start gap-3">
        <div className={`p-2 rounded-lg ${color || 'bg-blue-500/10'}`}>
          <Icon className={`h-4 w-4 ${color ? color.replace('bg-', 'text-').replace('/10', '') : 'text-blue-500'}`} />
        </div>
        <div>
          <div className="text-[10px] text-muted-foreground">{label}</div>
          <div className="text-sm font-semibold text-primary">{value}</div>
          {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Review progress bar ──────────────────────────────────

function ReviewProgressBar({ running, elapsed }: { running: boolean; elapsed: number }) {
  if (!running) return null;
  const stages = ['Fetching holdings', 'Building AI graph', 'Running 19 analysts', 'Parsing verdicts'];
  const stageIdx = Math.min(3, Math.floor(elapsed / 15));
  const pct = Math.min(95, (elapsed / 90) * 100);

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />
        <span className="text-sm font-medium text-amber-300">AI Analyst Review in Progress</span>
        <span className="text-xs text-zinc-500 ml-auto">{elapsed}s elapsed</span>
      </div>
      <div className="w-full h-2 bg-zinc-800 rounded-full overflow-hidden">
        <div className="h-full bg-gradient-to-r from-amber-500 to-emerald-500 rounded-full transition-all duration-1000 ease-linear" style={{ width: `${pct}%` }} />
      </div>
      <div className="flex items-center gap-4">
        {stages.map((s, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${i < stageIdx ? 'bg-emerald-500' : i === stageIdx ? 'bg-amber-400 animate-pulse' : 'bg-zinc-700'}`} />
            <span className={`text-[10px] ${i <= stageIdx ? 'text-zinc-300' : 'text-zinc-600'}`}>{s}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Detail tabs (analysis-tab level) ─────────────────────

type DetailTab = 'overview' | 'technical' | 'analysts' | 'risk';
const DETAIL_TABS: { key: DetailTab; label: string; icon: any }[] = [
  { key: 'overview', label: 'Overview', icon: Target },
  { key: 'technical', label: 'Technical', icon: Activity },
  { key: 'analysts', label: 'Analysts', icon: Users },
  { key: 'risk', label: 'Risk', icon: Shield },
];

function StockRow({ stock, verdict, expanded, onToggle }: {
  stock: PortfolioStock; verdict: AnalystVerdict | null; expanded: boolean; onToggle: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>('overview');
  const pnlPositive = stock.pnl >= 0;
  const a = stock.analysis;
  const signals = verdict?.analyst_signals || {};
  const signalEntries = Object.entries(signals).filter(([, v]) => v != null && typeof v === 'object');

  const effectiveSignal = verdict ? verdict.action : stock.signal;
  const effectiveColor = verdict
    ? (effectiveSignal.toLowerCase().includes('buy') ? 'emerald'
      : effectiveSignal.toLowerCase().includes('sell') ? 'red' : 'gray')
    : stock.signal_color;

  const fmtPct = (v: number | null | undefined) => v != null ? `${(v * 100).toFixed(2)}%` : '—';

  return (
    <div className="border border-border/50 rounded-lg overflow-hidden">
      {/* Row header */}
      <button onClick={onToggle} className="w-full flex items-center gap-3 px-4 py-3 hover:bg-muted/30 transition-colors text-left cursor-pointer">
        <div className="shrink-0">
          {expanded ? <ChevronDown className="w-4 h-4 text-muted-foreground" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-primary">{stock.ticker}</span>
            <Badge variant="outline" className="text-[9px] px-1.5 py-0">{stock.type === 'holding' ? 'CNC' : stock.product || 'MIS'}</Badge>
            {verdict ? <VerdictBadge action={effectiveSignal} /> : (
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold rounded-full border ${
                effectiveColor === 'emerald' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                effectiveColor === 'green' ? 'bg-green-500/10 text-green-400 border-green-500/20' :
                effectiveColor === 'red' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                effectiveColor === 'orange' ? 'bg-orange-500/10 text-orange-400 border-orange-500/20' :
                'bg-gray-500/10 text-gray-400 border-gray-500/20'
              }`}>
                {effectiveColor === 'emerald' || effectiveColor === 'green' ? <TrendingUp className="w-3 h-3" /> :
                 effectiveColor === 'red' || effectiveColor === 'orange' ? <TrendingDown className="w-3 h-3" /> : null}
                {effectiveSignal}
              </span>
            )}
          </div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {stock.quantity} shares @ {formatINR(stock.avg_price, 2)} avg
            {verdict && verdict.confidence > 0 && <span className="ml-2 text-zinc-500">AI conf: {(verdict.confidence * 100).toFixed(0)}%</span>}
            {verdict?.signal_breakdown && (
              <span className="ml-1 text-zinc-600 text-[9px]">
                ({verdict.signal_breakdown.bullish}B/{verdict.signal_breakdown.bearish}S/{verdict.signal_breakdown.neutral}N)
              </span>
            )}
          </div>
        </div>
        <div className="w-24 hidden md:block"><MiniSparkline data={stock.mini_chart || []} positive={pnlPositive} /></div>
        <div className="text-right min-w-[90px]">
          <div className="text-sm font-medium text-primary">{formatINR(stock.last_price, 2)}</div>
          <div className="text-[10px] text-muted-foreground">{formatINR(stock.current_value)}</div>
        </div>
        <div className="text-right min-w-[80px]">
          <div className={`text-sm font-semibold flex items-center justify-end gap-1 ${pnlPositive ? 'text-emerald-500' : 'text-red-500'}`}>
            {pnlPositive ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}{formatINR(Math.abs(stock.pnl), 2)}
          </div>
          <div className={`text-[10px] ${pnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>{pnlPositive ? '+' : ''}{stock.pnl_pct.toFixed(2)}%</div>
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-border/30 bg-muted/10">
          {/* AI Verdict banner */}
          {verdict && (
            <div className="px-4 pt-4 pb-2">
              <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-4 space-y-3">
                <div className="flex items-center gap-2 text-xs font-medium text-blue-400"><Bot className="w-3.5 h-3.5" /> Meta Analyst — Final Verdict</div>
                <div className="flex items-center gap-3">
                  <VerdictBadge action={verdict.action} />
                  <div className="flex-1"><ConfidenceBar value={verdict.confidence} wide /></div>
                  {typeof verdict.score === 'number' && (
                    <span className={`text-xs font-mono ${verdict.score > 0 ? 'text-emerald-400' : verdict.score < 0 ? 'text-red-400' : 'text-zinc-400'}`}>
                      score: {verdict.score > 0 ? '+' : ''}{verdict.score.toFixed(3)}
                    </span>
                  )}
                </div>

                {/* Signal breakdown bar */}
                {verdict.signal_breakdown && verdict.signal_breakdown.total > 0 && (
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 text-[10px] text-zinc-500">
                      <span className="text-emerald-400">{verdict.signal_breakdown.bullish} Bullish ({verdict.signal_breakdown.bullish_pct}%)</span>
                      <span className="text-zinc-500">{verdict.signal_breakdown.neutral} Neutral</span>
                      <span className="text-red-400">{verdict.signal_breakdown.bearish} Bearish ({verdict.signal_breakdown.bearish_pct}%)</span>
                      <span className="text-zinc-600 ml-auto">{verdict.signal_breakdown.total} analysts</span>
                    </div>
                    <div className="flex h-2 rounded-full overflow-hidden bg-zinc-800">
                      {verdict.signal_breakdown.bullish_pct > 0 && (
                        <div className="bg-emerald-500 transition-all" style={{ width: `${verdict.signal_breakdown.bullish_pct}%` }} />
                      )}
                      {(100 - verdict.signal_breakdown.bullish_pct - verdict.signal_breakdown.bearish_pct) > 0 && (
                        <div className="bg-zinc-600 transition-all" style={{ width: `${100 - verdict.signal_breakdown.bullish_pct - verdict.signal_breakdown.bearish_pct}%` }} />
                      )}
                      {verdict.signal_breakdown.bearish_pct > 0 && (
                        <div className="bg-red-500 transition-all" style={{ width: `${verdict.signal_breakdown.bearish_pct}%` }} />
                      )}
                    </div>
                  </div>
                )}

                {/* Target Analyst: price target, stop loss, time horizon */}
                {(() => {
                  const tgt = verdict.analyst_signals?.target_analyst_agent;
                  if (!tgt || !tgt.target_price) return null;
                  const horizonLabels: Record<string, { label: string; cls: string }> = {
                    intraday:   { label: 'Intraday',  cls: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/20' },
                    swing_1w:   { label: '1W Swing',  cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20' },
                    short_1m:   { label: '1M Short',  cls: 'bg-blue-500/15 text-blue-400 border-blue-500/20' },
                    medium_3m:  { label: '3M Medium', cls: 'bg-purple-500/15 text-purple-400 border-purple-500/20' },
                    'long_6m+': { label: '6M+ Long',  cls: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/20' },
                  };
                  const h = horizonLabels[tgt.time_horizon] || { label: tgt.time_horizon, cls: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/20' };
                  return (
                    <div className="flex items-center gap-4 flex-wrap text-xs mt-1">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold border ${h.cls}`}>
                        <Clock className="w-2.5 h-2.5" /> {h.label}
                      </span>
                      <span><span className="text-zinc-500">Target: </span><span className="font-mono text-emerald-400">{formatINR(tgt.target_price, 2)}</span></span>
                      <span><span className="text-zinc-500">Stop: </span><span className="font-mono text-red-400">{formatINR(tgt.stop_loss, 2)}</span></span>
                      {tgt.risk_reward_ratio > 0 && (
                        <span><span className="text-zinc-500">R:R </span><span className="font-mono">{tgt.risk_reward_ratio.toFixed(2)}</span></span>
                      )}
                    </div>
                  );
                })()}

                {verdict.reasoning && <p className="text-xs text-zinc-400 leading-relaxed">{verdict.reasoning}</p>}
              </div>
            </div>
          )}

          {/* Detail tabs */}
          <div className="flex border-b border-border/30 px-4">
            {DETAIL_TABS.map(t => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`flex items-center gap-1.5 px-3 py-2 text-[11px] font-medium transition-colors cursor-pointer ${
                  tab === t.key ? 'border-b-2 border-primary text-foreground' : 'text-muted-foreground hover:text-foreground'
                }`}>
                <t.icon size={11} /> {t.label}
              </button>
            ))}
          </div>

          <div className="px-4 py-4">
            {/* ── Overview ── */}
            {tab === 'overview' && (
              <div className="space-y-4">
                {stock.mini_chart && stock.mini_chart.length > 5 && (
                  <div>
                    <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Price (30 Days)</h4>
                    <div className="h-44">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={stock.mini_chart} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                          <defs>
                            <linearGradient id={`grad-port-${stock.ticker}`} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor={pnlPositive ? '#10b981' : '#ef4444'} stopOpacity={0.2} />
                              <stop offset="100%" stopColor={pnlPositive ? '#10b981' : '#ef4444'} stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <XAxis dataKey="d" tick={{ fontSize: 9, fill: '#666' }} tickLine={false} axisLine={false} />
                          <YAxis domain={['dataMin', 'dataMax']} tick={{ fontSize: 9, fill: '#666' }} tickFormatter={v => `₹${v}`} />
                          <RTooltip contentStyle={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 6, fontSize: 11 }} formatter={(v: any) => [formatINR(Number(v), 2), 'Price']} />
                          {a && <ReferenceLine y={a.ema50} stroke="#3b82f6" strokeDasharray="3 3" label={{ value: 'EMA50', fontSize: 8, fill: '#3b82f6' }} />}
                          <Area type="monotone" dataKey="c" stroke={pnlPositive ? '#10b981' : '#ef4444'} fill={`url(#grad-port-${stock.ticker})`} strokeWidth={1.5} dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <MetricCard label="Current Price" value={formatINR(stock.last_price, 2)} />
                  <MetricCard label="Avg Cost" value={formatINR(stock.avg_price, 2)} />
                  <MetricCard label="52W High" value={a ? formatINR(a.high_52w, 2) : undefined} />
                  <MetricCard label="52W Low" value={a ? formatINR(a.low_52w, 2) : undefined} />
                  <MetricCard label="Invested" value={formatINR(stock.invested_value)} />
                  <MetricCard label="Current Value" value={formatINR(stock.current_value)} />
                  <MetricCard label="P&L" value={`${stock.pnl >= 0 ? '+' : ''}${formatINR(stock.pnl, 2)}`} sub={`${stock.pnl_pct >= 0 ? '+' : ''}${stock.pnl_pct.toFixed(2)}%`} />
                  <MetricCard label="52W Range" value={a ? `${((stock.last_price - a.low_52w) / Math.max(1, a.high_52w - a.low_52w) * 100).toFixed(0)}%` : undefined} />
                </div>
              </div>
            )}

            {/* ── Technical ── */}
            {tab === 'technical' && a && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  <MetricCard label="Trend" value={a.trend} />
                  <MetricCard label="RSI (14)" value={a.rsi?.toFixed(1)} sub={a.rsi && a.rsi > 70 ? 'Overbought' : a.rsi && a.rsi < 30 ? 'Oversold' : 'Neutral'} />
                  <MetricCard label="MACD" value={a.macd.toFixed(3)} sub={`Signal: ${a.macd_signal.toFixed(3)}`} />
                  <MetricCard label="EMA 50" value={formatINR(a.ema50, 2)} />
                  <MetricCard label="EMA 200" value={formatINR(a.ema200, 2)} />
                  <MetricCard label="EMA Cross" value={a.ema50 > a.ema200 ? 'Golden Cross' : 'Death Cross'} />
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  <MetricCard label="Bollinger Upper" value={formatINR(a.bb_upper, 2)} />
                  <MetricCard label="Bollinger Lower" value={formatINR(a.bb_lower, 2)} />
                  <MetricCard label="BB Width" value={`${((a.bb_upper - a.bb_lower) / stock.last_price * 100).toFixed(1)}%`} />
                </div>
                <div className="space-y-2.5">
                  <GaugeBar value={a.rsi} min={0} max={100} label="RSI" />
                  <GaugeBar value={a.volatility} min={0} max={80} label="Volatility" unit="%" />
                </div>
              </div>
            )}
            {tab === 'technical' && !a && (
              <p className="text-sm text-muted-foreground py-6 text-center">No technical data available for this stock.</p>
            )}

            {/* ── Analysts ── */}
            {tab === 'analysts' && (() => {
              if (signalEntries.length === 0) {
                return (
                  <div className="flex flex-col items-center justify-center py-8 gap-2">
                    <Users size={20} className="text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">No analyst signals available.</p>
                    <p className="text-[10px] text-muted-foreground/60">Click "Run AI Review" to get 21-agent analysis (including Options Flow + Swarm Intelligence) on your portfolio.</p>
                  </div>
                );
              }
              return (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground mb-2">{signalEntries.length} analyst{signalEntries.length !== 1 ? 's' : ''} reported</p>
                  {signalEntries.map(([analyst, signal]: [string, any]) => {
                    const sigStr = typeof signal?.signal === 'string' ? signal.signal : typeof signal === 'string' ? signal : '';
                    const sigUpper = sigStr.toUpperCase();
                    const conf = typeof signal?.confidence === 'number' ? signal.confidence : null;
                    const reasoning = typeof signal?.reasoning === 'string' ? signal.reasoning : '';
                    return (
                      <div key={analyst} className="p-3 rounded-lg border bg-muted/20">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-xs font-medium capitalize">{analyst.replace(/_agent$/,'').replace(/_/g, ' ')}</span>
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                              sigUpper.includes('BUY') || sigUpper.includes('BULLISH') ? 'bg-emerald-500/15 text-emerald-400' :
                              sigUpper.includes('SELL') || sigUpper.includes('BEARISH') ? 'bg-red-500/15 text-red-400' :
                              'bg-amber-500/15 text-amber-400'
                            }`}>{sigStr || 'N/A'}</span>
                            {conf != null && <span className="text-[10px] font-mono text-muted-foreground">{Math.round(conf > 1 ? conf : conf * 100)}%</span>}
                          </div>
                        </div>
                        {reasoning && <p className="text-[11px] text-muted-foreground leading-relaxed">{reasoning}</p>}
                      </div>
                    );
                  })}
                </div>
              );
            })()}

            {/* ── Risk ── */}
            {tab === 'risk' && a && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  <MetricCard label="Annualized Volatility" value={`${a.volatility.toFixed(1)}%`} />
                  <MetricCard label="Max Drawdown" value={`${a.max_drawdown.toFixed(1)}%`} />
                  <MetricCard label="Position Size" value={formatINR(stock.current_value)} sub={`${stock.quantity} shares`} />
                </div>
                <div className="space-y-2.5">
                  <GaugeBar value={a.volatility} min={0} max={80} label="Volatility" unit="%" />
                  <GaugeBar value={Math.abs(a.max_drawdown)} min={0} max={50} label="Max Drawdown" unit="%" />
                </div>
                {a.bb_upper && a.bb_lower && (
                  <div className="p-3 rounded-lg border bg-muted/20">
                    <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Position Risk</h4>
                    <div className="grid grid-cols-3 gap-2 text-center">
                      <div>
                        <div className="text-[10px] text-muted-foreground">Upside to BB Upper</div>
                        <div className="text-sm font-mono font-semibold text-emerald-400">
                          {((a.bb_upper - stock.last_price) / stock.last_price * 100).toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted-foreground">Downside to BB Lower</div>
                        <div className="text-sm font-mono font-semibold text-red-400">
                          {((a.bb_lower - stock.last_price) / stock.last_price * 100).toFixed(1)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted-foreground">Return from Avg</div>
                        <div className={`text-sm font-mono font-semibold ${stock.pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {stock.pnl_pct >= 0 ? '+' : ''}{stock.pnl_pct.toFixed(2)}%
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
            {tab === 'risk' && !a && (
              <p className="text-sm text-muted-foreground py-6 text-center">No risk data available for this stock.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Sort options ─────────────────────────────────────────

type SortKey = 'value' | 'pnl' | 'pnl_pct' | 'name' | 'quantity' | 'last_price' | 'avg_price' | 'invested' | 'rsi' | 'volatility' | 'signal' | 'type' | 'day_pnl';

const SIGNAL_ORDER: Record<string, number> = {
  'strong buy': 1, 'buy': 2, 'hold': 3, 'sell': 4, 'strong sell': 5, 'n/a': 6,
};

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'value', label: 'Value' },
  { key: 'pnl', label: 'P&L' },
  { key: 'pnl_pct', label: 'P&L %' },
  { key: 'name', label: 'Name' },
  { key: 'quantity', label: 'Qty' },
  { key: 'last_price', label: 'Price' },
  { key: 'avg_price', label: 'Avg Cost' },
  { key: 'invested', label: 'Invested' },
  { key: 'rsi', label: 'RSI' },
  { key: 'volatility', label: 'Volatility' },
  { key: 'signal', label: 'Signal' },
  { key: 'type', label: 'Type' },
];

function getSortValue(stock: PortfolioStock, key: SortKey): number | string {
  switch (key) {
    case 'value': return stock.current_value;
    case 'pnl': return stock.pnl;
    case 'pnl_pct': return stock.pnl_pct;
    case 'name': return stock.ticker;
    case 'quantity': return stock.quantity;
    case 'last_price': return stock.last_price;
    case 'avg_price': return stock.avg_price;
    case 'invested': return stock.invested_value;
    case 'rsi': return stock.analysis?.rsi ?? -999;
    case 'volatility': return stock.analysis?.volatility ?? -999;
    case 'signal': return SIGNAL_ORDER[(stock.signal || 'n/a').toLowerCase()] ?? 6;
    case 'type': return stock.type === 'holding' ? 0 : 1;
    case 'day_pnl': return (stock as any).day_pnl ?? 0;
    default: return 0;
  }
}

// ── Main Portfolio component ─────────────────────────────

export function Portfolio() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [review, setReview] = useState<AnalystReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [reviewRunning, setReviewRunning] = useState(false);
  const [reviewElapsed, setReviewElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortKey>('value');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { addNotification } = useNotifications();

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [portfolioResp, reviewResp] = await Promise.all([
        fetch(`${API_BASE}/algo-trader/portfolio/detailed`),
        fetch(`${API_BASE}/algo-trader/portfolio/analyst-review`),
      ]);
      if (!portfolioResp.ok) throw new Error(`${portfolioResp.status} ${portfolioResp.statusText}`);
      setData(await portfolioResp.json());
      if (reviewResp.ok) {
        const r: AnalystReviewData = await reviewResp.json();
        setReview(r);
        if (r.running) startPolling();
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
      setLastRefreshed(new Date());
    }
  }, []);

  useEffect(() => {
    refresh();
    autoRefreshRef.current = setInterval(refresh, 60_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
    };
  }, [refresh]);

  const startPolling = () => {
    setReviewRunning(true);
    setReviewElapsed(0);

    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(async () => {
      setReviewElapsed(prev => prev + 5);
      try {
        const resp = await fetch(`${API_BASE}/algo-trader/portfolio/analyst-review`);
        if (resp.ok) {
          const r: AnalystReviewData = await resp.json();
          setReview(r);
          if (!r.running) {
            setReviewRunning(false);
            if (timerRef.current) clearInterval(timerRef.current);

            if (r.review?.verdicts) {
              const v = r.review.verdicts;
              const buys = Object.values(v).filter(x => (x.action || '').toLowerCase().includes('buy')).length;
              const sells = Object.values(v).filter(x => (x.action || '').toLowerCase().includes('sell')).length;
              const holds = Object.keys(v).length - buys - sells;
              const changes = r.review.changes;
              let changeMsg = '';
              if (changes?.summary) {
                const cs = changes.summary;
                if (cs.signal_flips > 0) changeMsg += ` | ${cs.signal_flips} signal flip${cs.signal_flips !== 1 ? 's' : ''}`;
                if (cs.improved > 0) changeMsg += ` | ${cs.improved} improved`;
              }
              addNotification({
                type: 'review',
                title: 'AI Review Complete',
                message: `${Object.keys(v).length} stocks: ${buys} Buy, ${holds} Hold, ${sells} Sell${changeMsg}`,
                data: { buys, holds, sells },
              });
            }
          }
        }
      } catch {}
    }, 5000);
  };

  const triggerReview = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/algo-trader/portfolio/analyst-review`, { method: 'POST' });
      startPolling();
    } catch { toast.error('Failed to start AI review'); }
  }, []);

  const startScheduler = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/algo-trader/portfolio/review-scheduler/start`, { method: 'POST' });
    } catch { toast.error('Failed to start review scheduler'); }
  }, []);

  const verdicts = review?.review?.verdicts || {};
  const reviewTime = review?.review?.timestamp;

  const getVerdict = (stock: PortfolioStock): AnalystVerdict | null => {
    return verdicts[stock.yf_ticker] || verdicts[stock.ticker] || verdicts[`${stock.ticker}.NS`] || null;
  };

  const sortedStocks = data?.stocks.slice().sort((a, b) => {
    const va = getSortValue(a, sortBy);
    const vb = getSortValue(b, sortBy);
    let cmp: number;
    if (typeof va === 'string' && typeof vb === 'string') {
      cmp = va.localeCompare(vb);
    } else {
      cmp = (vb as number) - (va as number);
    }
    return sortDir === 'asc' ? -cmp : cmp;
  }) ?? [];

  const gainers = sortedStocks.filter(s => s.pnl > 0).length;
  const losers = sortedStocks.filter(s => s.pnl < 0).length;
  const buyCount = Object.values(verdicts).filter(v => (v.action || '').toLowerCase().includes('buy')).length;
  const sellCount = Object.values(verdicts).filter(v => (v.action || '').toLowerCase().includes('sell')).length;
  const holdCount = Object.values(verdicts).length - buyCount - sellCount;

  if (loading && !data) {
    return (
      <div className="h-full overflow-y-auto p-4 sm:p-6 space-y-4">
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-xl border bg-card p-4 space-y-3 animate-pulse">
              <div className="h-3 w-20 bg-muted rounded" />
              <div className="h-6 w-28 bg-muted rounded" />
              <div className="h-3 w-16 bg-muted rounded" />
            </div>
          ))}
        </div>
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="rounded-lg border bg-card p-3 flex items-center gap-4 animate-pulse">
              <div className="h-4 w-24 bg-muted rounded" />
              <div className="h-4 w-16 bg-muted rounded" />
              <div className="flex-1" />
              <div className="h-4 w-20 bg-muted rounded" />
              <div className="h-4 w-16 bg-muted rounded" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-bold text-primary flex items-center gap-2"><Briefcase className="w-5 h-5" /> My Portfolio</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {data?.broker_connected ? `Live Zerodha data — ${sortedStocks.length} stocks` : 'Broker not connected — connect in Settings'}
            {lastRefreshed && <span className="ml-2 opacity-60">Updated {lastRefreshed.toLocaleTimeString()}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={triggerReview} disabled={reviewRunning} className="gap-1.5 text-xs">
            {reviewRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Bot className="h-3 w-3" />}
            {reviewRunning ? 'Analyzing...' : 'Run AI Review'}
          </Button>
          <Button variant="outline" size="sm" onClick={startScheduler} className="gap-1.5 text-xs" title="Start daily 12PM auto-review">
            <Clock className="h-3 w-3" /> Schedule 12PM
          </Button>
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading} className="gap-1.5 text-xs">
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-400 flex items-center gap-2"><WifiOff className="w-4 h-4" /> {error}</div>
      )}

      {/* Progress bar during review */}
      <ReviewProgressBar running={reviewRunning} elapsed={reviewElapsed} />

      {/* Review completed banner */}
      {!reviewRunning && reviewTime && Object.keys(verdicts).length > 0 && (() => {
        const changes = review?.review?.changes;
        return (
          <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3 space-y-2">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <Bot className="w-4 h-4 text-blue-400" />
                <span className="text-xs font-medium text-zinc-200">AI Analyst Review Complete</span>
                <span className="text-[10px] text-zinc-500">
                  {new Date(reviewTime).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
              <div className="flex items-center gap-3 text-[10px]">
                <span className="text-emerald-400 font-medium"><TrendingUp className="w-3 h-3 inline mr-0.5" />{buyCount} Buy</span>
                <span className="text-zinc-400 font-medium"><Minus className="w-3 h-3 inline mr-0.5" />{holdCount} Hold</span>
                <span className="text-red-400 font-medium"><TrendingDown className="w-3 h-3 inline mr-0.5" />{sellCount} Sell</span>
              </div>
            </div>

            {changes && changes.summary && (changes.summary.signal_flips > 0 || changes.summary.improved > 0 || changes.summary.declined > 0) && (
              <div className="space-y-1.5 pt-1 border-t border-blue-500/20">
                <div className="flex items-center gap-3 text-[10px] text-zinc-400">
                  <span>vs Previous Scan:</span>
                  {changes.summary.signal_flips > 0 && (
                    <span className="text-amber-400 font-medium">{changes.summary.signal_flips} signal flip{changes.summary.signal_flips !== 1 ? 's' : ''}</span>
                  )}
                  {changes.summary.improved > 0 && (
                    <span className="text-emerald-400 font-medium"><ArrowUp className="w-3 h-3 inline" />{changes.summary.improved} improved</span>
                  )}
                  {changes.summary.declined > 0 && (
                    <span className="text-red-400 font-medium"><ArrowDown className="w-3 h-3 inline" />{changes.summary.declined} declined</span>
                  )}
                  {changes.summary.new_count > 0 && (
                    <span className="text-blue-400 font-medium">+{changes.summary.new_count} new</span>
                  )}
                </div>

                {changes.signal_flips.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {changes.signal_flips.slice(0, 6).map(flip => (
                      <span key={flip.ticker} className="inline-flex items-center gap-1 px-2 py-0.5 text-[9px] font-medium rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300">
                        {flip.ticker.replace('.NS', '')}: {flip.from} → {flip.to}
                        <span className={flip.score_delta > 0 ? 'text-emerald-400' : 'text-red-400'}>
                          ({flip.score_delta > 0 ? '+' : ''}{flip.score_delta.toFixed(3)})
                        </span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })()}

      {!data?.broker_connected && !loading && (
        <Card className="bg-amber-500/5 border-amber-500/20">
          <CardContent className="p-4 text-center space-y-2">
            <WifiOff className="w-8 h-8 text-amber-500 mx-auto" />
            <div className="text-sm font-medium text-amber-500">Zerodha Not Connected</div>
            <div className="text-xs text-muted-foreground">Go to <strong>Settings</strong> to connect your Zerodha account.</div>
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SummaryCard icon={Wallet} label="Portfolio Value" value={formatINR(data.summary.portfolio_value)} sub={`Cash: ${formatINR(data.summary.cash)}`} color="bg-blue-500/10" />
            <SummaryCard icon={IndianRupee} label="Total Invested" value={formatINR(data.summary.total_invested)} sub={`${data.summary.num_holdings} holdings, ${data.summary.num_positions} positions`} color="bg-purple-500/10" />
            <SummaryCard icon={data.summary.total_pnl >= 0 ? TrendingUp : TrendingDown} label="Total P&L" value={`${data.summary.total_pnl >= 0 ? '+' : ''}${formatINR(data.summary.total_pnl)}`} sub={`${data.summary.total_pnl_pct >= 0 ? '+' : ''}${data.summary.total_pnl_pct.toFixed(2)}%`} color={data.summary.total_pnl >= 0 ? 'bg-emerald-500/10' : 'bg-red-500/10'} />
            <SummaryCard icon={Briefcase} label="Win / Loss" value={`${gainers}W / ${losers}L`} sub={`${sortedStocks.length} total stocks`} color="bg-amber-500/10" />
          </div>

          {(data.summary.cash > 0 || data.summary.used_margin > 0) && (
            <div className="flex items-center gap-4 text-xs text-muted-foreground bg-muted/30 rounded-lg px-4 py-2">
              <span>Available Cash: <strong className="text-primary">{formatINR(data.summary.cash)}</strong></span>
              <span>Used Margin: <strong className="text-primary">{formatINR(data.summary.used_margin)}</strong></span>
            </div>
          )}

          {sortedStocks.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Sort:</span>
              <div className="flex items-center gap-0.5 flex-wrap">
                {SORT_OPTIONS.map(opt => (
                  <button key={opt.key} onClick={() => {
                    if (sortBy === opt.key) {
                      setSortDir(d => d === 'desc' ? 'asc' : 'desc');
                    } else {
                      setSortBy(opt.key);
                      setSortDir(opt.key === 'name' || opt.key === 'type' ? 'asc' : 'desc');
                    }
                  }}
                    className={`text-[10px] px-2 py-1 rounded-md transition-colors cursor-pointer flex items-center gap-0.5 ${sortBy === opt.key ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:text-primary'}`}>
                    {opt.label}
                    {sortBy === opt.key && (
                      sortDir === 'desc' ? <ArrowDown className="w-2.5 h-2.5" /> : <ArrowUp className="w-2.5 h-2.5" />
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {sortedStocks.length === 0 ? (
            <Card className="bg-muted/20 border-border/30">
              <CardContent className="p-8 text-center">
                <Briefcase className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                <div className="text-sm text-muted-foreground">No holdings or positions found</div>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {sortedStocks.map(stock => (
                <StockRow
                  key={`${stock.ticker}-${stock.type}`}
                  stock={stock}
                  verdict={getVerdict(stock)}
                  expanded={expandedTicker === `${stock.ticker}-${stock.type}`}
                  onToggle={() => setExpandedTicker(expandedTicker === `${stock.ticker}-${stock.type}` ? null : `${stock.ticker}-${stock.type}`)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
