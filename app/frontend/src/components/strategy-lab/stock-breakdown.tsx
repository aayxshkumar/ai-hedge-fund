import { useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import type { BacktestResult } from '@/services/strategy-api';
import { formatINRCompact, formatPct } from '@/lib/format-inr';

interface StockBreakdownProps {
  results: BacktestResult[];
  selectedTicker: string | null;
  onSelectTicker: (t: string | null) => void;
}

export function StockBreakdown({ results, selectedTicker, onSelectTicker }: StockBreakdownProps) {
  const tickers = useMemo(() => {
    const set = new Set<string>();
    for (const r of results) if (!r.error) set.add(r.ticker);
    return [...set].sort();
  }, [results]);

  const chartData = useMemo(() => {
    if (!selectedTicker) return [];
    const tickerResults = results.filter((r) => r.ticker === selectedTicker && !r.error);
    return tickerResults.map((r) => ({
      strategy: r.strategy.replace(/_/g, ' '),
      strategyKey: r.strategy,
      return_pct: Math.round(r.total_return_pct * 10000) / 100,
      final_value: r.final_value,
      sharpe: r.sharpe_ratio ?? 0,
      max_dd: r.max_drawdown_pct ? Math.round(r.max_drawdown_pct * 10000) / 100 : 0,
      trades: r.total_trades,
      win_rate: Math.round(r.win_rate * 10000) / 100,
    })).sort((a, b) => b.return_pct - a.return_pct);
  }, [results, selectedTicker]);

  return (
    <div className="rounded-xl border bg-card">
      <div className="p-4 border-b flex items-center gap-4">
        <h3 className="text-sm font-semibold">Stock Breakdown</h3>
        <select
          className="px-3 py-1.5 text-xs rounded-lg border bg-background text-foreground cursor-pointer"
          value={selectedTicker || ''}
          onChange={(e) => onSelectTicker(e.target.value || null)}
        >
          <option value="">Select a stock...</option>
          {tickers.map((t) => (
            <option key={t} value={t}>{t.replace('.NS', '')}</option>
          ))}
        </select>
      </div>

      {!selectedTicker ? (
        <div className="p-8 text-center text-muted-foreground text-sm">
          Select a stock to compare strategy performance
        </div>
      ) : chartData.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground text-sm">No data for {selectedTicker}</div>
      ) : (
        <div className="p-4">
          <ResponsiveContainer width="100%" height={Math.max(chartData.length * 36, 200)}>
            <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 20, bottom: 5, left: 100 }}>
              <CartesianGrid strokeDasharray="3 3" className="opacity-20" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <YAxis type="category" dataKey="strategy" tick={{ fontSize: 10 }} width={90} />
              <Tooltip
                contentStyle={{ fontSize: 11, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px' }}
                formatter={(value, name) => {
                  if (name === 'return_pct') return [`${Number(value).toFixed(2)}%`, 'Return'];
                  return [String(value), String(name)];
                }}
              />
              <Bar dataKey="return_pct" name="Return %" radius={[0, 4, 4, 0]} fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>

          <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
            {chartData.slice(0, 5).map((d) => (
              <div key={d.strategyKey} className="p-3 rounded-lg border bg-muted/10">
                <div className="text-[10px] text-muted-foreground truncate">{d.strategy}</div>
                <div className={`text-sm font-mono font-bold ${d.return_pct >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                  {formatPct(d.return_pct)}
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {formatINRCompact(d.final_value)} | S: {d.sharpe.toFixed(2)} | WR: {d.win_rate}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
