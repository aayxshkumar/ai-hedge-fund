import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  algoTraderApi,
  type AlgoStatus,
  type PortfolioData,
  type AlgoConfig,
  type ExecutionEntry,
  type RiskData,
} from '@/services/algo-trader-api';
import { formatINR } from '@/lib/format-inr';
import {
  Activity,
  AlertTriangle,
  ArrowUpDown,
  Bot,
  CheckCircle2,
  Clock,
  Filter,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Search,
  Settings2,
  Shield,
  TrendingDown,
  TrendingUp,
  Wifi,
  WifiOff,
  X,
  Zap,
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function StatusDot({ ok }: { ok: boolean }) {
  return <span className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-emerald-500' : 'bg-red-500'}`} />;
}

export function AlgoDashboard() {
  const [status, setStatus] = useState<AlgoStatus | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [config, setConfig] = useState<AlgoConfig | null>(null);
  const [execLog, setExecLog] = useState<ExecutionEntry[]>([]);
  const [risk, setRisk] = useState<RiskData | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [watchlistInput, setWatchlistInput] = useState('');
  const [watchlistSuggestions, setWatchlistSuggestions] = useState<string[]>([]);
  const [events, setEvents] = useState<{ type: string; msg: string; ts: string }[]>([]);
  const [screenerResults, setScreenerResults] = useState<any[]>([]);
  const [screenLoading, setScreenLoading] = useState(false);
  const [scannerRunning, setScannerRunning] = useState(false);
  const [lastScanTime, setLastScanTime] = useState<string | null>(null);
  const [liveScanResults, setLiveScanResults] = useState<any[]>([]);
  const [syncLoading, setSyncLoading] = useState(false);
  const [paperPortfolio, setPaperPortfolio] = useState<any>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const refresh = useCallback(async () => {
    try {
      const [s, p, c, e, r] = await Promise.all([
        algoTraderApi.getStatus(),
        algoTraderApi.getPortfolio(),
        algoTraderApi.getConfig(),
        algoTraderApi.getExecutionLog(),
        algoTraderApi.getRisk(),
      ]);
      setStatus(s);
      setPortfolio(p);
      setConfig(c);
      setExecLog(e.log);
      setRisk(r);
      // Fetch scanner status + paper portfolio
      try {
        const [scanResp, paperResp] = await Promise.all([
          fetch(`${API_BASE}/algo-trader/scanner/status`),
          fetch(`${API_BASE}/algo-trader/paper/summary`),
        ]);
        if (scanResp.ok) {
          const scanData = await scanResp.json();
          setScannerRunning(scanData.running);
          setLastScanTime(scanData.last_scan_time);
          if (scanData.results?.length) setLiveScanResults(scanData.results);
        }
        if (paperResp.ok) {
          setPaperPortfolio(await paperResp.json());
        }
      } catch {}
    } catch (err) {
      console.error('Dashboard refresh failed:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 10000);
    return () => clearInterval(iv);
  }, [refresh]);

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/algo-trader/stream`);
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        setEvents(prev => [...prev.slice(-49), data]);
      } catch {}
    };
    return () => es.close();
  }, []);

  const handleStart = async () => {
    setActionLoading('start');
    try { await algoTraderApi.startTrader(); await refresh(); } catch { toast.error('Failed to start trader'); } finally { setActionLoading(null); }
  };

  const handleStop = async () => {
    setActionLoading('stop');
    try { await algoTraderApi.stopTrader(); await refresh(); } catch { toast.error('Failed to stop trader'); } finally { setActionLoading(null); }
  };

  const handleRunCycle = async () => {
    setActionLoading('cycle');
    try { await algoTraderApi.runCycle(); await refresh(); } catch { toast.error('Failed to run cycle'); } finally { setActionLoading(null); }
  };

  const handleToggleMode = async () => {
    if (!config) return;
    if (config.read_only) {
      const confirmed = window.confirm(
        'WARNING: You are about to enable LIVE trading.\n\nReal orders will be placed with real money.\n\nAre you sure?'
      );
      if (!confirmed) return;
    }
    setActionLoading('mode');
    try {
      await algoTraderApi.updateConfig({ read_only: !config.read_only });
      await refresh();
    } catch (e: any) {
      console.error('Mode switch failed:', e);
    } finally { setActionLoading(null); }
  };

  const handleRunScreener = async (autoUpdate = false) => {
    setScreenLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/algo-trader/screen`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ top_n: 15, auto_update_watchlist: autoUpdate }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setScreenerResults(data.screened || []);
        if (autoUpdate) await refresh();
      }
    } catch (err) {
      console.error('Screener failed:', err);
    } finally {
      setScreenLoading(false);
    }
  };

  const handleWatchlistSearch = (val: string) => {
    setWatchlistInput(val.toUpperCase());
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (val.length === 0) { setWatchlistSuggestions([]); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const resp = await fetch(`${API_BASE}/stocks/search?q=${encodeURIComponent(val)}&limit=8`);
        if (!resp.ok) return;
        const data = await resp.json();
        setWatchlistSuggestions((data.results || []).map((r: any) => r.symbol).filter((s: string) => !config?.watchlist.includes(s)));
      } catch {}
    }, 250);
  };

  const addToWatchlist = async (ticker: string) => {
    if (!config) return;
    setWatchlistInput('');
    setWatchlistSuggestions([]);
    await algoTraderApi.updateConfig({ watchlist: [...config.watchlist, ticker] });
    await refresh();
  };

  const removeFromWatchlist = async (ticker: string) => {
    if (!config) return;
    await algoTraderApi.updateConfig({ watchlist: config.watchlist.filter(t => t !== ticker) });
    await refresh();
  };

  const handleToggleScanner = async () => {
    setActionLoading('scanner');
    try {
      const url = scannerRunning ? '/algo-trader/scanner/stop' : '/algo-trader/scanner/start';
      await fetch(`${API_BASE}${url}`, { method: 'POST' });
      await refresh();
    } catch { toast.error('Action failed'); } finally { setActionLoading(null); }
  };

  const handleScanNow = async () => {
    setScreenLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/algo-trader/scanner/run-now`, { method: 'POST' });
      if (resp.ok) {
        const data = await resp.json();
        setLiveScanResults(data.results || []);
        await refresh();
      }
    } catch { toast.error('Screener failed'); } finally { setScreenLoading(false); }
  };

  const handleSyncPortfolio = async () => {
    setSyncLoading(true);
    try {
      await fetch(`${API_BASE}/algo-trader/sync-portfolio`, { method: 'POST' });
      await refresh();
    } catch { toast.error('Portfolio sync failed'); } finally { setSyncLoading(false); }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-background">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const zerodhaOk = status?.zerodha?.connected ?? false;

  return (
    <div className="h-full overflow-y-auto bg-background">
      <div className="max-w-7xl mx-auto p-6 space-y-5">

        {/* ── Status Bar ── */}
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-4">
              <h1 className="text-lg font-bold flex items-center gap-2"><Bot size={20} /> Auto Trader</h1>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                status?.running ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20' : 'bg-muted text-muted-foreground border'
              }`}>
                <StatusDot ok={!!status?.running} /> {status?.running ? 'Running' : 'Stopped'}
              </span>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                config?.read_only ? 'bg-amber-500/15 text-amber-400 border border-amber-500/20' : 'bg-red-500/15 text-red-400 border border-red-500/20'
              }`}>
                {config?.read_only ? 'Paper Mode' : 'LIVE Mode'}
              </span>
              <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium ${
                zerodhaOk ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
              }`}>
                {zerodhaOk ? <Wifi size={10} /> : <WifiOff size={10} />} Zerodha MCP
              </span>
              {status?.is_market_hours && (
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400">
                  <Activity size={10} /> Market Open
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleRunCycle} disabled={!!actionLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border hover:bg-accent/30 transition-colors cursor-pointer disabled:opacity-50">
                {actionLoading === 'cycle' ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />} Run Now
              </button>
              {status?.running ? (
                <button onClick={handleStop} disabled={!!actionLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-red-500/15 text-red-400 border border-red-500/20 hover:bg-red-500/25 cursor-pointer disabled:opacity-50">
                  {actionLoading === 'stop' ? <Loader2 size={12} className="animate-spin" /> : <Pause size={12} />} Stop
                </button>
              ) : (
                <button onClick={handleStart} disabled={!!actionLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/25 cursor-pointer disabled:opacity-50">
                  {actionLoading === 'start' ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Start
                </button>
              )}
              <button onClick={handleToggleMode} disabled={!!actionLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border hover:bg-accent/30 transition-colors cursor-pointer disabled:opacity-50">
                <Settings2 size={12} /> {config?.read_only ? 'Go Live' : 'Go Paper'}
              </button>
              <button onClick={refresh}
                className="p-1.5 rounded-lg border hover:bg-accent/30 transition-colors cursor-pointer">
                <RefreshCw size={12} />
              </button>
            </div>
          </div>
          <div className="flex items-center gap-4 mt-2 text-[10px] text-muted-foreground">
            <span><Clock size={10} className="inline mr-1" />{status?.current_time_ist} IST</span>
            <span>Model: {status?.model_name}</span>
            {status?.last_cycle && <span>Last cycle: {new Date(status.last_cycle).toLocaleTimeString()}</span>}
          </div>
        </div>

        {/* ── Grid Layout ── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

          {/* ── Portfolio Panel ── */}
          <div className="lg:col-span-2 rounded-xl border bg-card p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">Portfolio</h3>
              <div className="flex items-center gap-4 text-xs">
                <span className="text-muted-foreground">Cash: <span className="font-mono font-medium text-foreground">{formatINR(portfolio?.funds?.available_cash || 0)}</span></span>
                <span className="text-muted-foreground">Total: <span className="font-mono font-medium text-foreground">{formatINR(portfolio?.total_value || 0)}</span></span>
                <span className={`font-mono font-medium ${(portfolio?.day_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {(portfolio?.day_pnl || 0) >= 0 ? '+' : ''}{formatINR(portfolio?.day_pnl || 0)} today
                </span>
              </div>
            </div>

            {(portfolio?.positions?.length || 0) > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-muted-foreground border-b">
                      <th className="text-left py-2 font-medium">Ticker</th>
                      <th className="text-right py-2 font-medium">Qty</th>
                      <th className="text-right py-2 font-medium">Avg Price</th>
                      <th className="text-right py-2 font-medium">LTP</th>
                      <th className="text-right py-2 font-medium">P&L</th>
                      <th className="text-right py-2 font-medium">Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {portfolio?.positions?.map((p, i) => (
                      <tr key={i} className="border-b border-border/30">
                        <td className="py-2 font-medium">{p.ticker}</td>
                        <td className="py-2 text-right font-mono">{p.quantity}</td>
                        <td className="py-2 text-right font-mono">{formatINR(p.avg_price, 2)}</td>
                        <td className="py-2 text-right font-mono">{formatINR(p.last_price, 2)}</td>
                        <td className={`py-2 text-right font-mono ${p.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {p.pnl >= 0 ? '+' : ''}{formatINR(p.pnl, 2)}
                        </td>
                        <td className="py-2 text-right">{p.product}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-6 text-muted-foreground text-sm">
                {portfolio?.error ? `Connection error: ${portfolio.error}` : 'No open positions'}
              </div>
            )}

            {(portfolio?.holdings?.length || 0) > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Holdings</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b">
                        <th className="text-left py-2 font-medium">Ticker</th>
                        <th className="text-right py-2 font-medium">Qty</th>
                        <th className="text-right py-2 font-medium">Avg Price</th>
                        <th className="text-right py-2 font-medium">LTP</th>
                        <th className="text-right py-2 font-medium">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portfolio?.holdings?.map((h, i) => (
                        <tr key={i} className="border-b border-border/30">
                          <td className="py-2 font-medium">{h.ticker}</td>
                          <td className="py-2 text-right font-mono">{h.quantity}</td>
                          <td className="py-2 text-right font-mono">{formatINR(h.avg_price, 2)}</td>
                          <td className="py-2 text-right font-mono">{formatINR(h.last_price, 2)}</td>
                          <td className={`py-2 text-right font-mono ${h.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {h.pnl >= 0 ? '+' : ''}{formatINR(h.pnl, 2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {/* ── Paper Portfolio Panel ── */}
          {status?.read_only && paperPortfolio && (
            <div className="lg:col-span-3 rounded-xl border bg-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold flex items-center gap-1.5">
                  <Bot size={14} /> Paper Portfolio
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 ml-1">Simulated</span>
                </h3>
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-muted-foreground">Cash: <span className="font-mono font-medium text-foreground">{formatINR(paperPortfolio.cash)}</span></span>
                  <span className="text-muted-foreground">Value: <span className="font-mono font-medium text-foreground">{formatINR(paperPortfolio.total_value)}</span></span>
                  <span className={`font-mono font-medium ${paperPortfolio.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {paperPortfolio.total_pnl >= 0 ? '+' : ''}{formatINR(paperPortfolio.total_pnl)} ({paperPortfolio.total_return_pct >= 0 ? '+' : ''}{paperPortfolio.total_return_pct}%)
                  </span>
                  <span className="text-muted-foreground">{paperPortfolio.trade_count} trades</span>
                </div>
              </div>
              {paperPortfolio.open_positions > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                  {Object.entries(paperPortfolio.positions || {}).map(([ticker, pos]: [string, any]) => (
                    <div key={ticker} className="p-2 rounded-lg bg-muted/20 border border-border/30">
                      <div className="font-medium">{ticker.replace('.NS', '')}</div>
                      <div className="text-muted-foreground mt-0.5">x{pos.quantity} @ {formatINR(pos.avg_price, 0)}</div>
                      <div className={`font-mono mt-0.5 ${pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pos.unrealized_pnl >= 0 ? '+' : ''}{formatINR(pos.unrealized_pnl, 0)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {paperPortfolio.open_positions === 0 && (
                <p className="text-xs text-muted-foreground">No open paper positions. Start the trader or run a cycle to begin paper trading.</p>
              )}
            </div>
          )}

          {/* ── Risk Panel ── */}
          <div className="rounded-xl border bg-card p-4 space-y-4">
            <h3 className="text-sm font-semibold flex items-center gap-1.5"><Shield size={14} /> Risk</h3>
            {risk && (
              <div className="space-y-3">
                <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Daily P&L</div>
                  <div className={`text-lg font-bold font-mono ${risk.daily_pnl.total >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {risk.daily_pnl.total >= 0 ? '+' : ''}{formatINR(risk.daily_pnl.total)}
                  </div>
                  <div className="flex gap-3 mt-1 text-[10px] text-muted-foreground">
                    <span>Realized: {formatINR(risk.daily_pnl.realized)}</span>
                    <span>Unrealized: {formatINR(risk.daily_pnl.unrealized)}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="p-2.5 rounded-lg bg-muted/30">
                    <div className="text-[10px] text-muted-foreground">Max Daily Loss</div>
                    <div className="font-mono font-medium">{(risk.limits.max_daily_loss_pct * 100).toFixed(1)}%</div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-muted/30">
                    <div className="text-[10px] text-muted-foreground">Stop Loss</div>
                    <div className="font-mono font-medium">{(risk.limits.stop_loss_pct * 100).toFixed(1)}%</div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-muted/30">
                    <div className="text-[10px] text-muted-foreground">Take Profit</div>
                    <div className="font-mono font-medium">{(risk.limits.take_profit_pct * 100).toFixed(1)}%</div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-muted/30">
                    <div className="text-[10px] text-muted-foreground">Max Positions</div>
                    <div className="font-mono font-medium">{risk.limits.max_open_positions}</div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-muted/30">
                    <div className="text-[10px] text-muted-foreground">Max Position %</div>
                    <div className="font-mono font-medium">{(risk.limits.max_position_pct * 100).toFixed(0)}%</div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-muted/30">
                    <div className="text-[10px] text-muted-foreground">Max Exposure</div>
                    <div className="font-mono font-medium">{(risk.limits.max_portfolio_exposure * 100).toFixed(0)}%</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Second Row ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

          {/* ── Watchlist Manager ── */}
          <div className="rounded-xl border bg-card p-4 space-y-3">
            <h3 className="text-sm font-semibold">Watchlist ({config?.watchlist.length || 0})</h3>
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                value={watchlistInput}
                onChange={e => handleWatchlistSearch(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && watchlistSuggestions.length > 0) addToWatchlist(watchlistSuggestions[0]); }}
                placeholder="Add stock..."
                className="w-full pl-8 pr-3 py-2 text-xs rounded-lg border bg-background focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              {watchlistSuggestions.length > 0 && (
                <div className="absolute z-50 mt-1 w-full rounded-lg border bg-popover shadow-xl max-h-36 overflow-y-auto">
                  {watchlistSuggestions.map(s => (
                    <button key={s} onClick={() => addToWatchlist(s)}
                      className="w-full text-left px-3 py-1.5 text-xs hover:bg-accent cursor-pointer flex items-center justify-between">
                      <span>{s.replace('.NS', '').replace('.BO', '')} <span className="text-muted-foreground">{s.endsWith('.BO') ? '.BO' : '.NS'}</span></span>
                      <span className={`text-[9px] font-semibold px-1 py-0.5 rounded ${s.endsWith('.BO') ? 'bg-amber-500/15 text-amber-400' : 'bg-blue-500/15 text-blue-400'}`}>
                        {s.endsWith('.BO') ? 'BSE' : 'NSE'}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
              {config?.watchlist.map(t => (
                <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full bg-primary/10 text-primary border border-primary/20">
                  {t.replace('.NS', '')}
                  <button onClick={() => removeFromWatchlist(t)} className="hover:text-destructive cursor-pointer"><X size={9} /></button>
                </span>
              ))}
            </div>
          </div>

          {/* ── Live Events ── */}
          <div className="rounded-xl border bg-card p-4 space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-1.5"><Activity size={14} /> Live Events</h3>
            <div className="max-h-48 overflow-y-auto space-y-1">
              {events.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-4">No events yet. Start the trader or run a cycle.</div>
              ) : (
                events.slice().reverse().map((ev, i) => (
                  <div key={i} className="flex items-start gap-2 py-1 text-xs">
                    <span className={`mt-0.5 ${
                      ev.type === 'error' ? 'text-red-400' :
                      ev.type === 'cycle_done' ? 'text-emerald-400' :
                      'text-muted-foreground'
                    }`}>
                      {ev.type === 'error' ? <AlertTriangle size={10} /> :
                       ev.type === 'cycle_done' ? <CheckCircle2 size={10} /> :
                       <Clock size={10} />}
                    </span>
                    <span className="text-muted-foreground flex-1">{ev.msg}</span>
                    <span className="text-[9px] text-muted-foreground/50 font-mono">{ev.ts?.slice(11, 19)}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* ── Live Scanner Control ── */}
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <h3 className="text-sm font-semibold flex items-center gap-1.5"><Activity size={14} /> Live Scanner</h3>
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${
                scannerRunning ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20' : 'bg-muted text-muted-foreground border'
              }`}>
                <StatusDot ok={scannerRunning} /> {scannerRunning ? 'Active' : 'Off'}
              </span>
              {lastScanTime && (
                <span className="text-[10px] text-muted-foreground">
                  Last: {new Date(lastScanTime).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleSyncPortfolio} disabled={syncLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border hover:bg-accent/30 transition-colors cursor-pointer disabled:opacity-50">
                {syncLoading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Sync Zerodha Portfolio
              </button>
              <button onClick={handleScanNow} disabled={screenLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border hover:bg-accent/30 transition-colors cursor-pointer disabled:opacity-50">
                {screenLoading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />} Scan Now
              </button>
              <button onClick={handleToggleScanner} disabled={actionLoading === 'scanner'}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg cursor-pointer disabled:opacity-50 ${
                  scannerRunning
                    ? 'bg-red-500/15 text-red-400 border border-red-500/20 hover:bg-red-500/25'
                    : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/25'
                }`}>
                {actionLoading === 'scanner' ? <Loader2 size={12} className="animate-spin" /> : scannerRunning ? <Pause size={12} /> : <Play size={12} />}
                {scannerRunning ? 'Stop' : 'Start'} Auto-Scan
              </button>
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground mt-2">Auto-scans Nifty 50 every 30 minutes during market hours (9:15 AM - 3:30 PM IST). Top picks are added to the watchlist automatically.</p>
          {liveScanResults.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground border-b">
                    <th className="text-left py-1.5 font-medium">#</th>
                    <th className="text-left py-1.5 font-medium">Ticker</th>
                    <th className="text-right py-1.5 font-medium">Score</th>
                    <th className="text-right py-1.5 font-medium">Vol</th>
                    <th className="text-right py-1.5 font-medium">ADX</th>
                    <th className="text-center py-1.5 font-medium">Trend</th>
                    <th className="text-right py-1.5 font-medium">LTP</th>
                  </tr>
                </thead>
                <tbody>
                  {liveScanResults.map((r, i) => (
                    <tr key={r.ticker} className="border-b border-border/30">
                      <td className="py-1.5 text-muted-foreground">{i + 1}</td>
                      <td className="py-1.5 font-medium">{r.ticker?.replace('.NS', '').replace('.BO', '')}</td>
                      <td className="py-1.5 text-right font-mono font-medium">{r.score}</td>
                      <td className="py-1.5 text-right font-mono">{r.volatility}%</td>
                      <td className={`py-1.5 text-right font-mono ${r.adx > 25 ? 'text-emerald-400' : ''}`}>{r.adx}</td>
                      <td className="py-1.5 text-center">
                        {r.trend === 'up' ? <TrendingUp size={12} className="inline text-emerald-400" /> : <TrendingDown size={12} className="inline text-red-400" />}
                      </td>
                      <td className="py-1.5 text-right font-mono">{r.last_close ? formatINR(r.last_close, 2) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Daily Screener ── */}
        <div className="rounded-xl border bg-card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold flex items-center gap-1.5"><Filter size={14} /> Daily Screener</h3>
            <div className="flex items-center gap-2">
              <button onClick={() => handleRunScreener(false)} disabled={screenLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border hover:bg-accent/30 transition-colors cursor-pointer disabled:opacity-50">
                {screenLoading ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />} Scan Nifty 50
              </button>
              <button onClick={() => handleRunScreener(true)} disabled={screenLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 transition-colors cursor-pointer disabled:opacity-50">
                {screenLoading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />} Scan + Update Watchlist
              </button>
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground">Filters stocks by volume (500K+), volatility (15-80%), ADX (15+), and liquidity. Ranks by composite score.</p>
          {screenerResults.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground border-b">
                    <th className="text-left py-2 font-medium">#</th>
                    <th className="text-left py-2 font-medium">Ticker</th>
                    <th className="text-right py-2 font-medium">Score</th>
                    <th className="text-right py-2 font-medium">Avg Vol (20D)</th>
                    <th className="text-right py-2 font-medium">Rel Vol</th>
                    <th className="text-right py-2 font-medium">Volatility</th>
                    <th className="text-right py-2 font-medium">ADX</th>
                    <th className="text-right py-2 font-medium">Sentiment</th>
                    <th className="text-center py-2 font-medium">Trend</th>
                    <th className="text-right py-2 font-medium">LTP</th>
                    <th className="text-center py-2 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {screenerResults.map((r, i) => (
                    <tr key={r.ticker} className="border-b border-border/30">
                      <td className="py-2 text-muted-foreground">{i + 1}</td>
                      <td className="py-2 font-medium">{r.ticker.replace('.NS', '').replace('.BO', '')}</td>
                      <td className="py-2 text-right font-mono font-medium">{r.score}</td>
                      <td className="py-2 text-right font-mono">{(r.avg_volume_20d / 1e5).toFixed(1)}L</td>
                      <td className={`py-2 text-right font-mono ${r.relative_volume > 1.5 ? 'text-emerald-400' : ''}`}>{r.relative_volume}x</td>
                      <td className="py-2 text-right font-mono">{(r.volatility_20d * 100).toFixed(1)}%</td>
                      <td className={`py-2 text-right font-mono ${r.adx > 25 ? 'text-emerald-400' : r.adx > 20 ? 'text-amber-400' : ''}`}>{r.adx}</td>
                      <td className={`py-2 text-right font-mono ${r.sentiment > 0.2 ? 'text-emerald-400' : r.sentiment < -0.2 ? 'text-red-400' : ''}`}>
                        {r.sentiment > 0 ? '+' : ''}{r.sentiment}
                      </td>
                      <td className="py-2 text-center">
                        {r.trend === 'up' ? <TrendingUp size={12} className="inline text-emerald-400" /> : <TrendingDown size={12} className="inline text-red-400" />}
                      </td>
                      <td className="py-2 text-right font-mono">{formatINR(r.last_close, 2)}</td>
                      <td className="py-2 text-center">
                        {!config?.watchlist.includes(r.ticker) && (
                          <button onClick={() => addToWatchlist(r.ticker)}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary hover:bg-primary/20 cursor-pointer">+Add</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-6 text-muted-foreground text-xs">
              {screenLoading ? 'Screening stocks...' : 'Click "Scan Nifty 50" to find the best stocks for today.'}
            </div>
          )}
        </div>

        {/* ── Execution Log ── */}
        <div className="rounded-xl border bg-card p-4 space-y-3">
          <h3 className="text-sm font-semibold">Execution Log ({execLog.length})</h3>
          {execLog.length === 0 ? (
            <div className="text-center py-6 text-muted-foreground text-sm">No trades executed yet</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground border-b">
                    <th className="text-left py-2 font-medium">Time</th>
                    <th className="text-left py-2 font-medium">Ticker</th>
                    <th className="text-left py-2 font-medium">Action</th>
                    <th className="text-right py-2 font-medium">Qty</th>
                    <th className="text-right py-2 font-medium">Price</th>
                    <th className="text-right py-2 font-medium">Confidence</th>
                    <th className="text-left py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {execLog.slice().reverse().map((entry, i) => (
                    <tr key={i} className="border-b border-border/30">
                      <td className="py-2 font-mono text-muted-foreground">{entry.timestamp?.slice(11, 19) || '—'}</td>
                      <td className="py-2 font-medium">{entry.ticker}</td>
                      <td className="py-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          entry.action?.includes('BUY') ? 'bg-emerald-500/15 text-emerald-400' :
                          entry.action?.includes('SELL') || entry.action?.includes('EXIT') ? 'bg-red-500/15 text-red-400' :
                          'bg-muted text-muted-foreground'
                        }`}>{entry.action}</span>
                      </td>
                      <td className="py-2 text-right font-mono">{entry.quantity}</td>
                      <td className="py-2 text-right font-mono">{entry.price ? formatINR(entry.price, 2) : '—'}</td>
                      <td className="py-2 text-right font-mono">{entry.confidence ? `${Math.round(entry.confidence * 100)}%` : '—'}</td>
                      <td className="py-2">
                        {entry.result_ok ? (
                          <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 size={10} /> OK</span>
                        ) : (
                          <span className="text-red-400 flex items-center gap-1" title={entry.result_msg}><AlertTriangle size={10} /> {entry.result_msg?.slice(0, 30)}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Session Plan (Hermes) ── */}
        <SessionPlanPanel />

        {/* ── F&O Positions ── */}
        <FnOPositionsPanel />

        {/* ── Strategy Leaderboard ── */}
        <StrategyLeaderboard />

        {/* ── Learning Timeline ── */}
        <LearningTimeline />

        {/* ── Config ── */}
        <div className="rounded-xl border bg-card p-4 space-y-3">
          <h3 className="text-sm font-semibold flex items-center gap-1.5"><Settings2 size={14} /> Configuration</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="p-2.5 rounded-lg bg-muted/30">
              <div className="text-[10px] text-muted-foreground">Zerodha MCP</div>
              <div className="font-mono font-medium truncate">{config?.broker_connected ? 'Kite Connect — Active' : 'Not connected'}</div>
            </div>
            <div className="p-2.5 rounded-lg bg-muted/30">
              <div className="text-[10px] text-muted-foreground">Model</div>
              <div className="font-mono font-medium truncate">{config?.model_name}</div>
            </div>
            <div className="p-2.5 rounded-lg bg-muted/30">
              <div className="text-[10px] text-muted-foreground">Market Hours</div>
              <div className="font-mono font-medium">{config?.scheduler.market_open} — {config?.scheduler.market_close}</div>
            </div>
            <div className="p-2.5 rounded-lg bg-muted/30">
              <div className="text-[10px] text-muted-foreground">Analysis Interval</div>
              <div className="font-mono font-medium">{config?.scheduler.analysis_interval_minutes} min</div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}


function SessionPlanPanel() {
  const [plan, setPlan] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const fetchPlan = useCallback(() => {
    fetch(`${API_BASE}/algo-trader/session-plan`).then(r => r.json()).then(d => setPlan(d.plan)).catch(() => {});
  }, []);

  useEffect(() => { fetchPlan(); }, [fetchPlan]);

  const generate = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/algo-trader/session-plan/generate`, { method: 'POST' });
      const d = await resp.json();
      if (d.plan) setPlan(d.plan);
      toast.success('Session plan generated');
    } catch { toast.error('Failed to generate plan'); }
    finally { setLoading(false); }
  };

  return (
    <div className="rounded-xl border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold flex items-center gap-1.5 cursor-pointer" onClick={() => setExpanded(!expanded)}>
          <Bot size={14} className="text-cyan-400" /> Hermes Session Plan
        </h3>
        <button onClick={generate} disabled={loading}
          className="text-[10px] px-2.5 py-1 rounded-md bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 disabled:opacity-50 cursor-pointer">
          {loading ? <Loader2 size={10} className="animate-spin inline mr-1" /> : <Zap size={10} className="inline mr-1" />}
          {loading ? 'Generating...' : 'Generate Plan'}
        </button>
      </div>
      {plan && (
        <div className="space-y-2">
          <div className="flex gap-3 text-[11px]">
            {Object.entries(plan.asset_allocation || {}).map(([k, v]: [string, any]) => (
              <span key={k} className="px-2 py-0.5 rounded bg-muted/40 font-mono">
                {k}: {(v * 100).toFixed(0)}%
              </span>
            ))}
            <span className="text-muted-foreground">{Object.keys(plan.strategy_weights || {}).length} strategies</span>
          </div>
          {plan.reasoning && <p className="text-[10px] text-muted-foreground">{plan.reasoning}</p>}
          {plan.focus_tickers?.length > 0 && (
            <div className="text-[10px] text-muted-foreground">Focus: {plan.focus_tickers.join(', ')}</div>
          )}
          {expanded && plan.strategy_weights && (
            <div className="grid grid-cols-3 gap-1.5 text-[10px] mt-2">
              {Object.entries(plan.strategy_weights).sort((a: any, b: any) => b[1] - a[1]).map(([k, v]: [string, any]) => (
                <div key={k} className="flex justify-between px-1.5 py-0.5 rounded bg-muted/20">
                  <span className="truncate">{k}</span>
                  <span className="font-mono ml-1">{(v * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {!plan && !loading && <p className="text-xs text-muted-foreground text-center py-2">No session plan yet. Click Generate to create one.</p>}
    </div>
  );
}


function FnOPositionsPanel() {
  const [data, setData] = useState<any>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/algo-trader/fno/summary`).then(r => r.json()).then(setData).catch(() => {});
    const iv = setInterval(() => {
      fetch(`${API_BASE}/algo-trader/fno/summary`).then(r => r.json()).then(setData).catch(() => {});
    }, 30000);
    return () => clearInterval(iv);
  }, []);

  const fno = data?.fno;
  if (!fno || fno.open_count === 0) return null;

  return (
    <div className="rounded-xl border bg-card p-4 space-y-3">
      <h3 className="text-sm font-semibold flex items-center gap-1.5 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <ArrowUpDown size={14} className="text-purple-400" /> F&O Positions ({fno.open_count})
        <span className={`ml-auto text-xs font-mono ${fno.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          P&L ₹{fno.realized_pnl?.toLocaleString('en-IN')}
        </span>
      </h3>
      {expanded && (
        <div className="space-y-2">
          <div className="flex gap-3 text-[11px] text-muted-foreground">
            <span>Margin used: ₹{fno.margin_used?.toLocaleString('en-IN')}</span>
            <span>Total trades: {fno.total_trades}</span>
          </div>
          {Object.entries(fno.positions || {}).map(([pid, pos]: [string, any]) => (
            <div key={pid} className="rounded-lg border border-border/40 bg-muted/20 p-2.5 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="font-semibold">{pos.underlying} <span className="text-muted-foreground">{pos.instrument_type}</span></span>
                <span className={`font-mono ${pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {pos.side} {pos.lots}L @ ₹{pos.entry_price?.toLocaleString('en-IN')}
                </span>
              </div>
              {pos.strategy_name && <span className="text-[9px] text-muted-foreground">{pos.strategy_name}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


function StrategyLeaderboard() {
  const [data, setData] = useState<any>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/algo-trader/strategy-performance`).then(r => r.json()).then(setData).catch(() => {});
  }, []);

  const board = data?.leaderboard || [];
  if (board.length === 0) return null;

  return (
    <div className="rounded-xl border bg-card p-4 space-y-3">
      <h3 className="text-sm font-semibold flex items-center gap-1.5 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <Activity size={14} className="text-amber-400" /> Strategy Leaderboard ({board.length})
      </h3>
      {expanded && (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead><tr className="text-muted-foreground border-b">
              <th className="text-left py-1.5">Strategy</th>
              <th className="text-right py-1.5">Trades</th>
              <th className="text-right py-1.5">Win%</th>
              <th className="text-right py-1.5">P&L</th>
            </tr></thead>
            <tbody>
              {board.map((s: any) => (
                <tr key={s.strategy_name} className="border-b border-border/20">
                  <td className="py-1.5 font-medium">{s.strategy_name}</td>
                  <td className="py-1.5 text-right font-mono">{s.total_trades}</td>
                  <td className={`py-1.5 text-right font-mono ${s.win_rate > 50 ? 'text-emerald-400' : 'text-red-400'}`}>{s.win_rate}%</td>
                  <td className={`py-1.5 text-right font-mono ${s.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    ₹{s.total_pnl?.toLocaleString('en-IN')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


function LearningTimeline() {
  const [data, setData] = useState<any>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/algo-trader/learning/timeline`).then(r => r.json()).then(setData).catch(() => {});
  }, []);

  const lessons = data?.lessons || [];
  const mistakes = data?.mistake_patterns || [];
  if (lessons.length === 0 && mistakes.length === 0) return null;

  return (
    <div className="rounded-xl border bg-card p-4 space-y-3">
      <h3 className="text-sm font-semibold flex items-center gap-1.5 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <Shield size={14} className="text-indigo-400" /> Learning Timeline
        <span className="ml-2 text-[10px] text-muted-foreground">{lessons.length} lessons, {mistakes.length} patterns</span>
      </h3>
      {expanded && (
        <div className="space-y-3">
          {lessons.map((l: any, i: number) => (
            <div key={i} className="text-[11px] border-l-2 border-indigo-500/30 pl-3 py-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-muted-foreground">{l.date}</span>
                <span className={`font-mono ${l.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>₹{l.pnl?.toLocaleString('en-IN')}</span>
                <span className="text-muted-foreground">{l.trades} trades</span>
              </div>
              <p className="text-muted-foreground mt-0.5">{l.lesson}</p>
            </div>
          ))}
          {mistakes.length > 0 && (
            <div>
              <div className="text-[10px] text-red-400 font-semibold uppercase tracking-wider mb-1">Repeated Mistakes</div>
              {mistakes.map((m: any, i: number) => (
                <div key={i} className="text-[10px] text-red-400/80 py-0.5">
                  {m.strategy_name} in {m.trend || '?'} ({m.instrument_type}): {m.count}x, ₹{m.total_loss?.toLocaleString('en-IN')}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
