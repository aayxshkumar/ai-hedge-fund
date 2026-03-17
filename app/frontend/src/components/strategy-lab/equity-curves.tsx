import { useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { STRATEGY_COLORS } from './run-controls';
import { formatINRCompact } from '@/lib/format-inr';
import type { BacktestResult } from '@/services/strategy-api';

interface EquityCurvesProps {
  results: BacktestResult[];
  selectedStrategies: string[];
}

export function EquityCurves({ results, selectedStrategies }: EquityCurvesProps) {
  const chartData = useMemo(() => {
    const avgCurves: Record<string, Record<string, { total: number; count: number }>> = {};

    for (const r of results) {
      if (!selectedStrategies.includes(r.strategy) || r.error || !r.equity_curve?.length) continue;
      if (!avgCurves[r.strategy]) avgCurves[r.strategy] = {};

      for (const pt of r.equity_curve) {
        if (!avgCurves[r.strategy][pt.date]) {
          avgCurves[r.strategy][pt.date] = { total: 0, count: 0 };
        }
        avgCurves[r.strategy][pt.date].total += pt.value;
        avgCurves[r.strategy][pt.date].count += 1;
      }
    }

    const allDates = new Set<string>();
    for (const strat of Object.values(avgCurves)) {
      for (const d of Object.keys(strat)) allDates.add(d);
    }
    const sortedDates = [...allDates].sort();

    return sortedDates.map((date) => {
      const row: Record<string, string | number> = { date: date.slice(5) };
      for (const [strategy, datePts] of Object.entries(avgCurves)) {
        const pt = datePts[date];
        row[strategy] = pt ? Math.round(pt.total / pt.count) : 0;
      }
      return row;
    });
  }, [results, selectedStrategies]);

  if (chartData.length === 0) {
    return (
      <div className="rounded-xl border p-4 flex items-center justify-center h-80 bg-card">
        <span className="text-muted-foreground text-sm">Select strategies to view equity curves</span>
      </div>
    );
  }

  return (
    <div className="rounded-xl border p-4 bg-card">
      <h3 className="text-sm font-semibold mb-3">Average Portfolio Value</h3>
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
          {selectedStrategies.map((s) => (
            <Line
              key={s}
              type="monotone"
              dataKey={s}
              stroke={STRATEGY_COLORS[s] || '#888'}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
