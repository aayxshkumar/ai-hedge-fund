import { AlertTriangle } from 'lucide-react';
import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface LlmStatus {
  limited: boolean;
  limited_until: string | null;
  last_error: string | null;
  last_error_at: string | null;
  calls_ok: number;
  calls_failed: number;
  model_name: string;
  model_provider: string;
}

/** Polls the backend for LLM gateway availability (usage windows, auth errors). */
export function useLlmStatus(intervalMs = 30000) {
  const [status, setStatus] = useState<LlmStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(`${API_BASE}/hedge-fund/llm-status`);
        if (r.ok && alive) setStatus(await r.json());
      } catch { /* backend down: leave as is */ }
    };
    tick();
    const id = window.setInterval(tick, intervalMs);
    return () => { alive = false; window.clearInterval(id); };
  }, [intervalMs]);
  return status;
}

function fmtUntil(iso: string) {
  const d = new Date(iso);
  const mins = Math.max(0, Math.round((d.getTime() - Date.now()) / 60000));
  const when = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  return mins >= 60 ? `${when} (~${Math.floor(mins / 60)}h ${mins % 60}m)` : `${when} (~${mins}m)`;
}

/** Banner shown on analysis pages while the LLM plan's usage window is exhausted. */
export function LlmStatusBanner({ status }: { status: LlmStatus | null }) {
  if (!status?.limited || !status.limited_until) return null;
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-300 flex items-start gap-2">
      <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
      <div>
        <div className="font-medium">{status.model_provider} usage limit reached — AI analysis paused</div>
        <div className="text-amber-300/80 mt-0.5">
          The plan's usage window resets at <strong>{fmtUntil(status.limited_until)}</strong>. Price data, technicals and fund analytics keep working;
          AI reviews run again after the reset.
        </div>
      </div>
    </div>
  );
}
