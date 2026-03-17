import { useEffect, useState, useCallback } from 'react';
import { algoTraderApi } from '../../services/algo-trader-api';
import {
  BookOpen, TrendingUp, TrendingDown, RefreshCw, Filter, ChevronDown,
  ChevronRight, Target, Clock, Award, AlertTriangle, BarChart3
} from 'lucide-react';

interface Trade {
  id: number;
  timestamp: string;
  ticker: string;
  action: string;
  side: string;
  quantity: number;
  price: number;
  mode: string;
  confidence: number;
  decision_score: number;
  reasoning: string;
  strategy_scores: Record<string, number>;
  analyst_signals: Record<string, any>;
  rsi: number | null;
  macd: number | null;
  trend: string | null;
  volatility: number | null;
  executed: number;
  execution_price: number | null;
  execution_msg: string;
  exit_price: number | null;
  exit_timestamp: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  holding_duration_hours: number | null;
  exit_reason: string | null;
  model_name: string;
  source: string;
}

interface Stats {
  total_trades: number;
  closed_trades: number;
  open_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  avg_holding_hours: number;
  best_trade: { ticker: string; pnl: number } | null;
  worst_trade: { ticker: string; pnl: number } | null;
  by_action: { action: string; count: number; total_pnl: number; avg_pnl: number }[];
  by_ticker: { ticker: string; count: number; total_pnl: number; wins: number }[];
}

function formatINR(n: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function PnlBadge({ value }: { value: number | null }) {
  if (value == null) return <span className="text-xs text-zinc-500">OPEN</span>;
  const positive = value >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-semibold ${positive ? 'text-emerald-400' : 'text-red-400'}`}>
      {positive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {formatINR(value)} ({value >= 0 ? '+' : ''}{(value / Math.max(1, Math.abs(value))) > 0 ? '+' : ''})
    </span>
  );
}

function StatCard({ icon: Icon, label, value, sub, color = 'zinc' }: {
  icon: any; label: string; value: string | number; sub?: string; color?: string;
}) {
  const colors: Record<string, string> = {
    emerald: 'border-emerald-500/30 bg-emerald-500/5',
    red: 'border-red-500/30 bg-red-500/5',
    blue: 'border-blue-500/30 bg-blue-500/5',
    amber: 'border-amber-500/30 bg-amber-500/5',
    zinc: 'border-zinc-700 bg-zinc-800/50',
  };
  return (
    <div className={`rounded-lg border p-3 ${colors[color] || colors.zinc}`}>
      <div className="flex items-center gap-2 text-xs text-zinc-400 mb-1">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className="text-lg font-bold text-zinc-100">{value}</div>
      {sub && <div className="text-xs text-zinc-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export function Tradebook() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<'all' | 'open' | 'winning' | 'losing'>('all');
  const [limit, setLimit] = useState(50);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [tb, st] = await Promise.all([
        algoTraderApi.getTradebook(limit, undefined, filter === 'open'),
        algoTraderApi.getTradebookStats(),
      ]);
      let filtered = tb.trades;
      if (filter === 'winning') filtered = filtered.filter((t: Trade) => t.pnl != null && t.pnl > 0);
      if (filter === 'losing') filtered = filtered.filter((t: Trade) => t.pnl != null && t.pnl < 0);
      setTrades(filtered);
      setStats(st);
    } catch (e) {
      console.error('Tradebook fetch error', e);
    } finally {
      setLoading(false);
    }
  }, [limit, filter]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="p-4 space-y-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-bold text-zinc-100">Tradebook</h2>
          <span className="text-xs text-zinc-500">Every trade logged for model learning</span>
        </div>
        <button onClick={refresh} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-xs text-zinc-300 hover:bg-zinc-700 transition">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <StatCard icon={BarChart3} label="Total Trades" value={stats.total_trades} sub={`${stats.open_trades} open`} color="blue" />
          <StatCard icon={Award} label="Win Rate" value={`${stats.win_rate}%`} sub={`${stats.winning_trades}W / ${stats.losing_trades}L`} color={stats.win_rate >= 50 ? 'emerald' : 'red'} />
          <StatCard icon={TrendingUp} label="Total P&L" value={formatINR(stats.total_pnl)} color={stats.total_pnl >= 0 ? 'emerald' : 'red'} />
          <StatCard icon={Target} label="Profit Factor" value={stats.profit_factor.toFixed(2)} sub={`Avg win: ${formatINR(stats.avg_win)}`} color={stats.profit_factor >= 1 ? 'emerald' : 'amber'} />
          <StatCard icon={Clock} label="Avg Hold" value={`${stats.avg_holding_hours.toFixed(1)}h`} color="zinc" />
          <StatCard icon={AlertTriangle} label="Avg Loss" value={formatINR(stats.avg_loss)} color="red" />
        </div>
      )}

      {/* Top performers by ticker */}
      {stats && stats.by_ticker.length > 0 && (
        <div className="rounded-lg border border-zinc-700 bg-zinc-900/50 p-3">
          <h3 className="text-xs font-semibold text-zinc-400 mb-2">Performance by Ticker</h3>
          <div className="flex flex-wrap gap-2">
            {stats.by_ticker.slice(0, 12).map(t => (
              <div key={t.ticker} className={`px-2 py-1 rounded text-xs font-mono border ${t.total_pnl >= 0 ? 'border-emerald-600/40 bg-emerald-900/20 text-emerald-300' : 'border-red-600/40 bg-red-900/20 text-red-300'}`}>
                {t.ticker.replace('.NS', '')} {formatINR(t.total_pnl)} ({t.wins}/{t.count})
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-2">
        <Filter className="w-3.5 h-3.5 text-zinc-500" />
        {(['all', 'open', 'winning', 'losing'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-2.5 py-1 rounded text-xs transition ${filter === f ? 'bg-blue-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'}`}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
        <select value={limit} onChange={e => setLimit(Number(e.target.value))}
          className="ml-auto px-2 py-1 rounded text-xs bg-zinc-800 border border-zinc-700 text-zinc-300">
          <option value={25}>25 trades</option>
          <option value={50}>50 trades</option>
          <option value={100}>100 trades</option>
          <option value={200}>200 trades</option>
        </select>
      </div>

      {/* Trades list */}
      <div className="rounded-lg border border-zinc-700 bg-zinc-900/50 overflow-hidden">
        {trades.length === 0 ? (
          <div className="p-8 text-center text-zinc-500">
            {loading ? 'Loading trades...' : 'No trades recorded yet. Run a trading cycle to see entries here.'}
          </div>
        ) : (
          <div className="divide-y divide-zinc-800">
            {trades.map(trade => (
              <div key={trade.id} className="hover:bg-zinc-800/50 transition">
                <button onClick={() => setExpandedId(expandedId === trade.id ? null : trade.id)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left">
                  {expandedId === trade.id ? <ChevronDown className="w-4 h-4 text-zinc-500 shrink-0" /> : <ChevronRight className="w-4 h-4 text-zinc-500 shrink-0" />}

                  <span className={`w-10 text-center text-xs font-bold rounded px-1.5 py-0.5 ${trade.action === 'buy' ? 'bg-emerald-600/20 text-emerald-400' : trade.action === 'sell' ? 'bg-red-600/20 text-red-400' : 'bg-zinc-700 text-zinc-400'}`}>
                    {trade.action.toUpperCase()}
                  </span>

                  <span className="font-mono text-sm text-zinc-200 w-32">{trade.ticker.replace('.NS', '')}</span>

                  <span className="text-xs text-zinc-400 w-16">x{trade.quantity}</span>
                  <span className="text-xs text-zinc-400 w-24">{formatINR(trade.price)}</span>

                  <span className={`text-xs px-1.5 py-0.5 rounded ${trade.mode === 'live' ? 'bg-amber-600/20 text-amber-400' : 'bg-zinc-700 text-zinc-400'}`}>
                    {trade.mode}
                  </span>

                  <span className="text-xs text-zinc-500 w-20">conf: {(trade.confidence * 100).toFixed(0)}%</span>

                  <div className="ml-auto flex items-center gap-3">
                    <PnlBadge value={trade.pnl} />
                    <span className="text-xs text-zinc-600 w-28 text-right">{formatTime(trade.timestamp)}</span>
                  </div>
                </button>

                {expandedId === trade.id && (
                  <div className="px-4 pb-3 pl-11 space-y-2">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                      <div><span className="text-zinc-500">RSI:</span> <span className="text-zinc-300">{trade.rsi?.toFixed(1) ?? 'N/A'}</span></div>
                      <div><span className="text-zinc-500">MACD:</span> <span className="text-zinc-300">{trade.macd?.toFixed(3) ?? 'N/A'}</span></div>
                      <div><span className="text-zinc-500">Trend:</span> <span className="text-zinc-300">{trade.trend ?? 'N/A'}</span></div>
                      <div><span className="text-zinc-500">Volatility:</span> <span className="text-zinc-300">{trade.volatility?.toFixed(2) ?? 'N/A'}%</span></div>
                      <div><span className="text-zinc-500">Source:</span> <span className="text-zinc-300">{trade.source}</span></div>
                      <div><span className="text-zinc-500">Model:</span> <span className="text-zinc-300">{trade.model_name || 'N/A'}</span></div>
                      <div><span className="text-zinc-500">Exec Price:</span> <span className="text-zinc-300">{trade.execution_price ? formatINR(trade.execution_price) : 'N/A'}</span></div>
                      <div><span className="text-zinc-500">Hold Time:</span> <span className="text-zinc-300">{trade.holding_duration_hours ? `${trade.holding_duration_hours.toFixed(1)}h` : 'N/A'}</span></div>
                    </div>

                    {trade.reasoning && (
                      <div className="text-xs">
                        <span className="text-zinc-500">Reasoning: </span>
                        <span className="text-zinc-400">{trade.reasoning}</span>
                      </div>
                    )}

                    {trade.execution_msg && (
                      <div className="text-xs">
                        <span className="text-zinc-500">Result: </span>
                        <span className={trade.executed ? 'text-emerald-400' : 'text-red-400'}>{trade.execution_msg}</span>
                      </div>
                    )}

                    {trade.exit_reason && (
                      <div className="text-xs">
                        <span className="text-zinc-500">Exit Reason: </span>
                        <span className="text-amber-400">{trade.exit_reason}</span>
                      </div>
                    )}

                    {trade.analyst_signals && Object.keys(trade.analyst_signals).length > 0 && (
                      <div className="text-xs">
                        <span className="text-zinc-500">Analyst Signals: </span>
                        <span className="text-zinc-400 font-mono">{JSON.stringify(trade.analyst_signals)}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
