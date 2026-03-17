import { useCallback, useEffect, useMemo, useState } from 'react';
import { RunControls, STRATEGY_COLORS } from './run-controls';
import { EquityCurves } from './equity-curves';
import { ReturnsHeatmap } from './returns-heatmap';
import { MetricsTable } from './metrics-table';
import { StockBreakdown } from './stock-breakdown';
import {
  fetchResults,
  fetchResultsSummary,
  fetchHeatmap,
  fetchStrategies,
  type BacktestResult,
  type StrategySummary,
  type Strategy,
} from '@/services/strategy-api';
import { ChevronDown, Search, X } from 'lucide-react';

export function StrategyLab() {
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [summary, setSummary] = useState<StrategySummary[]>([]);
  const [heatmap, setHeatmap] = useState<Record<string, Record<string, number>>>({});
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [selectedPeriod, setSelectedPeriod] = useState<string>('1Y');
  const [loading, setLoading] = useState(false);
  const [allStrategies, setAllStrategies] = useState<Strategy[]>([]);
  const [showStratFilter, setShowStratFilter] = useState(false);
  const [showTickerFilter, setShowTickerFilter] = useState(false);
  const [filterTickerSearch, setFilterTickerSearch] = useState('');
  const [filterStratSearch, setFilterStratSearch] = useState('');
  const [filterTickers, setFilterTickers] = useState<string[]>([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [res, sum, hm, strats] = await Promise.all([
        fetchResults({ period: selectedPeriod, limit: 5000 }),
        fetchResultsSummary(),
        fetchHeatmap(selectedPeriod),
        fetchStrategies(),
      ]);
      setResults(res);
      setSummary(sum);
      setHeatmap(hm);
      setAllStrategies(strats);
      if (selectedStrategies.length === 0 && sum.length > 0) {
        setSelectedStrategies(sum.slice(0, 5).map((s) => s.strategy));
      }
    } catch (err) {
      console.error('Failed to load strategy data', err);
    } finally {
      setLoading(false);
    }
  }, [selectedPeriod]);

  useEffect(() => { loadData(); }, [loadData]);

  const availableTickers = useMemo(() => {
    const set = new Set<string>();
    for (const r of results) if (!r.error) set.add(r.ticker);
    return [...set].sort();
  }, [results]);

  const filteredResults = useMemo(() => {
    return results.filter(r => {
      const stratOk = selectedStrategies.length === 0 || selectedStrategies.includes(r.strategy);
      const tickOk = filterTickers.length === 0 || filterTickers.includes(r.ticker);
      return stratOk && tickOk;
    });
  }, [results, selectedStrategies, filterTickers]);

  const toggleFilterStrategy = (name: string) => {
    setSelectedStrategies(prev =>
      prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]
    );
  };

  const toggleFilterTicker = (t: string) => {
    setFilterTickers(prev =>
      prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]
    );
  };

  return (
    <div className="h-full overflow-y-auto bg-background">
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Clean Header */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Strategy Lab</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Backtest and compare {summary.length} strategies across Nifty 50 stocks
          </p>
        </div>

        {/* Run Controls Card */}
        <RunControls onBatchComplete={loadData} />

        {/* Unified Filter Bar */}
        <div className="flex items-center gap-2 flex-wrap rounded-xl border bg-card p-3">
          {/* Period pills */}
          <div className="flex items-center gap-1">
            {['3M', '6M', '1Y', '2Y'].map((p) => (
              <button
                key={p}
                onClick={() => setSelectedPeriod(p)}
                className={`px-3 py-1 text-xs font-medium rounded-full transition-colors cursor-pointer ${
                  selectedPeriod === p
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted/50 text-muted-foreground hover:bg-muted'
                }`}
              >
                {p}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-border" />

          {/* Strategy filter */}
          <div className="relative">
            <button
              onClick={() => { setShowStratFilter(!showStratFilter); setShowTickerFilter(false); }}
              className="flex items-center gap-1.5 px-3 py-1 text-xs rounded-full border bg-background text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              Strategies: {selectedStrategies.length === 0 ? 'All' : selectedStrategies.length}
              <ChevronDown size={11} />
            </button>
            {showStratFilter && (
              <div className="absolute z-50 mt-1 w-64 rounded-xl border bg-popover shadow-xl max-h-60 overflow-y-auto">
                <div className="sticky top-0 bg-popover p-2 border-b">
                  <div className="relative">
                    <Search size={11} className="absolute left-2.5 top-2 text-muted-foreground" />
                    <input
                      value={filterStratSearch}
                      onChange={e => setFilterStratSearch(e.target.value)}
                      placeholder="Search strategies..."
                      className="w-full pl-7 pr-2 py-1.5 text-xs rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary/50"
                      autoFocus
                    />
                  </div>
                </div>
                {allStrategies.filter(s => s.name.includes(filterStratSearch.toLowerCase())).map(s => (
                  <button
                    key={s.name}
                    onClick={() => toggleFilterStrategy(s.name)}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent text-left cursor-pointer"
                  >
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: STRATEGY_COLORS[s.name] || '#888' }} />
                    <span className={selectedStrategies.includes(s.name) ? 'font-medium text-foreground' : 'text-muted-foreground'}>
                      {s.name.replace(/_/g, ' ')}
                    </span>
                  </button>
                ))}
                <div className="border-t p-2 flex gap-3">
                  <button onClick={() => setSelectedStrategies(allStrategies.map(s => s.name))} className="text-[10px] text-primary hover:underline cursor-pointer">Select All</button>
                  <button onClick={() => setSelectedStrategies([])} className="text-[10px] text-muted-foreground hover:underline cursor-pointer">Clear</button>
                </div>
              </div>
            )}
          </div>

          {/* Ticker filter */}
          <div className="relative">
            <button
              onClick={() => { setShowTickerFilter(!showTickerFilter); setShowStratFilter(false); }}
              className="flex items-center gap-1.5 px-3 py-1 text-xs rounded-full border bg-background text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              Stocks: {filterTickers.length === 0 ? 'All' : filterTickers.length}
              <ChevronDown size={11} />
            </button>
            {showTickerFilter && (
              <div className="absolute z-50 mt-1 w-56 rounded-xl border bg-popover shadow-xl max-h-60 overflow-y-auto">
                <div className="sticky top-0 bg-popover p-2 border-b">
                  <input
                    value={filterTickerSearch}
                    onChange={e => setFilterTickerSearch(e.target.value)}
                    placeholder="Search stocks..."
                    className="w-full px-2.5 py-1.5 text-xs rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary/50"
                    autoFocus
                  />
                </div>
                {availableTickers.filter(t => t.toLowerCase().includes(filterTickerSearch.toLowerCase())).map(t => (
                  <button
                    key={t}
                    onClick={() => toggleFilterTicker(t)}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent text-left cursor-pointer"
                  >
                    <span className={filterTickers.includes(t) ? 'font-medium text-foreground' : 'text-muted-foreground'}>
                      {t.replace('.NS', '')}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <span className="text-xs text-muted-foreground ml-auto">
            {filteredResults.length} results
          </span>
        </div>

        {/* Content */}
        {loading && results.length === 0 ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-muted-foreground">Loading results...</div>
          </div>
        ) : results.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 border border-dashed rounded-xl">
            <p className="text-muted-foreground mb-2">No backtest results yet</p>
            <p className="text-sm text-muted-foreground">Run a batch backtest above to get started</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <EquityCurves results={filteredResults} selectedStrategies={selectedStrategies} />
              <ReturnsHeatmap heatmap={heatmap} selectedStrategies={selectedStrategies} />
            </div>
            <MetricsTable summary={summary} selectedStrategies={selectedStrategies} onSelectStrategies={setSelectedStrategies} />
            <StockBreakdown results={filteredResults} selectedTicker={selectedTicker} onSelectTicker={setSelectedTicker} />
          </>
        )}
      </div>
    </div>
  );
}
