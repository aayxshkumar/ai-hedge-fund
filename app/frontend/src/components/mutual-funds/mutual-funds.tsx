import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { formatINR } from '@/lib/format-inr';
import {
  AlertTriangle, ArrowDown, ArrowUp, Bot, CheckCircle2, ChevronDown, ChevronRight, Globe2, IndianRupee,
  Layers, Loader2, PieChart, RefreshCw, ShieldAlert, Sparkles, TrendingDown, TrendingUp, Wallet, WifiOff,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Area, AreaChart, ResponsiveContainer, Tooltip } from 'recharts';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// ── Types ─────────────────────────────────────────────────────────────

interface Fund {
  fund: string; isin: string; folio?: string; scheme_code?: number; amc: string; category: string; bucket: string; plan: string;
  units: number; avg_nav: number; nav: number; nav_date?: string; invested: number; current: number; pnl: number; pnl_pct: number | null;
  xirr: number | null; weight: number; history_years?: number;
  ret_1m?: number | null; ret_3m?: number | null; ret_6m?: number | null; ret_1y?: number | null; cagr_3y?: number | null; cagr_5y?: number | null;
  vol_1y?: number | null; sharpe_1y?: number | null; max_dd_3y?: number | null; sparkline?: { d: string; v: number }[];
  rank?: { peers?: number; cagr_3y_pct?: number; cagr_3y_median?: number; ratio_pct?: number; max_dd_3y_pct?: number };
}
interface Agg { name: string; current: number; invested: number; count: number; weight: number; pnl_pct: number | null }
interface MFPortfolio {
  as_of: string; fund_count: number; invested: number; current: number; pnl: number; pnl_pct: number | null;
  by_bucket: Agg[]; by_amc: Agg[];
  concentration: { top_fund_weight: number; top3_weight: number; hhi: number; effective_funds: number };
  weighted: { ret_1y: number | null; cagr_3y: number | null; vol_1y: number | null; max_dd_3y: number | null; xirr: number | null };
  funds: Fund[];
  equity?: { count: number; invested: number; current: number; pnl: number; pnl_pct: number | null } | null;
  cap_lookthrough?: { large: number; mid: number; small: number; international: number; other: number };
  universe_as_of?: string | null;
}
interface Review {
  health_score: number; headline: string; overall_assessment: string; strengths: string[]; concerns: string[]; redundancies: string[];
  diversification_notes: string; next_steps: { title: string; rationale: string; priority: 'high' | 'medium' | 'low' }[];
  fund_notes: { fund: string; role: string; flag: 'core' | 'satellite' | 'overlap' | 'review'; note: string }[];
  timestamp: string;
  source?: 'rules' | 'llm';
  profile?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────

const pct = (x: number | null | undefined, digits = 1) => (x === null || x === undefined ? '—' : `${x >= 0 ? '+' : ''}${(x * 100).toFixed(digits)}%`);
const pctPlain = (x: number | null | undefined, digits = 1) => (x === null || x === undefined ? '—' : `${(x * 100).toFixed(digits)}%`);
const signed = (x: number | null | undefined, digits = 2) => (x === null || x === undefined ? '—' : `${x >= 0 ? '+' : ''}${x.toFixed(digits)}%`);
const tone = (x: number | null | undefined) => (x === null || x === undefined ? 'text-muted-foreground' : x >= 0 ? 'text-emerald-400' : 'text-red-400');

const BUCKET_COLORS: Record<string, string> = {
  'Large Cap': '#3b82f6', 'Mid Cap': '#8b5cf6', 'Small Cap': '#ec4899', 'Flexi / Multi / Focused': '#06b6d4',
  'Index - Broad': '#10b981', 'Index - Factor / Smart Beta': '#84cc16', 'Sectoral / Thematic': '#f59e0b',
  'International': '#f97316', 'ELSS': '#14b8a6', 'Hybrid': '#a3a3a3', 'Debt / Liquid': '#64748b', 'Gold / Commodity': '#eab308', 'Other': '#71717a',
};
const bucketColor = (b: string) => BUCKET_COLORS[b] || '#71717a';

const FLAG_STYLE: Record<string, string> = {
  core: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  satellite: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  overlap: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  review: 'bg-red-500/10 text-red-400 border-red-500/20',
};
const PRIORITY_STYLE: Record<string, string> = {
  high: 'bg-red-500/10 text-red-400 border-red-500/20',
  medium: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  low: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20',
};

const ord = (n: number) => `${n}${[11, 12, 13].includes(n % 100) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] || 'th'}`;
function normalizeName(s: string) { return s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').replace(/\b(direct|plan|growth|fund|the)\b/g, '').trim(); }
function noteFor(review: Review | null, fund: Fund) {
  if (!review) return null;
  const target = normalizeName(fund.fund);
  return review.fund_notes.find(n => {
    const nn = normalizeName(n.fund);
    return nn === target || target.includes(nn) || nn.includes(target);
  }) || null;
}

// ── Small components ──────────────────────────────────────────────────

function SummaryCard({ icon: Icon, label, value, sub, color }: { icon: React.ElementType; label: string; value: string; sub?: string; color?: string }) {
  return (
    <Card className="bg-panel border-border/50">
      <CardContent className="p-3 flex items-start gap-3">
        <div className={`p-2 rounded-lg ${color || 'bg-blue-500/10'}`}>
          <Icon className={`h-4 w-4 ${color ? color.replace('bg-', 'text-').replace('/10', '') : 'text-blue-500'}`} />
        </div>
        <div className="min-w-0">
          <div className="text-[10px] text-muted-foreground">{label}</div>
          <div className="text-sm font-semibold text-primary truncate">{value}</div>
          {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, sub, valueClass }: { label: string; value: string; sub?: string; valueClass?: string }) {
  return (
    <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-sm font-semibold font-mono ${valueClass || ''}`}>{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function Sparkline({ data, positive, height = 44 }: { data?: { d: string; v: number }[]; positive: boolean; height?: number }) {
  if (!data || data.length < 2) return <div className="text-[10px] text-muted-foreground">No NAV history</div>;
  const id = positive ? 'mfSparkG' : 'mfSparkR';
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={positive ? '#10b981' : '#ef4444'} stopOpacity={0.3} />
            <stop offset="100%" stopColor={positive ? '#10b981' : '#ef4444'} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Tooltip
          contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 6, fontSize: 10, padding: '4px 8px' }}
          labelStyle={{ color: 'hsl(var(--muted-foreground))' }}
          formatter={(v: any) => [`NAV ${Number(v).toFixed(2)}`, '']}
        />
        <Area type="monotone" dataKey="v" stroke={positive ? '#10b981' : '#ef4444'} fill={`url(#${id})`} strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function AllocationBar({ items }: { items: Agg[] }) {
  return (
    <div className="space-y-3">
      <div className="flex h-3 w-full rounded-full overflow-hidden bg-muted">
        {items.map(b => (
          <div key={b.name} title={`${b.name}: ${b.weight}%`} style={{ width: `${b.weight}%`, background: bucketColor(b.name) }} className="h-full" />
        ))}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5">
        {items.map(b => (
          <div key={b.name} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2 min-w-0">
              <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: bucketColor(b.name) }} />
              <span className="truncate">{b.name}</span>
              <span className="text-[10px] text-muted-foreground">×{b.count}</span>
            </div>
            <div className="flex items-center gap-3 font-mono text-[11px]">
              <span className={tone(b.pnl_pct)}>{signed(b.pnl_pct, 1)}</span>
              <span className="w-12 text-right">{b.weight.toFixed(1)}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HealthRing({ score }: { score: number }) {
  const r = 26, c = 2 * Math.PI * r, off = c * (1 - Math.min(100, Math.max(0, score)) / 100);
  const color = score >= 70 ? '#10b981' : score >= 45 ? '#f59e0b' : '#ef4444';
  return (
    <div className="relative w-16 h-16 shrink-0">
      <svg viewBox="0 0 64 64" className="w-16 h-16 -rotate-90">
        <circle cx="32" cy="32" r={r} stroke="hsl(var(--muted))" strokeWidth="6" fill="none" />
        <circle cx="32" cy="32" r={r} stroke={color} strokeWidth="6" fill="none" strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round" />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-base font-bold font-mono leading-none" style={{ color }}>{score}</span>
        <span className="text-[8px] text-muted-foreground uppercase tracking-wider">health</span>
      </div>
    </div>
  );
}

function ReviewPanel({ review, running, error, onRun, startedAt, title, subtitle, extra }: { review: Review | null; running: boolean; error: string | null; onRun?: () => void; startedAt: string | null; title?: string; subtitle?: string; extra?: React.ReactNode }) {
  const [showAll, setShowAll] = useState(false);
  if (!review && !running && !error) {
    return (
      <Card className="bg-panel border-border/50">
        <CardContent className="p-4 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-violet-500/10"><Bot className="h-4 w-4 text-violet-400" /></div>
            <div>
              <div className="text-sm font-semibold">AI portfolio-construction review</div>
              <div className="text-[11px] text-muted-foreground">Overlap, concentration, cost and role of every fund — grounded in the numbers above.</div>
            </div>
          </div>
          <Button size="sm" onClick={onRun} className="gap-1.5 text-xs"><Sparkles className="h-3 w-3" /> Run review</Button>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card className="bg-panel border-border/50">
      <CardContent className="p-4 space-y-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-4">
            {review && <HealthRing score={review.health_score} />}
            <div>
              <div className="text-sm font-semibold flex items-center gap-2">
                <Bot className="h-4 w-4 text-violet-400" /> {title || 'AI Review'}
                {review && <span className="text-[10px] font-normal text-muted-foreground">{new Date(review.timestamp).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>}
                {subtitle && <span className="text-[10px] font-normal text-muted-foreground">• {subtitle}</span>}
              </div>
              {review && <div className="text-sm text-primary/90 mt-1 max-w-3xl">{review.headline}</div>}
              {running && <div className="text-xs text-muted-foreground mt-1 flex items-center gap-2"><Loader2 className="h-3 w-3 animate-spin" /> Reviewing {startedAt ? `(started ${new Date(startedAt).toLocaleTimeString()})` : ''}…</div>}
              {error && <div className="text-xs text-red-400 mt-1">{error}</div>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {extra}
            {onRun && (
              <Button variant="outline" size="sm" onClick={onRun} disabled={running} className="gap-1.5 text-xs">
                {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} {review ? 'Re-run' : 'Run'}
              </Button>
            )}
          </div>
        </div>

        {review && (
          <>
            <p className="text-xs text-muted-foreground leading-relaxed">{review.overall_assessment}</p>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                <div className="text-[10px] uppercase tracking-wider text-emerald-400 mb-2 flex items-center gap-1"><CheckCircle2 className="h-3 w-3" /> Strengths</div>
                <ul className="space-y-1.5">{review.strengths.map((s, i) => <li key={i} className="text-xs text-zinc-300 leading-snug">• {s}</li>)}</ul>
              </div>
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
                <div className="text-[10px] uppercase tracking-wider text-amber-400 mb-2 flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> Concerns</div>
                <ul className="space-y-1.5">{review.concerns.map((s, i) => <li key={i} className="text-xs text-zinc-300 leading-snug">• {s}</li>)}</ul>
              </div>
              <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-3">
                <div className="text-[10px] uppercase tracking-wider text-violet-400 mb-2 flex items-center gap-1"><Layers className="h-3 w-3" /> Redundancies</div>
                {review.redundancies.length === 0 ? <div className="text-xs text-muted-foreground">None flagged</div> :
                  <ul className="space-y-1.5">{review.redundancies.map((s, i) => <li key={i} className="text-xs text-zinc-300 leading-snug">• {s}</li>)}</ul>}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Next steps to evaluate</div>
              <div className="space-y-2">
                {(showAll ? review.next_steps : review.next_steps.slice(0, 4)).map((n, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-lg bg-muted/30 border border-border/50 p-2.5">
                    <span className={`text-[9px] uppercase font-semibold px-1.5 py-0.5 rounded border shrink-0 mt-0.5 ${PRIORITY_STYLE[n.priority]}`}>{n.priority}</span>
                    <div className="min-w-0">
                      <div className="text-xs font-medium">{n.title}</div>
                      <div className="text-[11px] text-muted-foreground leading-snug mt-0.5">{n.rationale}</div>
                    </div>
                  </div>
                ))}
                {review.next_steps.length > 4 && (
                  <button onClick={() => setShowAll(v => !v)} className="text-[11px] text-primary hover:underline cursor-pointer">
                    {showAll ? 'Show fewer' : `Show all ${review.next_steps.length}`}
                  </button>
                )}
              </div>
            </div>
            {review.diversification_notes && <p className="text-[11px] text-muted-foreground border-t border-border/50 pt-3 leading-relaxed">{review.diversification_notes}</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}

type SortKey = 'weight' | 'pnl_pct' | 'ret_1y' | 'cagr_3y' | 'vol_1y' | 'max_dd_3y' | 'fund';
const SORTS: { key: SortKey; label: string }[] = [
  { key: 'weight', label: 'Weight' }, { key: 'pnl_pct', label: 'P&L' }, { key: 'ret_1y', label: '1Y' },
  { key: 'cagr_3y', label: '3Y CAGR' }, { key: 'vol_1y', label: 'Volatility' }, { key: 'max_dd_3y', label: 'Drawdown' }, { key: 'fund', label: 'Name' },
];

function FundRow({ f, note, expanded, onToggle }: { f: Fund; note: Review['fund_notes'][number] | null; expanded: boolean; onToggle: () => void }) {
  const positive = (f.pnl ?? 0) >= 0;
  return (
    <div className={`rounded-lg border transition-colors ${expanded ? 'border-primary/30 bg-card' : 'border-border/50 bg-card/50 hover:bg-accent/20'}`}>
      <div role="button" tabIndex={0} onClick={onToggle} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); } }}
        className="w-full grid grid-cols-[1fr_auto] sm:grid-cols-[minmax(0,2.2fr)_repeat(5,minmax(0,1fr))_auto] items-center gap-3 px-3 py-2.5 cursor-pointer text-left">
        <div className="min-w-0 flex items-center gap-2">
          <span className="w-1.5 h-6 rounded-full shrink-0" style={{ background: bucketColor(f.bucket) }} />
          <div className="min-w-0">
            <div className="text-xs font-medium truncate" title={f.fund}>{f.fund.replace(/ - DIRECT PLAN$/i, '').replace(/ FUND$/i, ' Fund')}</div>
            <div className="text-[10px] text-muted-foreground flex items-center gap-1.5 truncate">
              <span>{f.bucket}</span><span className="opacity-40">•</span><span className="truncate">{f.amc}</span>
              {f.rank?.cagr_3y_pct !== undefined && (
                <span className={`ml-1 px-1.5 rounded border text-[9px] ${f.rank.cagr_3y_pct >= 67 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : f.rank.cagr_3y_pct < 33 ? 'bg-red-500/10 text-red-400 border-red-500/20' : 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20'}`}
                  title={`3-year CAGR percentile among ${f.rank.peers} ${f.bucket} funds (median ${((f.rank.cagr_3y_median ?? 0) * 100).toFixed(1)}%)`}>
                  {ord(f.rank.cagr_3y_pct)} pct of {f.rank.peers}
                </span>
              )}
              {note && <span className={`ml-1 px-1.5 rounded border text-[9px] uppercase ${FLAG_STYLE[note.flag]}`}>{note.flag}</span>}
            </div>
          </div>
        </div>
        <div className="hidden sm:block text-right font-mono text-xs">{f.weight.toFixed(1)}%<div className="text-[10px] text-muted-foreground">{formatINR(f.current)}</div></div>
        <div className={`hidden sm:block text-right font-mono text-xs ${tone(f.pnl_pct)}`}>{signed(f.pnl_pct)}<div className="text-[10px] text-muted-foreground">{positive ? '+' : ''}{formatINR(f.pnl)}</div></div>
        <div className={`hidden sm:block text-right font-mono text-xs ${tone(f.ret_1y)}`}>{pct(f.ret_1y)}</div>
        <div className={`hidden sm:block text-right font-mono text-xs ${tone(f.cagr_3y)}`}>{pct(f.cagr_3y)}</div>
        <div className="hidden sm:block text-right font-mono text-xs text-muted-foreground">{pctPlain(f.vol_1y, 0)}<div className="text-[10px] text-red-400/70">{pctPlain(f.max_dd_3y, 0)}</div></div>
        <div className="flex items-center justify-end gap-2 sm:gap-1">
          <span className={`sm:hidden font-mono text-xs ${tone(f.pnl_pct)}`}>{signed(f.pnl_pct)}</span>
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
        </div>
      </div>
      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-border/50 grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-4">
          <div className="space-y-3">
            <div className="flex items-center justify-between text-[10px] text-muted-foreground"><span>NAV, last 3 years</span><span>{f.category}{f.history_years ? ` • ${f.history_years}y history` : ''}</span></div>
            <Sparkline data={f.sparkline} positive={(f.cagr_3y ?? f.ret_1y ?? 0) >= 0} height={90} />
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              <Stat label="1M" value={pct(f.ret_1m)} valueClass={tone(f.ret_1m)} />
              <Stat label="3M" value={pct(f.ret_3m)} valueClass={tone(f.ret_3m)} />
              <Stat label="6M" value={pct(f.ret_6m)} valueClass={tone(f.ret_6m)} />
              <Stat label="1Y" value={pct(f.ret_1y)} valueClass={tone(f.ret_1y)} />
              <Stat label="3Y CAGR" value={pct(f.cagr_3y)} valueClass={tone(f.cagr_3y)} />
              <Stat label="5Y CAGR" value={pct(f.cagr_5y)} valueClass={tone(f.cagr_5y)} />
            </div>
          </div>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Units" value={f.units.toLocaleString('en-IN')} sub={`Avg NAV ${f.avg_nav.toFixed(2)} → ${f.nav.toFixed(2)}`} />
              <Stat label="XIRR" value={f.xirr === null ? '—' : `${f.xirr.toFixed(1)}%`} sub={f.folio ? `Folio ${f.folio}` : undefined} />
              <Stat label="Volatility (1Y)" value={pctPlain(f.vol_1y)} sub={f.sharpe_1y != null ? `Sharpe ${f.sharpe_1y.toFixed(2)}` : undefined} />
              <Stat label="Max drawdown (3Y)" value={pctPlain(f.max_dd_3y)} valueClass="text-red-400" />
            </div>
            {note ? (
              <div className={`rounded-lg border p-3 ${FLAG_STYLE[note.flag]}`}>
                <div className="text-[10px] uppercase tracking-wider mb-1 flex items-center gap-1"><Bot className="h-3 w-3" /> {note.flag} • {note.role}</div>
                <div className="text-xs text-zinc-200 leading-snug">{note.note}</div>
              </div>
            ) : (
              <div className="text-[11px] text-muted-foreground">Run the AI review for a per-fund note.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────

export function MutualFunds() {
  const [data, setData] = useState<MFPortfolio | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [reviewRunning, setReviewRunning] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewStarted, setReviewStarted] = useState<string | null>(null);
  const [rules, setRules] = useState<Review | null>(null);
  const [profile, setProfile] = useState<'growth' | 'balanced'>('growth');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortKey>('weight');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [bucketFilter, setBucketFilter] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${API_BASE}/mutual-funds/holdings${refresh ? '?refresh=true' : ''}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      setData(j);
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  }, []);

  const loadReview = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/mutual-funds/review`);
      const j = await r.json();
      setReview(j.review); setReviewRunning(j.running); setReviewError(j.error); setReviewStarted(j.started_at);
    } catch { /* ignore */ }
  }, []);

  const loadRules = useCallback(async (p: 'growth' | 'balanced') => {
    try {
      const r = await fetch(`${API_BASE}/mutual-funds/rules-review?profile=${p}`);
      if (r.ok) setRules(await r.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { load(); loadReview(); }, [load, loadReview]);
  useEffect(() => { if (data) loadRules(profile); }, [data, profile, loadRules]);
  useEffect(() => {
    if (!reviewRunning) return;
    const id = window.setInterval(loadReview, 4000);
    return () => window.clearInterval(id);
  }, [reviewRunning, loadReview]);

  const runReview = async () => {
    setReviewRunning(true); setReviewError(null);
    await fetch(`${API_BASE}/mutual-funds/review`, { method: 'POST' });
    setTimeout(loadReview, 1500);
  };

  const funds = useMemo(() => {
    const list = (data?.funds ?? []).filter(f => !bucketFilter || f.bucket === bucketFilter);
    const val = (f: Fund) => (sortBy === 'fund' ? f.fund : (f[sortBy] as number | null | undefined));
    return [...list].sort((a, b) => {
      const va = val(a), vb = val(b);
      if (typeof va === 'string' && typeof vb === 'string') return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      const na = (va as number | null | undefined) ?? -Infinity, nb = (vb as number | null | undefined) ?? -Infinity;
      return sortDir === 'asc' ? na - nb : nb - na;
    });
  }, [data, sortBy, sortDir, bucketFilter]);

  const combined = data ? data.current + (data.equity?.current ?? 0) : 0;
  const mfShare = data && combined ? (data.current / combined) * 100 : 0;

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-bold text-primary flex items-center gap-2"><PieChart className="w-5 h-5" /> Mutual Funds</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {data ? `${data.fund_count} funds from Zerodha Coin • NAV & analytics from AMFI / mfapi.in` : 'Live holdings from your Zerodha account'}
            {data?.as_of && <span className="ml-2 opacity-60">Updated {new Date(data.as_of).toLocaleTimeString()}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={runReview} disabled={reviewRunning} className="gap-1.5 text-xs">
            {reviewRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Bot className="h-3 w-3" />} {reviewRunning ? 'Reviewing…' : 'Run AI Review'}
          </Button>
          <Button variant="outline" size="sm" onClick={() => load(true)} disabled={loading} className="gap-1.5 text-xs">
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-400 flex items-center gap-2"><WifiOff className="w-4 h-4" /> {error}</div>
      )}

      {loading && !data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-xl border bg-card p-4 space-y-3 animate-pulse"><div className="h-3 w-20 bg-muted rounded" /><div className="h-6 w-28 bg-muted rounded" /><div className="h-3 w-16 bg-muted rounded" /></div>
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SummaryCard icon={Wallet} label="MF Value" value={formatINR(data.current)} sub={`${data.fund_count} funds • ${data.concentration.effective_funds} effective`} color="bg-blue-500/10" />
            <SummaryCard icon={IndianRupee} label="Invested" value={formatINR(data.invested)} sub={`Top-3 funds ${data.concentration.top3_weight}% of value`} color="bg-purple-500/10" />
            <SummaryCard icon={data.pnl >= 0 ? TrendingUp : TrendingDown} label="Unrealised P&L" value={`${data.pnl >= 0 ? '+' : ''}${formatINR(data.pnl)}`} sub={signed(data.pnl_pct)} color={data.pnl >= 0 ? 'bg-emerald-500/10' : 'bg-red-500/10'} />
            <SummaryCard icon={Globe2} label="Total wealth (MF + stocks)" value={formatINR(combined)} sub={data.equity ? `MF ${mfShare.toFixed(0)}% • Stocks ${(100 - mfShare).toFixed(0)}% (${data.equity.count})` : 'No equity data'} color="bg-amber-500/10" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-3">
            <Card className="bg-panel border-border/50">
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-semibold flex items-center gap-2"><Layers className="h-3.5 w-3.5 text-muted-foreground" /> Allocation by role</div>
                  {bucketFilter && <button onClick={() => setBucketFilter(null)} className="text-[10px] text-primary hover:underline cursor-pointer">Clear filter: {bucketFilter}</button>}
                </div>
                <AllocationBar items={data.by_bucket} />
                <div className="flex flex-wrap gap-1 pt-1">
                  {data.by_bucket.map(b => (
                    <button key={b.name} onClick={() => setBucketFilter(bucketFilter === b.name ? null : b.name)}
                      className={`text-[10px] px-2 py-0.5 rounded-full border cursor-pointer transition-colors ${bucketFilter === b.name ? 'border-primary text-primary bg-primary/10' : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
                      {b.name}
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
            <Card className="bg-panel border-border/50">
              <CardContent className="p-4 space-y-3">
                <div className="text-xs font-semibold flex items-center gap-2"><ShieldAlert className="h-3.5 w-3.5 text-muted-foreground" /> Portfolio characteristics <span className="text-[10px] font-normal text-muted-foreground">(value-weighted)</span></div>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="1Y return" value={pct(data.weighted.ret_1y)} valueClass={tone(data.weighted.ret_1y)} />
                  <Stat label="3Y CAGR" value={pct(data.weighted.cagr_3y)} valueClass={tone(data.weighted.cagr_3y)} />
                  <Stat label="Volatility (1Y)" value={pctPlain(data.weighted.vol_1y)} sub="annualised" />
                  <Stat label="Max drawdown (3Y)" value={pctPlain(data.weighted.max_dd_3y)} valueClass="text-red-400" />
                </div>
                {data.cap_lookthrough && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Look-through market cap (estimated from fund roles)</div>
                    <div className="flex h-2.5 w-full rounded-full overflow-hidden bg-muted">
                      {([['large', '#3b82f6'], ['mid', '#8b5cf6'], ['small', '#ec4899'], ['international', '#f97316'], ['other', '#64748b']] as const).map(([k, c]) => (
                        <div key={k} style={{ width: `${data.cap_lookthrough![k]}%`, background: c }} title={`${k} ${data.cap_lookthrough![k]}%`} />
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-x-3 text-[10px] text-muted-foreground mt-1">
                      <span>Large {data.cap_lookthrough.large}%</span><span>Mid {data.cap_lookthrough.mid}%</span><span>Small {data.cap_lookthrough.small}%</span><span>Intl {data.cap_lookthrough.international}%</span>
                    </div>
                  </div>
                )}
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">By AMC</div>
                  <div className="space-y-1">
                    {data.by_amc.slice(0, 6).map(a => (
                      <div key={a.name} className="flex items-center gap-2 text-[11px]">
                        <span className="w-28 truncate text-muted-foreground" title={a.name}>{a.name.replace(' Mutual Fund', '')}</span>
                        <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden"><div className="h-full bg-primary/60 rounded-full" style={{ width: `${a.weight}%` }} /></div>
                        <span className="font-mono w-10 text-right">{a.weight.toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <ReviewPanel review={rules} running={false} error={null} startedAt={null} title="Construction review (rules, no AI)"
            subtitle={rules?.profile ? `${rules.profile} profile • every fund ranked against its category peers` : undefined}
            extra={(
              <div className="flex items-center rounded-md border border-border/60 overflow-hidden text-[10px]">
                {(['growth', 'balanced'] as const).map((p, i) => (
                  <button key={p} onClick={() => setProfile(p)} title={p === 'growth' ? 'Long horizon: broad/large+mid core, mid+small up to 50%, thematic ≤ 20%' : 'Core ≥ 45%, mid+small ≤ 35%, thematic ≤ 15%'}
                    className={`px-2 py-1.5 cursor-pointer transition-colors ${i ? 'border-l border-border/60' : ''} ${profile === p ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:text-foreground'}`}>{p}</button>
                ))}
              </div>
            )} />
          <ReviewPanel review={review} running={reviewRunning} error={reviewError} onRun={runReview} startedAt={reviewStarted} title="AI review" subtitle="LLM narrative on the same numbers; optional" />

          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Sort:</span>
            {SORTS.map(opt => (
              <button key={opt.key} onClick={() => { if (sortBy === opt.key) setSortDir(d => d === 'desc' ? 'asc' : 'desc'); else { setSortBy(opt.key); setSortDir(opt.key === 'fund' ? 'asc' : 'desc'); } }}
                className={`text-[10px] px-2 py-1 rounded-md transition-colors cursor-pointer flex items-center gap-0.5 ${sortBy === opt.key ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:text-primary'}`}>
                {opt.label}{sortBy === opt.key && (sortDir === 'desc' ? <ArrowDown className="w-2.5 h-2.5" /> : <ArrowUp className="w-2.5 h-2.5" />)}
              </button>
            ))}
            <span className="ml-auto text-[10px] text-muted-foreground">{funds.length} of {data.fund_count} funds</span>
          </div>

          <div className="hidden sm:grid grid-cols-[minmax(0,2.2fr)_repeat(5,minmax(0,1fr))_auto] gap-3 px-3 text-[10px] uppercase tracking-wider text-muted-foreground">
            <span>Fund</span><span className="text-right">Weight</span><span className="text-right">P&L</span><span className="text-right">1Y</span><span className="text-right">3Y CAGR</span><span className="text-right">Vol / DD</span><span className="w-4" />
          </div>
          <div className="space-y-2">
            {funds.map(f => (
              <FundRow key={f.isin + (f.folio || '')} f={f} note={noteFor(review, f) || noteFor(rules, f)} expanded={expanded === f.isin} onToggle={() => setExpanded(expanded === f.isin ? null : f.isin)} />
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground">Returns are NAV-based (direct plan, growth) and do not include your cash-flow timing; XIRR comes from Zerodha when available. Educational analysis, not personalised financial advice.</p>
        </>
      )}
    </div>
  );
}
