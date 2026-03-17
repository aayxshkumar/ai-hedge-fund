import { useState } from 'react';
import type { StrategySummary } from '@/services/strategy-api';
import { STRATEGY_COLORS } from './run-controls';
import { formatPct } from '@/lib/format-inr';
import { ArrowDown, ArrowUp } from 'lucide-react';

interface MetricsTableProps {
  summary: StrategySummary[];
  selectedStrategies: string[];
  onSelectStrategies: (s: string[]) => void;
}

type SortKey = keyof StrategySummary;

export function MetricsTable({ summary, selectedStrategies, onSelectStrategies }: MetricsTableProps) {
  const [sortBy, setSortBy] = useState<SortKey>('avg_return_pct');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const sorted = [...summary].sort((a, b) => {
    const av = a[sortBy] ?? 0;
    const bv = b[sortBy] ?? 0;
    return sortDir === 'desc' ? (bv as number) - (av as number) : (av as number) - (bv as number);
  });

  const handleSort = (key: SortKey) => {
    if (sortBy === key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(key);
      setSortDir('desc');
    }
  };

  const toggleStrategy = (name: string) => {
    if (selectedStrategies.includes(name)) {
      onSelectStrategies(selectedStrategies.filter((s) => s !== name));
    } else {
      onSelectStrategies([...selectedStrategies, name]);
    }
  };

  const columns: { key: SortKey; label: string; fmt: (v: unknown) => string }[] = [
    { key: 'avg_return_pct', label: 'Avg Return', fmt: (v) => formatPct(Number(v) * 100) },
    { key: 'median_return_pct', label: 'Median', fmt: (v) => formatPct(Number(v) * 100) },
    { key: 'best_return_pct', label: 'Best', fmt: (v) => formatPct(Number(v) * 100) },
    { key: 'worst_return_pct', label: 'Worst', fmt: (v) => formatPct(Number(v) * 100) },
    { key: 'avg_sharpe', label: 'Sharpe', fmt: (v) => v != null ? Number(v).toFixed(2) : '—' },
    { key: 'avg_sortino', label: 'Sortino', fmt: (v) => v != null ? Number(v).toFixed(2) : '—' },
    { key: 'avg_max_drawdown', label: 'Max DD', fmt: (v) => v != null ? formatPct(Number(v) * 100) : '—' },
    { key: 'avg_win_rate', label: 'Win Rate', fmt: (v) => `${(Number(v) * 100).toFixed(1)}%` },
    { key: 'profitable_pct', label: 'Profitable', fmt: (v) => `${(Number(v) * 100).toFixed(1)}%` },
    { key: 'avg_trades', label: 'Trades', fmt: (v) => v != null ? Number(v).toFixed(0) : '—' },
  ];

  return (
    <div className="rounded-xl border bg-card overflow-auto">
      <div className="p-4 border-b">
        <h3 className="text-sm font-semibold">Strategy Comparison</h3>
        <p className="text-xs text-muted-foreground mt-0.5">Click rows to toggle chart visibility. Click headers to sort.</p>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b bg-muted/20">
            <th className="p-2.5 text-left font-medium">Strategy</th>
            <th className="p-2.5 text-left font-medium text-muted-foreground">#</th>
            {columns.map((c) => (
              <th
                key={c.key}
                className="p-2.5 text-right font-medium cursor-pointer hover:text-foreground text-muted-foreground transition-colors"
                onClick={() => handleSort(c.key)}
              >
                <span className="inline-flex items-center gap-1">
                  {c.label}
                  {sortBy === c.key && (sortDir === 'desc' ? <ArrowDown size={10} /> : <ArrowUp size={10} />)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const selected = selectedStrategies.includes(row.strategy);
            return (
              <tr
                key={row.strategy}
                className={`border-b cursor-pointer transition-colors ${
                  selected ? 'bg-primary/5' : 'hover:bg-muted/20'
                }`}
                onClick={() => toggleStrategy(row.strategy)}
              >
                <td className="p-2.5 font-medium flex items-center gap-2">
                  <span
                    className="w-3 h-3 rounded-full flex-shrink-0 transition-colors"
                    style={{
                      backgroundColor: selected ? (STRATEGY_COLORS[row.strategy] || '#888') : 'transparent',
                      border: `2px solid ${STRATEGY_COLORS[row.strategy] || '#888'}`,
                    }}
                  />
                  {row.strategy.replace(/_/g, ' ')}
                </td>
                <td className="p-2.5 text-muted-foreground">{row.backtests}</td>
                {columns.map((c) => {
                  const val = row[c.key];
                  const isReturn = c.key.includes('return');
                  const color =
                    isReturn && typeof val === 'number'
                      ? val > 0 ? 'text-emerald-500' : val < 0 ? 'text-red-500' : ''
                      : '';
                  return (
                    <td key={c.key} className={`p-2.5 text-right font-mono ${color}`}>
                      {c.fmt(val)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
