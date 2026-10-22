"""Quality + price + trend screen over the app's NSE universe (no LLM).

Replaces random sampling in discovery. Yahoo's India feed lacks growth
fields for most names, so this is a first pass: ROE, margins, leverage,
P/E, trend, RSI and liquidity. Results are cached on disk for a week; the
persona scorer (src.analysis.persona_scores) is the second pass.
"""

from __future__ import annotations

import json
import math
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

OUT = Path(__file__).resolve().parents[2] / "outputs"
SCREEN_FILE = OUT / "quality_screen.json"
INFO_CACHE = OUT / "data_cache" / "info"
INFO_TTL = 24 * 3600
SCREEN_TTL = 7 * 24 * 3600


def cached_info(ticker: str) -> dict:
    """`_fetch_fundamentals` with a 24 h disk cache (Yahoo `.info` is the slowest call we make)."""
    from app.backend.routes.hedge_fund import _fetch_fundamentals
    INFO_CACHE.mkdir(parents=True, exist_ok=True)
    p = INFO_CACHE / f"{ticker}.json"
    if p.exists() and time.time() - p.stat().st_mtime < INFO_TTL:
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    f = _fetch_fundamentals(ticker) or {}
    if f.get("market_cap"):
        p.write_text(json.dumps(f, default=str))
    return f


def _clean(o):
    """Replace NaN/inf floats with None so the screen file and its JSON endpoint stay valid."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def score_row(f: dict, tech: dict, turnover_cr: float | None) -> tuple[int, list[str]]:
    s, why = 0, []
    roe, opm, de, pe = f.get("roe"), f.get("operating_margin"), f.get("debt_to_equity"), f.get("pe_ratio")
    if roe and roe > 0.15: s += 2; why.append(f"ROE {roe*100:.0f}%")
    if opm and opm > 0.15: s += 1; why.append(f"OPM {opm*100:.0f}%")
    if de is not None and de < 60: s += 1; why.append(f"D/E {de:.0f}")
    if pe and pe < 25: s += 1; why.append(f"P/E {pe:.0f}")
    if tech.get("trend") == "Bullish": s += 1; why.append("above EMA200")
    if tech.get("rsi") and 40 <= tech["rsi"] <= 65: s += 1; why.append(f"RSI {tech['rsi']:.0f}")
    if (turnover_cr or 0) > 5: s += 1; why.append(f"₹{turnover_cr:.0f} Cr/day")
    return s, why


def run_screen(tickers: list[str] | None = None, workers: int = 3, progress=None) -> dict:
    from app.backend.routes.hedge_fund import _compute_technical
    from app.backend.routes.algo_trader import _history_with_fallback
    from src.data.nse_stocks import NSE_STOCKS

    universe = tickers or NSE_STOCKS
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")

    def one(t):
        row = {"ticker": t}
        try:
            df = _history_with_fallback(t, start, end)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().capitalize() for c in df.columns]
                row["technical"] = _compute_technical(df)
                c = df["Close"]
                row["price"] = round(float(c.iloc[-1]), 2)
                row["ret_1y"] = float(c.iloc[-1] / c.iloc[0] - 1)
                row["ret_3m"] = float(c.iloc[-1] / c.iloc[-64] - 1) if len(c) > 64 else None
                row["turnover_cr"] = float((df["Close"] * df["Volume"]).tail(60).mean() / 1e7)
        except Exception as e:
            row["error"] = str(e)[:80]
        row["fundamentals"] = cached_info(t)
        row = _clean(row)
        s, why = score_row(row["fundamentals"], row.get("technical") or {}, row.get("turnover_cr"))
        row["score"], row["why"] = s, why
        return row

    rows, t0 = [], time.time()
    with ThreadPoolExecutor(workers) as ex:
        for i, r in enumerate(ex.map(one, universe), 1):
            rows.append(r)
            if progress and i % 25 == 0:
                progress(i, len(universe))
    rows.sort(key=lambda r: (-r["score"], -((r["fundamentals"] or {}).get("roe") or 0)))
    result = {"as_of": datetime.now().isoformat(timespec="seconds"), "universe": len(universe),
              "seconds": round(time.time() - t0), "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    SCREEN_FILE.write_text(json.dumps(result, default=str))
    return result


def load_screen(max_age: int = SCREEN_TTL) -> dict | None:
    if SCREEN_FILE.exists() and time.time() - SCREEN_FILE.stat().st_mtime < max_age:
        try:
            return _clean(json.loads(SCREEN_FILE.read_text()))
        except Exception:
            return None
    return None


def top_candidates(n: int = 20, exclude: set[str] | None = None, min_score: int = 5) -> list[str]:
    """Best-scored tickers from the latest screen (empty if no fresh screen)."""
    data = load_screen()
    if not data:
        return []
    ex = {t.upper().replace(".NS", "").replace(".BO", "") for t in (exclude or set())}
    out = []
    for r in data["rows"]:
        base = r["ticker"].upper().replace(".NS", "").replace(".BO", "")
        if r["score"] >= min_score and base not in ex and (r.get("turnover_cr") or 0) >= 5:
            out.append(r["ticker"])
        if len(out) >= n:
            break
    return out
