const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface AnalysisDecision {
  action: string;
  quantity: number;
  confidence: number;
  reasoning: string;
}

export interface AnalystSignal {
  signal: string;
  confidence: number;
  reasoning: string;
}

export interface AnalysisResult {
  decisions: Record<string, AnalysisDecision>;
  analyst_signals: Record<string, Record<string, AnalystSignal>>;
  current_prices: Record<string, number>;
}

export interface AnalystInfo {
  key: string;
  display_name: string;
  description: string;
  investing_style: string;
  order: number;
}

export async function runAnalysis(
  tickers: string[],
  analysts?: string[],
  modelName?: string,
): Promise<AnalysisResult> {
  const body: Record<string, unknown> = { tickers };
  if (analysts && analysts.length > 0) body.analysts = analysts;
  if (modelName) body.model_name = modelName;

  const res = await fetch(`${API_BASE}/hedge-fund/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Analysis failed');
  }
  return res.json();
}

export async function fetchAnalysts(): Promise<AnalystInfo[]> {
  const res = await fetch(`${API_BASE}/hedge-fund/agents`);
  const data = await res.json();
  return data.agents || [];
}
