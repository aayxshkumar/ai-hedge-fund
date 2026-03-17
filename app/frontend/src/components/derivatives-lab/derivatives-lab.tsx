import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchOptionsStrategies, fetchOptionsSummary, fetchOptionsResults,
  startOptionsBatch, streamOptionsBatchProgress, fetchOptionsStatus,
  fetchFuturesStrategies, fetchFuturesSummary, fetchFuturesResults,
  startFuturesBatch, streamFuturesBatchProgress, fetchFuturesStatus,
  type DerivativeStrategy, type DerivativeSummary, type DerivativeResult, type BatchProgress,
} from '@/services/derivatives-api';
import { formatINR, formatINRCompact, formatPct } from '@/lib/format-inr';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar,
} from 'recharts';
import { Loader2, Play, ChevronDown } from 'lucide-react';

const STRATEGY_COLORS: Record<string, string> = {
  long_straddle: '#3b82f6',
  short_straddle: '#ef4444',
  long_strangle: '#10b981',
  iron_condor: '#f59e0b',
  bull_call_spread: '#8b5cf6',
  bear_put_spread: '#ec4899',
  iron_butterfly: '#06b6d4',
  futures_trend: '#3b82f6',
  futures_mean_revert: '#ef4444',
  futures_breakout: '#10b981',
  futures_vwap: '#f59e0b',
};

type Instrument = 'options' | 'futures';

export function DerivativesLab() {
  const [instrument, setInstrument] = useState<Instrument>('options');
  const [strategies, setStrategies] = useState<DerivativeStrategy[]>([]);
  const [summary, setSummary] = useState<DerivativeSummary[]>([]);
  const [results, setResults] = useState<DerivativeResult[]>([]);
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [capital, setCapital] = useState(1000000);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      if (instrument === 'options') {
        const [strats, sum, res] = await Promise.all([
          fetchOptionsStrategies(), fetchOptionsSummary(), fetchOptionsResults(),
        ]);
        setStrategies(strats);
        setSummary(sum);
        setResults(res);
      } else {
        const [strats, sum, res] = await Promise.all([
          fetchFuturesStrategies(), fetchFuturesSummary(), fetchFuturesResults(),
        ]);
        setStrategies(strats);
        setSummary(sum);
        setResults(res);
      }
    } catch (err) {
      console.error('Failed to load derivatives data', err);
    } finally {
      setLoading(false);
    }
  }, [instrument]);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const status = instrument === 'options' ? await fetchOptionsStatus() : await fetchFuturesStatus();
        setRunning(status.running);
        if (status.running) setProgress(status.progress);
      } catch {}
    };
    checkStatus();
  }, [instrument]);

  const handleRun = async () => {
    try {
      const params = { initial_capital: capital };
      const res = instrument === 'options'
        ? await startOptionsBatch(params)
        : await startFuturesBatch(params);

      if (res.status === 'started') {
        setRunning(true);
        const stream = instrument === 'options' ? streamOptionsBatchProgress : streamFuturesBatchProgress;
        const unsub = stream((p) => {
          setProgress(p);
          if (p.done) { setRunning(false); unsub(); loadData(); }
        });
      }
    } catch (err) {
      console.error('Failed to start batch', err);
    }
  };

  const filteredResults = useMemo(() => {
    if (selectedStrategies.length === 0) return results.filter(r => !r.error);
    return results.filter(r => !r.error && selectedStrategies.includes(r.strategy));
  }, [results, selectedStrategies]);

  const chartData = useMemo(() => {
    const stratNames = selectedStrategies.length > 0 ? selectedStrategies : summary.slice(0, 5).map(s => s.strategy);
    const avgCurves: Record<string, Record<string, { total: number; count: number }>> = {};

    for (const r of results) {
      if (!stratNames.includes(r.strategy) || r.error || !r.equity_curve?.length) continue;
      if (!avgCurves[r.strategy]) avgCurves[r.strategy] = {};
      for (const pt of r.equity_curve) {
        if (!avgCurves[r.strategy][pt.date]) avgCurves[r.strategy][pt.date] = { total: 0, count: 0 };
        avgCurves[r.strategy][pt.date].total += pt.value;
        avgCurves[r.strategy][pt.date].count += 1;
      }
    }

    const allDates = new Set<string>();
    for (const strat of Object.values(avgCurves)) for (const d of Object.keys(strat)) allDates.add(d);
    return [...allDates].sort().map((date) => {
      const row: Record<string, string | number> = { date: date.slice(5) };
      for (const [strategy, datePts] of Object.entries(avgCurves)) {
        const pt = datePts[date];
        row[strategy] = pt ? Math.round(pt.total / pt.count) : 0;
      }
      return row;
    });
  }, [results, selectedStrategies, summary]);

  const displayStrategies = selectedStrategies.length > 0 ? selectedStrategies : summary.slice(0, 5).map(s => s.strategy);

  const toggleStrategy = (name: string) => {
    setSelectedStrategies(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]);
  };

  return (
    <div className="h-full overflow-y-auto bg-background">
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Derivatives Lab</h1>
            <p className="text-muted-foreground text-sm mt-1">
              Backtest {instrument === 'options' ? 'options' : 'futures'} strategies on Nifty 50 & Bank Nifty
            </p>
          </div>
          <div className="flex items-center gap-2 bg-muted/50 rounded-lg p-1">
            {(['options', 'futures'] as Instrument[]).map(inst => (
              <button
                key={inst}
                onClick={() => { setInstrument(inst); setSelectedStrategies([]); }}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors cursor-pointer ${
                  instrument === inst
                    ? 'bg-background shadow-sm text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {inst === 'options' ? 'Options' : 'Futures'}
              </button>
            ))}
          </div>
        </div>

        {/* Run Controls */}
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">Capital</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">₹</span>
                <input
                  type="number"
                  value={capital}
                  onChange={e => setCapital(Number(e.target.value))}
                  className="w-36 pl-6 pr-3 py-1.5 text-sm rounded-lg border bg-background"
                />
              </div>
            </div>
            <div className="ml-auto flex items-center gap-3">
              {running && progress && (
                <div className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-primary" />
                  <span className="text-xs text-muted-foreground">
                    {progress.completed}/{progress.total} ({progress.pct.toFixed(0)}%)
                  </span>
                  <div className="w-32 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${progress.pct}%` }} />
                  </div>
                </div>
              )}
              <button
                onClick={handleRun}
                disabled={running}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 cursor-pointer"
              >
                {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Run {instrument === 'options' ? 'Options' : 'Futures'} Backtest
              </button>
            </div>
          </div>
        </div>

        {/* Strategy Pills */}
        <div className="flex flex-wrap gap-2">
          {strategies.map(s => (
            <button
              key={s.name}
              onClick={() => toggleStrategy(s.name)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border transition-colors cursor-pointer ${
                selectedStrategies.includes(s.name) || selectedStrategies.length === 0
                  ? 'bg-card border-border text-foreground shadow-sm'
                  : 'bg-muted/30 border-transparent text-muted-foreground'
              }`}
            >
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: STRATEGY_COLORS[s.name] || '#888' }} />
              {s.name.replace(/_/g, ' ')}
            </button>
          ))}
        </div>

        {loading && results.length === 0 ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : results.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 border border-dashed rounded-xl">
            <p className="text-muted-foreground mb-2">No {instrument} backtest results yet</p>
            <p className="text-sm text-muted-foreground">Click "Run" above to start backtesting</p>
          </div>
        ) : (
          <>
            {/* Equity Curves */}
            <div className="rounded-xl border bg-card p-4">
              <h3 className="text-sm font-semibold mb-3">Portfolio Equity Curves</h3>
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" className="opacity-20" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => formatINRCompact(v)} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px' }}
                    formatter={(val) => [formatINRCompact(Number(val))]}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {displayStrategies.map(s => (
                    <Line key={s} type="monotone" dataKey={s} stroke={STRATEGY_COLORS[s] || '#888'} strokeWidth={2} dot={false} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Summary Table */}
            <div className="rounded-xl border bg-card overflow-auto">
              <div className="p-4 border-b">
                <h3 className="text-sm font-semibold">Strategy Performance</h3>
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/30">
                    <th className="p-3 text-left font-medium">Strategy</th>
                    <th className="p-3 text-right font-medium text-muted-foreground">Tests</th>
                    <th className="p-3 text-right font-medium text-muted-foreground">Avg Return</th>
                    <th className="p-3 text-right font-medium text-muted-foreground">Best</th>
                    <th className="p-3 text-right font-medium text-muted-foreground">Worst</th>
                    <th className="p-3 text-right font-medium text-muted-foreground">Sharpe</th>
                    <th className="p-3 text-right font-medium text-muted-foreground">Win Rate</th>
                    <th className="p-3 text-right font-medium text-muted-foreground">Avg P&L/Trade</th>
                    <th className="p-3 text-right font-medium text-muted-foreground">Profitable</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.map(row => (
                    <tr
                      key={row.strategy}
                      onClick={() => toggleStrategy(row.strategy)}
                      className={`border-b transition-colors cursor-pointer ${
                        selectedStrategies.includes(row.strategy) ? 'bg-primary/5' : 'hover:bg-muted/30'
                      }`}
                    >
                      <td className="p-3 font-medium flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: STRATEGY_COLORS[row.strategy] || '#888' }} />
                        {row.strategy.replace(/_/g, ' ')}
                      </td>
                      <td className="p-3 text-right text-muted-foreground">{row.backtests}</td>
                      <td className={`p-3 text-right font-mono ${row.avg_return_pct > 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                        {formatPct(row.avg_return_pct * 100)}
                      </td>
                      <td className="p-3 text-right font-mono text-emerald-500">{formatPct(row.best_return_pct * 100)}</td>
                      <td className="p-3 text-right font-mono text-red-500">{formatPct(row.worst_return_pct * 100)}</td>
                      <td className="p-3 text-right font-mono">{row.avg_sharpe?.toFixed(2) ?? '—'}</td>
                      <td className="p-3 text-right font-mono">{(row.avg_win_rate * 100).toFixed(1)}%</td>
                      <td className={`p-3 text-right font-mono ${row.avg_pnl_per_trade > 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                        {formatINR(row.avg_pnl_per_trade)}
                      </td>
                      <td className="p-3 text-right font-mono">{(row.profitable_pct * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* P&L Distribution */}
            <div className="rounded-xl border bg-card p-4">
              <h3 className="text-sm font-semibold mb-3">Returns by Strategy & Index</h3>
              <ResponsiveContainer width="100%" height={Math.max(filteredResults.length * 28, 200)}>
                <BarChart
                  data={filteredResults.slice(0, 20).map(r => ({
                    label: `${r.strategy.replace(/_/g, ' ')} · ${r.ticker}`,
                    return_pct: Math.round(r.total_return_pct * 10000) / 100,
                  }))}
                  layout="vertical"
                  margin={{ top: 5, right: 20, bottom: 5, left: 140 }}
                >
                  <CartesianGrid strokeDasharray="3 3" className="opacity-20" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 9 }} width={130} />
                  <Tooltip
                    contentStyle={{ fontSize: 11, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px' }}
                    formatter={(v) => [`${Number(v).toFixed(2)}%`, 'Return']}
                  />
                  <Bar dataKey="return_pct" name="Return %" radius={[0, 4, 4, 0]} fill="#3b82f6" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
