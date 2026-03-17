import { useMemo } from 'react';

interface ReturnsHeatmapProps {
  heatmap: Record<string, Record<string, number>>;
  selectedStrategies: string[];
}

function getColor(value: number): string {
  if (value >= 0.2) return 'bg-emerald-500/80 text-white';
  if (value >= 0.1) return 'bg-emerald-400/70 text-white';
  if (value >= 0.05) return 'bg-emerald-300/60 text-emerald-900';
  if (value >= 0) return 'bg-emerald-100/50 text-emerald-800';
  if (value >= -0.05) return 'bg-red-100/50 text-red-800';
  if (value >= -0.1) return 'bg-red-300/60 text-red-900';
  if (value >= -0.2) return 'bg-red-400/70 text-white';
  return 'bg-red-500/80 text-white';
}

export function ReturnsHeatmap({ heatmap, selectedStrategies }: ReturnsHeatmapProps) {
  const { strategies, tickers, data } = useMemo(() => {
    const strats = selectedStrategies.filter((s) => heatmap[s]);
    const tickerSet = new Set<string>();
    for (const s of strats) {
      for (const t of Object.keys(heatmap[s] || {})) tickerSet.add(t);
    }
    const ticks = [...tickerSet].sort();
    return { strategies: strats, tickers: ticks, data: heatmap };
  }, [heatmap, selectedStrategies]);

  if (strategies.length === 0 || tickers.length === 0) {
    return (
      <div className="rounded-xl border p-4 flex items-center justify-center h-80 bg-card">
        <span className="text-muted-foreground text-sm">No heatmap data available</span>
      </div>
    );
  }

  return (
    <div className="rounded-xl border p-4 bg-card overflow-auto">
      <h3 className="text-sm font-semibold mb-3">Returns Heatmap</h3>
      <div className="overflow-auto max-h-[320px]">
        <table className="text-[10px] border-collapse w-full">
          <thead>
            <tr>
              <th className="sticky left-0 bg-card z-10 p-1.5 text-left font-medium text-muted-foreground">Stock</th>
              {strategies.map((s) => (
                <th key={s} className="p-1.5 font-medium text-muted-foreground whitespace-nowrap">
                  {s.replace(/_/g, ' ')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tickers.map((ticker) => (
              <tr key={ticker} className="border-t border-border/20">
                <td className="sticky left-0 bg-card z-10 p-1.5 font-mono whitespace-nowrap font-medium">
                  {ticker.replace('.NS', '')}
                </td>
                {strategies.map((s) => {
                  const val = data[s]?.[ticker];
                  return (
                    <td key={s} className={`p-1.5 text-center font-mono rounded ${val !== undefined ? getColor(val) : 'bg-muted/10'}`}>
                      {val !== undefined ? `${(val * 100).toFixed(1)}%` : '—'}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
