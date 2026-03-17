import { useEffect, useState } from 'react';
import {
  startBatchBacktest,
  streamBatchProgress,
  fetchBatchStatus,
  fetchStrategies,
  fetchTickers,
  type BatchProgress,
  type Strategy,
} from '@/services/strategy-api';
import { formatINR } from '@/lib/format-inr';
import { ChevronDown, Loader2 } from 'lucide-react';

export const STRATEGY_COLORS: Record<string, string> = {
  momentum: '#3b82f6',
  mean_reversion: '#ef4444',
  vwap: '#10b981',
  supertrend: '#f59e0b',
  donchian: '#8b5cf6',
  ichimoku: '#ec4899',
  adx_trend: '#06b6d4',
  stoch_rsi: '#f97316',
  obv_divergence: '#84cc16',
  ma_ribbon: '#a855f7',
  keltner: '#14b8a6',
  volume_breakout: '#e11d48',
  supertrend_adx: '#0ea5e9',
  squeeze_breakout: '#d946ef',
  vwap_momentum: '#22d3ee',
  cloud_oscillator: '#fb923c',
  volume_trend: '#4ade80',
  donchian_trailing: '#818cf8',
  multi_tf_momentum: '#f43f5e',
};

interface RunControlsProps {
  onBatchComplete: () => void;
}

export function RunControls({ onBatchComplete }: RunControlsProps) {
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [allStrategies, setAllStrategies] = useState<Strategy[]>([]);
  const [allTickers, setAllTickers] = useState<string[]>([]);
  const [selectedRunStrategies, setSelectedRunStrategies] = useState<string[]>([]);
  const [selectedRunTickers, setSelectedRunTickers] = useState<string[]>([]);
  const [capital, setCapital] = useState(1000000);
  const [showStratDropdown, setShowStratDropdown] = useState(false);
  const [showTickerDropdown, setShowTickerDropdown] = useState(false);
  const [stratSearch, setStratSearch] = useState('');
  const [tickerSearch, setTickerSearch] = useState('');

  useEffect(() => {
    fetchBatchStatus().then(({ running: r, progress: p }) => {
      setRunning(r);
      if (r) setProgress(p);
    }).catch(() => {});
    fetchStrategies().then(setAllStrategies).catch(() => {});
    fetchTickers().then(setAllTickers).catch(() => {});
  }, []);

  const toggleRunStrategy = (name: string) => {
    setSelectedRunStrategies(prev =>
      prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]
    );
  };

  const toggleRunTicker = (t: string) => {
    setSelectedRunTickers(prev =>
      prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]
    );
  };

  const handleStart = async () => {
    try {
      const params: Record<string, unknown> = { initial_capital: capital };
      if (selectedRunStrategies.length > 0) params.strategies = selectedRunStrategies;
      if (selectedRunTickers.length > 0) params.tickers = selectedRunTickers;
      const res = await startBatchBacktest(params as never);
      if (res.status === 'started') {
        setRunning(true);
        const unsub = streamBatchProgress((p) => {
          setProgress(p);
          if (p.done) {
            setRunning(false);
            unsub();
            onBatchComplete();
          }
        });
      }
    } catch (err) {
      console.error('Failed to start batch', err);
    }
  };

  const filteredStrategies = allStrategies.filter(s =>
    s.name.toLowerCase().includes(stratSearch.toLowerCase()) ||
    s.description.toLowerCase().includes(stratSearch.toLowerCase())
  );

  const filteredTickers = allTickers.filter(t =>
    t.toLowerCase().includes(tickerSearch.toLowerCase())
  );

  const stratCount = selectedRunStrategies.length || allStrategies.length;
  const tickCount = selectedRunTickers.length || allTickers.length;
  const totalJobs = stratCount * tickCount * 2;

  return (
    <div className="p-4 rounded-xl border bg-card space-y-3">
      <div className="flex flex-wrap gap-3 items-end">
        {/* Strategy selector */}
        <div className="relative flex-1 min-w-[200px]">
          <label className="text-xs font-medium text-muted-foreground mb-1 block">Strategies</label>
          <button
            onClick={() => { setShowStratDropdown(!showStratDropdown); setShowTickerDropdown(false); }}
            className="w-full flex items-center justify-between px-3 py-1.5 text-xs rounded-md border bg-background hover:bg-accent/50"
          >
            <span>{selectedRunStrategies.length === 0 ? `All (${allStrategies.length})` : `${selectedRunStrategies.length} selected`}</span>
            <ChevronDown size={12} />
          </button>
          {showStratDropdown && (
            <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-lg max-h-56 overflow-y-auto">
              <div className="sticky top-0 bg-popover p-1.5 border-b">
                <input
                  value={stratSearch}
                  onChange={e => setStratSearch(e.target.value)}
                  placeholder="Search strategies..."
                  className="w-full px-2 py-1 text-xs rounded border bg-background focus:outline-none"
                  autoFocus
                />
              </div>
              {filteredStrategies.map(s => (
                <button
                  key={s.name}
                  onClick={() => toggleRunStrategy(s.name)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent text-left"
                >
                  <span className={`w-3 h-3 rounded border flex items-center justify-center ${selectedRunStrategies.includes(s.name) ? 'bg-primary border-primary text-primary-foreground' : 'border-muted-foreground'}`}>
                    {selectedRunStrategies.includes(s.name) && <span className="text-[9px]">✓</span>}
                  </span>
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: STRATEGY_COLORS[s.name] || '#888' }} />
                  <span className="truncate">{s.name.replace(/_/g, ' ')}</span>
                  <span className="text-muted-foreground ml-auto text-[10px] truncate max-w-[120px]">{s.description}</span>
                </button>
              ))}
              <div className="border-t p-1.5 flex gap-2">
                <button onClick={() => setSelectedRunStrategies(allStrategies.map(s => s.name))} className="text-[10px] text-muted-foreground hover:text-foreground">All</button>
                <button onClick={() => setSelectedRunStrategies([])} className="text-[10px] text-muted-foreground hover:text-foreground">None</button>
              </div>
            </div>
          )}
        </div>

        {/* Ticker selector */}
        <div className="relative flex-1 min-w-[200px]">
          <label className="text-xs font-medium text-muted-foreground mb-1 block">Stocks</label>
          <button
            onClick={() => { setShowTickerDropdown(!showTickerDropdown); setShowStratDropdown(false); }}
            className="w-full flex items-center justify-between px-3 py-1.5 text-xs rounded-md border bg-background hover:bg-accent/50"
          >
            <span>{selectedRunTickers.length === 0 ? `All Nifty 50` : `${selectedRunTickers.length} selected`}</span>
            <ChevronDown size={12} />
          </button>
          {showTickerDropdown && (
            <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-lg max-h-56 overflow-y-auto">
              <div className="sticky top-0 bg-popover p-1.5 border-b">
                <input
                  value={tickerSearch}
                  onChange={e => setTickerSearch(e.target.value)}
                  placeholder="Search tickers..."
                  className="w-full px-2 py-1 text-xs rounded border bg-background focus:outline-none"
                  autoFocus
                />
              </div>
              {filteredTickers.map(t => (
                <button
                  key={t}
                  onClick={() => toggleRunTicker(t)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent text-left"
                >
                  <span className={`w-3 h-3 rounded border flex items-center justify-center ${selectedRunTickers.includes(t) ? 'bg-primary border-primary text-primary-foreground' : 'border-muted-foreground'}`}>
                    {selectedRunTickers.includes(t) && <span className="text-[9px]">✓</span>}
                  </span>
                  <span>{t}</span>
                </button>
              ))}
              <div className="border-t p-1.5 flex gap-2">
                <button onClick={() => setSelectedRunTickers([...allTickers])} className="text-[10px] text-muted-foreground hover:text-foreground">All</button>
                <button onClick={() => setSelectedRunTickers([])} className="text-[10px] text-muted-foreground hover:text-foreground">None</button>
              </div>
            </div>
          )}
        </div>

        {/* Capital */}
        <div className="min-w-[140px]">
          <label className="text-xs font-medium text-muted-foreground mb-1 block">Capital</label>
          <div className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-md border bg-background">
            <span className="text-muted-foreground">₹</span>
            <input
              type="number"
              value={capital}
              onChange={e => setCapital(Number(e.target.value))}
              className="w-full bg-transparent focus:outline-none text-xs"
            />
          </div>
        </div>

        {/* Run button */}
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block invisible">Run</label>
          <button
            onClick={handleStart}
            disabled={running}
            className={`px-4 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
              running
                ? 'bg-muted text-muted-foreground cursor-not-allowed'
                : 'bg-primary text-primary-foreground hover:bg-primary/90'
            }`}
          >
            {running && <Loader2 size={12} className="animate-spin" />}
            {running ? 'Running...' : `Run (${totalJobs} tests)`}
          </button>
        </div>
      </div>

      {/* Progress */}
      {running && progress && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{progress.current_strategy} / {progress.current_ticker}</span>
            <span>
              {progress.completed}/{progress.total} ({progress.pct.toFixed(1)}%)
              {progress.eta_sec > 0 && ` — ETA ${Math.ceil(progress.eta_sec / 60)}m`}
            </span>
          </div>
          <div className="w-full bg-muted rounded-full h-2">
            <div className="bg-primary h-2 rounded-full transition-all duration-500" style={{ width: `${progress.pct}%` }} />
          </div>
        </div>
      )}

      {!running && progress && progress.completed > 0 && (
        <span className="text-xs text-muted-foreground">
          Last run: {progress.completed} backtests ({formatINR(capital)} capital) in {Math.ceil(progress.elapsed_sec / 60)}m
          {progress.failed > 0 && ` (${progress.failed} failed)`}
        </span>
      )}
    </div>
  );
}
