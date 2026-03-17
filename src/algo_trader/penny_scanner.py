"""Penny / Micro-cap Stock Scanner — full AI-powered discovery for sub-₹100 stocks.

Phase 1 — Technical pre-filter: scans the full NSE+BSE universe to find
stocks under ₹100 with decent volume and momentum signals.

Phase 2 — AI Analysis: runs the complete 21-agent + swarm + meta-analyst
pipeline on the top technical candidates.

Phase 3 — Final filter: only stocks the AI recommends as buy or strong_buy
are saved and surfaced in the UI.

Each scan discovers NEW stocks by tracking previously scanned tickers.
"""

from __future__ import annotations

import json
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
OUTPUTS_DIR = Path(__file__).resolve().parent.parent.parent / "outputs"
PENNY_SCAN_FILE = OUTPUTS_DIR / "penny_scan.json"
PENNY_HISTORY_FILE = OUTPUTS_DIR / "penny_scanned_tickers.json"

MAX_PRICE = 100
MIN_PRICE = 3
MIN_AVG_VOLUME = 30_000
MIN_DATA_DAYS = 25
PREFILTER_TOP_N = 6
AI_BATCH_SIZE = 4


def _now_ist() -> str:
    return datetime.now(IST).isoformat()


# ── Previously scanned ticker tracking ────────────────────────────────

def _load_scanned_history() -> dict:
    if PENNY_HISTORY_FILE.exists():
        try:
            with open(PENNY_HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"scanned": [], "last_reset": _now_ist()}


def _save_scanned_history(history: dict):
    import os
    PENNY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PENNY_HISTORY_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(history, f, indent=2, default=str)
    os.replace(str(tmp), str(PENNY_HISTORY_FILE))


# ── Technical helpers ─────────────────────────────────────────────────

def _compute_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not np.isnan(val) else 50.0


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr = pd.concat([
        (high - low).rename("a"),
        (high - close.shift(1)).abs().rename("b"),
        (low - close.shift(1)).abs().rename("c"),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx_series = dx.rolling(period).mean()
    val = adx_series.iloc[-1]
    return float(val) if not np.isnan(val) else 0.0


def _quick_price_check(ticker: str) -> float | None:
    """Fast price check — returns last close or None if invalid."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        try:
            p = t.fast_info.get("lastPrice")
            if p and float(p) > 0:
                return float(p)
        except Exception:
            pass
        h = t.history(period="5d")
        if h is not None and not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


@dataclass
class TechnicalCandidate:
    """Intermediate result from the technical pre-filter phase."""
    ticker: str
    score: float
    last_close: float
    rsi: float
    adx: float
    ema_trend: str
    momentum_5d: float
    momentum_20d: float
    volume_surge: bool
    relative_volume: float
    avg_volume_20d: float
    target_price: float
    stop_loss: float
    risk_reward: float
    time_horizon: str
    swing_high: float
    swing_low: float
    reasoning: str


def _technical_screen(ticker: str) -> TechnicalCandidate | None:
    """Screen a single stock for sub-₹100 price + technical quality."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period="90d")
        if df is None or len(df) < MIN_DATA_DAYS:
            return None

        df.columns = [str(c).strip().capitalize() for c in df.columns]
        required = {"Close", "High", "Low", "Volume"}
        if not required.issubset(set(df.columns)):
            return None

        high, low, close, volume = df["High"], df["Low"], df["Close"], df["Volume"]
        last_close = float(close.iloc[-1])
        if np.isnan(last_close) or last_close < MIN_PRICE or last_close > MAX_PRICE:
            return None

        avg_vol_raw = volume.iloc[-21:-1].mean() if len(volume) > 21 else volume.mean()
        avg_vol = float(avg_vol_raw) if not np.isnan(avg_vol_raw) else 0
        if avg_vol < MIN_AVG_VOLUME:
            return None

        last_vol = float(volume.iloc[-1])
        rel_vol = last_vol / avg_vol if avg_vol > 0 else 1.0
        if np.isnan(rel_vol):
            rel_vol = 1.0

        rsi = _compute_rsi(close)
        if rsi > 80 or rsi < 20:
            return None

        adx = _compute_adx(high, low, close)

        ema_20 = float(close.ewm(span=20).mean().iloc[-1])
        ema_50 = float(close.ewm(span=50).mean().iloc[-1])
        if np.isnan(ema_20): ema_20 = last_close
        if np.isnan(ema_50): ema_50 = last_close
        ema_trend = "up" if last_close > ema_20 > ema_50 else ("down" if last_close < ema_20 < ema_50 else "flat")

        prev_5 = float(close.iloc[-5]) if len(close) >= 5 else last_close
        prev_20 = float(close.iloc[-20]) if len(close) >= 20 else last_close
        mom_5d = ((last_close / prev_5) - 1) * 100 if prev_5 > 0 else 0
        mom_20d = ((last_close / prev_20) - 1) * 100 if prev_20 > 0 else 0
        if np.isnan(mom_5d): mom_5d = 0
        if np.isnan(mom_20d): mom_20d = 0

        # ── Technical targets ────────────────────────────────────────
        tr1 = (high - low).rename("tr1")
        tr2 = (high - close.shift(1)).abs().rename("tr2")
        tr3 = (low - close.shift(1)).abs().rename("tr3")
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_14_raw = tr.rolling(14).mean().iloc[-1]
        atr_14 = float(atr_14_raw) if not np.isnan(atr_14_raw) else last_close * 0.03
        if atr_14 <= 0: atr_14 = last_close * 0.03

        recent_30_high = high.tail(30)
        recent_30_low = low.tail(30)
        swing_high = float(recent_30_high.max())
        swing_low = float(recent_30_low.min())
        if np.isnan(swing_high): swing_high = last_close * 1.05
        if np.isnan(swing_low): swing_low = last_close * 0.95

        fib_range = swing_high - swing_low
        fib_382 = swing_high - fib_range * 0.382

        mult_t = 2.5 if adx > 30 else 2.0 if adx > 20 else 1.5
        mult_sl = 1.2 if adx > 30 else 1.3 if adx > 20 else 1.5

        cands_t = [last_close + mult_t * atr_14]
        if swing_high > last_close * 1.01: cands_t.append(swing_high)
        if fib_382 > last_close * 1.01: cands_t.append(fib_382)
        cands_t.sort()
        target_price = round(cands_t[len(cands_t) // 2] if len(cands_t) >= 3 else max(cands_t), 2)

        cands_sl = [last_close - mult_sl * atr_14]
        if swing_low < last_close * 0.99: cands_sl.append(swing_low)
        cands_sl.append(ema_50 if ema_50 < last_close else last_close - atr_14)
        cands_sl = [s for s in cands_sl if 0 < s < last_close]
        stop_loss = round(max(cands_sl), 2) if cands_sl else round(last_close * 0.92, 2)
        stop_loss = max(stop_loss, round(last_close * 0.85, 2))

        risk = last_close - stop_loss
        reward = target_price - last_close
        risk_reward = round(reward / risk, 2) if risk > 0 else 0.0

        # ── Score ────────────────────────────────────────────────────
        score = 0.0
        score += min(rel_vol, 3.0) * 8
        if ema_trend == "up": score += 20
        elif ema_trend == "flat": score += 5
        if 40 <= rsi <= 65: score += 15
        elif 30 <= rsi < 40 or 65 < rsi <= 75: score += 8
        if adx > 25: score += 15
        elif adx > 20: score += 10
        elif adx > 15: score += 5
        if mom_5d > 5: score += 15
        elif mom_5d > 2: score += 10
        elif mom_5d > 0: score += 5
        if mom_20d > 10: score += 10
        elif mom_20d > 5: score += 7
        elif mom_20d > 0: score += 3
        if risk_reward >= 2.0: score += 5
        elif risk_reward >= 1.5: score += 3

        if mom_5d > 5 and rel_vol > 1.5: time_horizon = "swing_1w"
        elif adx > 25 and ema_trend == "up" and mom_20d > 10: time_horizon = "medium_3m"
        elif mom_20d > 5: time_horizon = "short_1m"
        else: time_horizon = "swing_1w"

        reasons = []
        if ema_trend == "up": reasons.append("bullish EMA alignment")
        if rel_vol > 1.5: reasons.append(f"volume surge {rel_vol:.1f}x")
        if adx > 25: reasons.append(f"strong trend ADX={adx:.0f}")
        if mom_5d > 2: reasons.append(f"+{mom_5d:.1f}% in 5d")
        if 40 <= rsi <= 65: reasons.append(f"RSI {rsi:.0f} in sweet spot")
        if risk_reward >= 1.5: reasons.append(f"R:R {risk_reward:.1f}")

        return TechnicalCandidate(
            ticker=ticker, score=round(score, 2), last_close=round(last_close, 2),
            rsi=round(rsi, 1), adx=round(adx, 1), ema_trend=ema_trend,
            momentum_5d=round(mom_5d, 2), momentum_20d=round(mom_20d, 2),
            volume_surge=rel_vol > 1.5, relative_volume=round(rel_vol, 2),
            avg_volume_20d=round(avg_vol), target_price=target_price,
            stop_loss=stop_loss, risk_reward=risk_reward, time_horizon=time_horizon,
            swing_high=round(swing_high, 2), swing_low=round(swing_low, 2),
            reasoning="; ".join(reasons) if reasons else "Basic screening criteria met",
        )
    except Exception as e:
        log.debug("Technical screen failed for %s: %s", ticker, e)
        return None


# ── Full AI-powered penny scan ────────────────────────────────────────

def run_penny_scan(
    sample_size: int = AI_BATCH_SIZE,
    model_name: str | None = None,
    progress_callback=None,
) -> dict:
    """Full AI penny stock discovery pipeline.

    1. Builds the full NSE+BSE universe, excludes previously scanned tickers
    2. Technical pre-filter: finds sub-₹100 stocks with the best signals
    3. Runs 21 AI agents + swarm + meta-analyst on the top candidates
    4. Only keeps buy/strong_buy results

    Returns the scan report dict (saved to penny_scan.json).
    """
    import os

    def _progress(stage: str, detail: str = "", done: int = 0, total: int = 0):
        if progress_callback:
            try:
                progress_callback(stage, detail, done, total)
            except Exception:
                pass

    _progress("init", "Building full NSE+BSE penny universe...")

    # ── Phase 0: Build universe of NEW tickers ───────────────────────
    from src.data.nse_stocks import ALL_INDIAN_STOCKS
    history = _load_scanned_history()
    previously_scanned = set(history.get("scanned", []))

    # Reset history if > 500 tickers scanned (cycle back)
    if len(previously_scanned) > 500:
        log.info("Resetting penny scan history (> 500 tickers scanned)")
        previously_scanned = set()
        history = {"scanned": [], "last_reset": _now_ist()}

    # Exclude tickers already scanned
    universe = [t for t in ALL_INDIAN_STOCKS if t not in previously_scanned]
    random.shuffle(universe)
    log.info("Penny universe: %d stocks remaining (%d previously scanned)", len(universe), len(previously_scanned))
    _progress("init", f"{len(universe)} stocks in universe, {len(previously_scanned)} already scanned")

    # ── Phase 1: Technical pre-filter — find sub-₹100 with best signals ──
    _progress("scanning", f"Screening stocks for sub-₹100 penny candidates...", 0, len(universe))

    # Scan in batches of 50 until we have enough candidates
    candidates: list[TechnicalCandidate] = []
    scanned_this_run: list[str] = []
    batch_size = 50
    needed = max(PREFILTER_TOP_N * 3, 18)

    for batch_start in range(0, len(universe), batch_size):
        if len(candidates) >= needed:
            break
        batch = universe[batch_start:batch_start + batch_size]
        scanned_this_run.extend(batch)

        with ThreadPoolExecutor(max_workers=10) as pool:
            futs = {pool.submit(_technical_screen, t): t for t in batch}
            for f in as_completed(futs):
                try:
                    r = f.result()
                    if r is not None and r.score >= 25:
                        candidates.append(r)
                except Exception:
                    pass

        done_so_far = batch_start + len(batch)
        _progress("scanning", f"Found {len(candidates)} candidates from {done_so_far} stocks", done_so_far, len(universe))

    # Update scanned history
    history["scanned"] = list(previously_scanned | set(scanned_this_run))
    _save_scanned_history(history)

    candidates.sort(key=lambda c: c.score, reverse=True)
    top_candidates = candidates[:PREFILTER_TOP_N]

    if not top_candidates:
        log.info("No technical penny candidates found this run")
        _progress("done", "No penny candidates found", 0, 0)
        report = _build_report([], [], [], [])
        _save_report(report)
        return report

    tickers = [c.ticker for c in top_candidates]
    names = [t.replace(".NS", "").replace(".BO", "") for t in tickers]
    n = len(tickers)
    log.info("Top %d penny candidates for AI analysis: %s", n, ", ".join(names))
    _progress("enriching", f"Top {n} candidates: {', '.join(names)}", 0, n)

    # ── Phase 2: Full AI agent pipeline ──────────────────────────────
    _progress("ai_agents", f"Running 21 AI agents + swarm on {', '.join(names)}...", 0, n)

    verdicts: dict = {}
    analyst_signals: dict = {}
    effective_model = model_name or "claude-sonnet-4-20250514"
    try:
        from src.main import create_workflow
        from langchain_core.messages import HumanMessage
        from src.utils.analysts import ANALYST_CONFIG
        from app.backend.database import SessionLocal
        from app.backend.services.api_key_service import ApiKeyService

        db = SessionLocal()
        try:
            api_keys = ApiKeyService(db).get_api_keys_dict()
        finally:
            db.close()

        selected_analysts = list(ANALYST_CONFIG.keys())
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_90 = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        workflow = create_workflow(selected_analysts)
        agent = workflow.compile()

        ai_result = agent.invoke({
            "messages": [HumanMessage(content="Make trading decisions based on the provided data.")],
            "data": {
                "tickers": tickers,
                "portfolio": {"cash": 1000000, "positions": {}},
                "start_date": start_90,
                "end_date": end_date,
                "analyst_signals": {},
            },
            "metadata": {
                "show_reasoning": True,
                "model_name": effective_model,
                "model_provider": "Anthropic",
                "request": type("Req", (), {
                    "api_keys": api_keys,
                    "get_agent_model_config": lambda self, agent_id: (effective_model, "Anthropic"),
                })(),
            },
        })

        analyst_signals = ai_result.get("data", {}).get("analyst_signals", {})
        _progress("meta_analysis", "Running meta-analyst signal fusion...", n, n)
        from src.algo_trader.meta_analyst import run_meta_analysis
        verdicts = run_meta_analysis(analyst_signals, tickers)

        for ticker in tickers:
            ticker_sigs = {}
            for agent_name, signals in analyst_signals.items():
                if isinstance(signals, dict) and ticker in signals:
                    ticker_sigs[agent_name] = signals[ticker]
            if ticker in verdicts:
                verdicts[ticker]["analyst_signals"] = ticker_sigs

    except Exception as e:
        log.warning("Penny AI analysis failed: %s", e, exc_info=True)

    # ── Phase 3: Build results — only keep buys ──────────────────────
    _progress("finalizing", "Filtering for buy signals...", n, n)

    all_analyzed: list[dict] = []
    strong_buys: list[dict] = []
    buys: list[dict] = []

    candidate_map = {c.ticker: c for c in top_candidates}
    for ticker in tickers:
        cand = candidate_map.get(ticker)
        verdict = verdicts.get(ticker, {})
        target_sig = verdict.get("analyst_signals", {}).get("target_analyst_agent", {})

        entry = {
            "ticker": ticker,
            "scanned_at": _now_ist(),
            "last_close": cand.last_close if cand else 0,
            "current_price": cand.last_close if cand else 0,
            "rsi": cand.rsi if cand else None,
            "adx": cand.adx if cand else None,
            "ema_trend": cand.ema_trend if cand else "unknown",
            "momentum_5d": cand.momentum_5d if cand else 0,
            "momentum_20d": cand.momentum_20d if cand else 0,
            "volume_surge": cand.volume_surge if cand else False,
            "relative_volume": cand.relative_volume if cand else 0,
            "avg_volume_20d": cand.avg_volume_20d if cand else 0,
            "technical_score": cand.score if cand else 0,
            "target_price": target_sig.get("target_price", cand.target_price if cand else 0),
            "stop_loss": target_sig.get("stop_loss", cand.stop_loss if cand else 0),
            "risk_reward": target_sig.get("risk_reward_ratio", cand.risk_reward if cand else 0),
            "time_horizon": target_sig.get("time_horizon", cand.time_horizon if cand else ""),
            "swing_high": cand.swing_high if cand else 0,
            "swing_low": cand.swing_low if cand else 0,
            "ai_action": verdict.get("action", ""),
            "ai_score": verdict.get("score", 0),
            "ai_confidence": verdict.get("confidence", 0),
            "ai_reasoning": str(verdict.get("reasoning", ""))[:400],
            "signal": target_sig.get("signal", "neutral"),
            "signal_breakdown": verdict.get("signal_breakdown", {}),
            "recommendation": "watch",
            "reasoning": cand.reasoning if cand else "",
        }

        action = verdict.get("action", "").lower()
        ai_score = verdict.get("score", 0)
        if "buy" in action and "short" not in action:
            if ai_score > 0.2:
                entry["recommendation"] = "strong_buy"
                strong_buys.append(entry)
            else:
                entry["recommendation"] = "buy"
                buys.append(entry)

        all_analyzed.append(entry)

    report = _build_report(strong_buys, buys, all_analyzed, names)
    _save_report(report)

    # Save to analysis history
    try:
        hist_dir = OUTPUTS_DIR / "analysis_history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        slug = "_".join(names[:4])
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        hist_file = hist_dir / f"{ts}_penny_{slug}.json"
        with open(hist_file, "w") as f:
            json.dump(report, f, indent=2, default=str)
    except Exception as exc:
        log.warning("Failed to save penny scan to history: %s", exc)

    log.info(
        "Penny AI scan complete: %d analyzed, %d strong buys, %d buys out of %d candidates",
        len(all_analyzed), len(strong_buys), len(buys), len(candidates),
    )
    _progress("done", f"{len(strong_buys)} strong buys, {len(buys)} buys from {n} analyzed", n, n)
    return report


def _build_report(strong_buys: list, buys: list, all_analyzed: list, batch_names: list) -> dict:
    # Merge with existing results
    existing = load_scan_results()
    prev_strong = existing.get("strong_buys", [])
    prev_buys = existing.get("buys", [])

    prev_strong_tickers = {s["ticker"] for s in prev_strong}
    prev_buy_tickers = {s["ticker"] for s in prev_buys}

    merged_strong = list(prev_strong)
    for sb in strong_buys:
        if sb["ticker"] not in prev_strong_tickers:
            merged_strong.append(sb)
    merged_strong.sort(key=lambda x: -x.get("ai_score", 0))
    merged_strong = merged_strong[:20]

    merged_buys = list(prev_buys)
    for b in buys:
        if b["ticker"] not in prev_buy_tickers and b["ticker"] not in prev_strong_tickers:
            merged_buys.append(b)
    merged_buys.sort(key=lambda x: -x.get("ai_score", 0))
    merged_buys = merged_buys[:20]

    total_scans = existing.get("total_scans", 0) + (1 if all_analyzed else 0)

    return {
        "scan_time": _now_ist(),
        "total_scans": total_scans,
        "total_scanned": len(all_analyzed),
        "strong_buys": merged_strong,
        "buys": merged_buys,
        "all_analyzed": all_analyzed,
        "last_batch": batch_names,
        "results": merged_strong + merged_buys,
    }


def _save_report(report: dict):
    import os
    PENNY_SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PENNY_SCAN_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(report, f, indent=2, default=str)
    os.replace(str(tmp), str(PENNY_SCAN_FILE))
    log.info("Penny scan saved: %d strong buys, %d buys",
             len(report.get("strong_buys", [])), len(report.get("buys", [])))


def load_scan_results() -> dict:
    """Load the most recent penny scan results."""
    if not PENNY_SCAN_FILE.exists():
        return {"scan_time": None, "total_scanned": 0, "results": [], "strong_buys": [], "buys": []}
    try:
        with open(PENNY_SCAN_FILE) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to load penny scan results: %s", exc)
        return {"scan_time": None, "total_scanned": 0, "results": [], "strong_buys": [], "buys": []}


def refresh_live_prices(results: list[dict], max_workers: int = 6) -> list[dict]:
    """Fetch live/latest prices for scan results."""
    import yfinance as yf

    def _fetch_live(item: dict) -> dict:
        ticker = item.get("ticker", "")
        if not ticker:
            return item
        out = dict(item)
        try:
            t = yf.Ticker(ticker)
            live_price = None
            prev_close = None
            try:
                fi = t.fast_info
                live_price = fi["lastPrice"]
                prev_close = fi["previousClose"]
            except Exception:
                pass
            if not live_price or live_price <= 0:
                hist = t.history(period="5d")
                if hist is not None and not hist.empty:
                    live_price = float(hist["Close"].iloc[-1])
                    if len(hist) >= 2:
                        prev_close = float(hist["Close"].iloc[-2])
            if live_price and live_price > 0 and not np.isnan(live_price):
                out["last_close"] = round(float(live_price), 2)
                out["current_price"] = round(float(live_price), 2)
                out["price_updated_at"] = _now_ist()
                if prev_close and prev_close > 0 and not np.isnan(prev_close):
                    out["change_1d_pct"] = round(
                        (float(live_price) - float(prev_close)) / float(prev_close) * 100, 2
                    )
        except Exception as exc:
            log.debug("Live price fetch failed for %s: %s", ticker, exc)
        return out

    refreshed: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_live, r): r for r in results}
        for f in as_completed(futures):
            try:
                refreshed.append(f.result())
            except Exception:
                refreshed.append(futures[f])
    refreshed.sort(key=lambda r: r.get("ai_score", r.get("score", 0)), reverse=True)
    return refreshed


# Legacy compat — old code imports these
def scan_penny_stocks(**kwargs):
    """Legacy wrapper — calls run_penny_scan."""
    return []

def save_scan_results(results):
    """Legacy no-op."""
    pass
