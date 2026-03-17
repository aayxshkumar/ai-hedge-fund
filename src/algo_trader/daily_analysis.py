"""Daily Analysis Generator — Aggregates all signals into a single daily report.

Combines:
- Meta Analyst verdicts (latest portfolio review)
- Penny scanner top picks
- Portfolio balance / rebalancing recommendations
- Target Analyst targets and time horizons
- Market overview (Nifty 50 trend)

Auto-generates at 12:30 IST (after the 12:00 analyst review completes).
Cached to outputs/daily_analysis.json.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
DAILY_FILE = Path(__file__).resolve().parent.parent.parent / "outputs" / "daily_analysis.json"
REVIEW_FILE = Path(__file__).resolve().parent.parent.parent / "outputs" / "portfolio_review.json"
DISCOVERY_FILE = Path(__file__).resolve().parent.parent.parent / "outputs" / "discovery_analysis.json"


def _now_ist() -> str:
    return datetime.now(IST).isoformat()


def _market_overview() -> dict:
    """Quick Nifty 50 trend snapshot."""
    try:
        import yfinance as yf
        t = yf.Ticker("^NSEI")
        df = t.history(period="30d")
        if df is None or len(df) < 5:
            return {"index": "NIFTY 50", "trend": "unknown"}

        df.columns = [str(c).strip().capitalize() for c in df.columns]
        if "Close" not in df.columns:
            return {"index": "NIFTY 50", "trend": "unknown"}
        close = df["Close"]

        last = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        change_1d = (last - prev) / prev * 100 if prev != 0 else 0
        prev_5d = float(close.iloc[-5]) if len(close) >= 5 else 0
        change_5d = (last - prev_5d) / prev_5d * 100 if prev_5d != 0 else 0
        ema_20 = float(close.ewm(span=20).mean().iloc[-1])
        trend = "bullish" if last > ema_20 else "bearish"

        return {
            "index": "NIFTY 50",
            "last_close": round(last, 2),
            "change_1d_pct": round(change_1d, 2),
            "change_5d_pct": round(change_5d, 2),
            "ema_20": round(ema_20, 2),
            "trend": trend,
        }
    except Exception as e:
        log.warning("Market overview failed: %s", e)
        return {"index": "NIFTY 50", "trend": "unknown"}


def _load_review_verdicts() -> dict:
    """Load the latest Meta Analyst verdicts."""
    try:
        if REVIEW_FILE.exists():
            data = json.loads(REVIEW_FILE.read_text())
            return data.get("verdicts", {})
    except Exception:
        pass
    return {}


def _extract_target_signals(verdicts: dict) -> list[dict]:
    """Pull target analyst signals from review verdicts.

    Merges the target_analyst_agent data with the meta analyst verdict
    so the UI gets a complete picture (action, score, confidence, plus target/SL).
    """
    targets = []
    for ticker, v in verdicts.items():
        sig = v.get("analyst_signals", {}).get("target_analyst_agent", {})
        if sig and sig.get("target_price"):
            targets.append({
                "ticker": ticker,
                "signal": sig.get("signal", "neutral"),
                "target_price": sig.get("target_price", 0),
                "stop_loss": sig.get("stop_loss", 0),
                "time_horizon": sig.get("time_horizon", "short_1m"),
                "risk_reward_ratio": sig.get("risk_reward_ratio", 0),
                "confidence": sig.get("confidence", 0),
                "reasoning": sig.get("reasoning", "")[:200],
                "meta_action": v.get("action", ""),
                "meta_score": v.get("score", 0),
                "meta_confidence": v.get("confidence", 0),
            })
    targets.sort(key=lambda x: -x.get("confidence", 0))
    return targets


def _summarize_verdicts(verdicts: dict) -> dict:
    """Summarize the portfolio review verdicts."""
    if not verdicts:
        return {"total": 0, "buys": 0, "sells": 0, "holds": 0, "top_buys": [], "top_sells": []}

    buys = []
    sells = []
    holds = 0
    for ticker, v in verdicts.items():
        action = v.get("action", "hold").lower()
        if "buy" in action:
            buys.append({"ticker": ticker, "score": v.get("score", 0), "confidence": v.get("confidence", 0)})
        elif "sell" in action:
            sells.append({"ticker": ticker, "score": v.get("score", 0), "confidence": v.get("confidence", 0)})
        else:
            holds += 1

    buys.sort(key=lambda x: -x["score"])
    sells.sort(key=lambda x: x["score"])

    return {
        "total": len(verdicts),
        "buys": len(buys),
        "sells": len(sells),
        "holds": holds,
        "top_buys": buys[:5],
        "top_sells": sells[:5],
    }


def _extract_strong_buys(verdicts: dict) -> list[dict]:
    """Extract stocks with strong buy / buy signals from meta analyst verdicts.

    Returns a list sorted by score (descending) with full verdict detail
    including target analyst signals if available.
    """
    strong = []
    for ticker, v in verdicts.items():
        action = v.get("action", "hold").lower()
        if "buy" not in action:
            continue
        target_sig = v.get("analyst_signals", {}).get("target_analyst_agent", {})
        strong.append({
            "ticker": ticker,
            "action": v.get("action", "buy"),
            "score": v.get("score", 0),
            "confidence": v.get("confidence", 0),
            "reasoning": str(v.get("reasoning", ""))[:250],
            "target_price": target_sig.get("target_price", 0),
            "stop_loss": target_sig.get("stop_loss", 0),
            "time_horizon": target_sig.get("time_horizon", ""),
            "risk_reward_ratio": target_sig.get("risk_reward_ratio", 0),
            "signal": target_sig.get("signal", "neutral"),
        })
    strong.sort(key=lambda x: -x["score"])
    return strong


def _extract_all_verdicts(verdicts: dict) -> list[dict]:
    """Build a flat list of ALL verdict stocks (buys, sells, holds) for the UI batch view."""
    all_v: list[dict] = []
    for ticker, v in verdicts.items():
        target_sig = v.get("analyst_signals", {}).get("target_analyst_agent", {})
        breakdown = v.get("signal_breakdown", {})
        all_v.append({
            "ticker": ticker,
            "action": v.get("action", "hold"),
            "score": v.get("score", 0),
            "confidence": v.get("confidence", 0),
            "reasoning": str(v.get("reasoning", ""))[:250],
            "target_price": target_sig.get("target_price", 0),
            "stop_loss": target_sig.get("stop_loss", 0),
            "time_horizon": target_sig.get("time_horizon", ""),
            "risk_reward_ratio": target_sig.get("risk_reward_ratio", 0),
            "bullish_pct": breakdown.get("bullish_pct", 0),
            "bearish_pct": breakdown.get("bearish_pct", 0),
            "total_agents": breakdown.get("total", 0),
        })
    all_v.sort(key=lambda x: -x["score"])
    return all_v


def _flatten_yf_columns(df) -> None:
    """Flatten yfinance MultiIndex columns in-place to simple strings."""
    import pandas as _pd
    if isinstance(df.columns, _pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).strip().capitalize() for c in df.columns]


def _enrich_stock(ticker: str) -> dict:
    """Fetch live price + key technicals for a single stock."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period="90d")
        if df is None or len(df) < 5:
            return {}

        df.columns = [str(c).strip().capitalize() for c in df.columns]
        if "Close" not in df.columns:
            return {}

        close = df["Close"]
        high = df.get("High", close)
        low = df.get("Low", close)
        volume = df.get("Volume", close * 0)

        last = float(close.iloc[-1])
        if np.isnan(last):
            return {}
        prev = float(close.iloc[-2])
        change_1d = (last - prev) / prev * 100 if prev != 0 and not np.isnan(prev) else 0

        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, min_periods=14).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, min_periods=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))
        rsi_raw = rsi_series.iloc[-1]
        rsi_val = float(rsi_raw) if not np.isnan(rsi_raw) else None

        ema50_raw = close.ewm(span=50).mean().iloc[-1]
        ema50 = float(ema50_raw) if not np.isnan(ema50_raw) else None
        ema200 = None
        if len(close) >= 200:
            ema200_raw = close.ewm(span=200).mean().iloc[-1]
            ema200 = float(ema200_raw) if not np.isnan(ema200_raw) else None
        trend = "Bullish" if ema200 and ema50 and last > ema50 > ema200 else (
            "Bearish" if ema200 and ema50 and last < ema50 < ema200 else "Neutral")

        high_52w = float(high.tail(252).max()) if len(high) >= 252 else float(high.max())
        low_52w = float(low.tail(252).min()) if len(low) >= 252 else float(low.min())

        last_30 = df.tail(30)
        mini_chart = [
            {"d": idx.strftime("%m/%d"), "c": round(float(row["Close"]), 2)}
            for idx, row in last_30.iterrows()
            if not np.isnan(row["Close"])
        ]

        avg_vol_raw = volume.iloc[-21:-1].mean() if len(volume) > 21 else volume.mean()
        avg_vol = float(avg_vol_raw) if not np.isnan(avg_vol_raw) else 0

        return {
            "current_price": round(last, 2),
            "change_1d_pct": round(change_1d, 2),
            "rsi": round(rsi_val, 1) if rsi_val is not None else None,
            "ema50": round(ema50, 2) if ema50 is not None else None,
            "ema200": round(ema200, 2) if ema200 is not None else None,
            "trend": trend,
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "avg_volume": round(avg_vol),
            "mini_chart": mini_chart,
        }
    except Exception as e:
        log.debug("Enrichment failed for %s: %s", ticker, e)
        return {}


def generate_daily_analysis() -> dict:
    """Generate the full daily analysis report.

    Penny picks are handled separately (via /penny-scanner/results).
    This report focuses on the AI-reviewed portfolio: strong buys,
    target signals, all verdicts, portfolio balance, and market overview.
    """
    log.info("Generating daily analysis report...")

    market = _market_overview()
    verdicts = _load_review_verdicts()
    verdict_summary = _summarize_verdicts(verdicts)
    target_signals = _extract_target_signals(verdicts)
    strong_buys = _extract_strong_buys(verdicts)
    all_verdicts = _extract_all_verdicts(verdicts)

    from src.algo_trader.portfolio_balancer import load_rebalance_analysis
    rebalance = load_rebalance_analysis()

    short_term_picks = rebalance.get("short_term_picks", [])

    all_tickers = {v.get("ticker", "") for v in all_verdicts}
    for p in short_term_picks[:5]:
        all_tickers.add(p.get("ticker", ""))
    all_tickers.discard("")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    enriched: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_enrich_stock, t): t for t in all_tickers}
        for f in as_completed(futs):
            t = futs[f]
            try:
                data = f.result()
                if data:
                    enriched[t] = data
            except Exception:
                pass

    for t in target_signals:
        tk = t.get("ticker", "")
        t["enriched"] = enriched.get(tk, {})

    for p in short_term_picks:
        tk = p.get("ticker", "")
        info = enriched.get(tk, {})
        if info.get("current_price") and not p.get("price"):
            p["price"] = info["current_price"]
        p["enriched"] = info

    for sb in strong_buys:
        tk = sb.get("ticker", "")
        info = enriched.get(tk, {})
        if info.get("current_price"):
            sb["current_price"] = info["current_price"]
            sb["change_1d_pct"] = info.get("change_1d_pct", 0)
        sb["enriched"] = info

    for v in all_verdicts:
        tk = v.get("ticker", "")
        info = enriched.get(tk, {})
        if info.get("current_price"):
            v["current_price"] = info["current_price"]
            v["change_1d_pct"] = info.get("change_1d_pct", 0)
            v["change_5d_pct"] = info.get("change_5d_pct", 0)

    batch_tickers = [v["ticker"] for v in all_verdicts if v.get("ticker")]

    report = {
        "generated_at": _now_ist(),
        "market_overview": market,
        "verdict_summary": verdict_summary,
        "strong_buys": strong_buys[:10],
        "target_signals": target_signals[:10],
        "all_verdicts": all_verdicts,
        "batch_tickers": batch_tickers,
        "portfolio_balance": {
            "current_allocation": rebalance.get("current_allocation", {}),
            "recommended_profile": rebalance.get("recommended_profile", "balanced"),
            "recommended_allocation": rebalance.get("recommended_allocation", {}),
            "suggestions": rebalance.get("suggestions", []),
            "short_term_picks": short_term_picks[:5],
        },
    }

    import os
    DAILY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DAILY_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(report, f, indent=2, default=str)
    os.replace(str(tmp), str(DAILY_FILE))

    _save_daily_history(report)
    log.info("Daily analysis saved to %s", DAILY_FILE)
    return report


def _save_daily_history(report: dict) -> None:
    """Persist the daily analysis to analysis_history/ for the Analysis Library."""
    import os
    from datetime import datetime as _dt

    hist_dir = DAILY_FILE.parent / "analysis_history"
    hist_dir.mkdir(parents=True, exist_ok=True)

    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    tickers = report.get("batch_tickers", [])
    slug = "_".join(t.replace(".NS", "").replace(".BO", "") for t in tickers[:4])
    fname = f"{ts}_daily_{slug}.json"

    history_entry = {
        "type": "daily",
        "generated_at": report.get("generated_at"),
        "timestamp": report.get("generated_at"),
        "tickers": tickers,
        "market_overview": report.get("market_overview"),
        "verdict_summary": report.get("verdict_summary"),
        "strong_buys": report.get("strong_buys", []),
        "all_verdicts": report.get("all_verdicts", []),
        "portfolio_balance": report.get("portfolio_balance"),
    }

    tmp = hist_dir / f".{fname}.tmp"
    with open(tmp, "w") as f:
        json.dump(history_entry, f, indent=2, default=str)
    os.replace(str(tmp), str(hist_dir / fname))


def load_daily_analysis() -> dict:
    """Load the latest daily analysis from cache."""
    if not DAILY_FILE.exists():
        return {}
    try:
        with open(DAILY_FILE) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to load daily analysis: %s", exc)
        return {}


def run_discovery_scan(
    exclude_tickers: list[str] | None = None,
    sample_size: int = 4,
    model_name: str | None = None,
    progress_callback=None,
) -> dict:
    """Run full AI swarm + meta analyst discovery on random stocks.

    Picks *sample_size* random stocks, runs ALL 21 agents + swarm + meta
    analyst, and keeps only strong buys. Results accumulate across runs
    so the strong-buy list grows over time.

    ``progress_callback(stage, detail, stocks_done, stocks_total)`` is
    called at each major step so callers can relay progress to the UI.
    """
    import random
    import os
    from src.data.nse_stocks import NIFTY_50, NIFTY_NEXT_50, NIFTY_MIDCAP_150

    def _progress(stage: str, detail: str = "", done: int = 0, total: int = 0):
        if progress_callback:
            try:
                progress_callback(stage, detail, done, total)
            except Exception:
                pass

    log.info("Running market discovery scan (%d stocks)...", sample_size)
    _progress("init", "Building stock universe...")

    exclude = {t.upper().replace(".NS", "").replace(".BO", "") for t in (exclude_tickers or [])}

    existing = load_discovery_results()
    for s in existing.get("strong_buys", []):
        tk = s.get("ticker", "").upper().replace(".NS", "").replace(".BO", "")
        if tk:
            exclude.add(tk)

    universe = [t for t in NIFTY_50 + NIFTY_NEXT_50 + NIFTY_MIDCAP_150 if t.upper() not in exclude]
    n = min(sample_size, len(universe))
    if n == 0:
        log.info("No new stocks to discover — universe exhausted")
        return existing or {"generated_at": _now_ist(), "strong_buys": [], "all_analyzed": [], "total_scans": 0}

    picked = random.sample(universe, n)
    tickers = [f"{t}.NS" for t in picked]
    names = [t.replace('.NS', '') for t in tickers]
    log.info("Discovery tickers: %s", ", ".join(names))
    _progress("enriching", f"Fetching technicals for {', '.join(names)}", 0, n)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    enriched: dict[str, dict] = {}
    done_count = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_enrich_stock, t): t for t in tickers}
        for f in as_completed(futs):
            t = futs[f]
            try:
                data = f.result()
                if data:
                    enriched[t] = data
            except Exception:
                pass
            done_count += 1
            _progress("enriching", f"Enriched {t.replace('.NS', '')} ({done_count}/{n})", done_count, n)

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
        log.warning("Discovery AI analysis failed: %s", e)

    _progress("finalizing", "Building results and saving...", n, n)
    new_analyzed: list[dict] = []
    new_strong_buys: list[dict] = []
    new_buys: list[dict] = []
    for ticker in tickers:
        info = enriched.get(ticker, {})
        verdict = verdicts.get(ticker, {})
        target_sig = verdict.get("analyst_signals", {}).get("target_analyst_agent", {})
        per_agent = {}
        for agent_name, sig_data in verdict.get("analyst_signals", {}).items():
            if isinstance(sig_data, dict):
                per_agent[agent_name] = {
                    "signal": sig_data.get("signal", "neutral"),
                    "confidence": sig_data.get("confidence", 0),
                    "reasoning": str(sig_data.get("reasoning", ""))[:200],
                }

        entry = {
            "ticker": ticker,
            "discovered_at": _now_ist(),
            "current_price": info.get("current_price"),
            "change_1d_pct": info.get("change_1d_pct"),
            "rsi": info.get("rsi"),
            "trend": info.get("trend"),
            "ema50": info.get("ema50"),
            "ema200": info.get("ema200"),
            "high_52w": info.get("high_52w"),
            "low_52w": info.get("low_52w"),
            "action": verdict.get("action", ""),
            "score": verdict.get("score", 0),
            "confidence": verdict.get("confidence", 0),
            "reasoning": str(verdict.get("reasoning", ""))[:300],
            "target_price": target_sig.get("target_price", 0),
            "stop_loss": target_sig.get("stop_loss", 0),
            "time_horizon": target_sig.get("time_horizon", ""),
            "risk_reward_ratio": target_sig.get("risk_reward_ratio", 0),
            "signal": target_sig.get("signal", "neutral"),
            "signal_breakdown": verdict.get("signal_breakdown", {}),
            "analyst_signals": per_agent,
        }
        new_analyzed.append(entry)

        action = verdict.get("action", "").lower()
        score = verdict.get("score", 0)
        if "buy" in action:
            if score > 0.2:
                new_strong_buys.append(entry)
            else:
                new_buys.append(entry)

    # ── Live file: accumulate across hourly runs ──
    prev_strong = existing.get("strong_buys", [])
    prev_strong_tickers = {s["ticker"] for s in prev_strong}
    merged_strong = list(prev_strong)
    for sb in new_strong_buys:
        if sb["ticker"] not in prev_strong_tickers:
            merged_strong.append(sb)
    merged_strong.sort(key=lambda x: -x.get("score", 0))
    merged_strong = merged_strong[:20]

    prev_buys = existing.get("buys", [])
    prev_buy_tickers = {s["ticker"] for s in prev_buys}
    merged_buys = list(prev_buys)
    for b in new_buys:
        if b["ticker"] not in prev_buy_tickers and b["ticker"] not in prev_strong_tickers:
            merged_buys.append(b)
    merged_buys.sort(key=lambda x: -x.get("score", 0))
    merged_buys = merged_buys[:20]

    prev_all = existing.get("all_analyzed", [])
    merged_all = new_analyzed + prev_all
    merged_all = merged_all[:50]

    total_scans = existing.get("total_scans", 0) + 1

    live_report = {
        "generated_at": _now_ist(),
        "strong_buys": merged_strong,
        "buys": merged_buys,
        "all_analyzed": merged_all,
        "total_scans": total_scans,
        "last_batch": [t.replace(".NS", "") for t in tickers],
    }

    DISCOVERY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DISCOVERY_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(live_report, f, indent=2, default=str)
    os.replace(str(tmp), str(DISCOVERY_FILE))

    # ── History file: only THIS run's stocks ──
    batch_report = {
        "generated_at": _now_ist(),
        "strong_buys": new_strong_buys,
        "buys": new_buys,
        "all_analyzed": new_analyzed,
        "total_scans": 1,
        "last_batch": [t.replace(".NS", "") for t in tickers],
    }
    try:
        history_dir = DAILY_FILE.parent / "analysis_history"
        history_dir.mkdir(parents=True, exist_ok=True)
        slug = "_".join(t.replace(".NS", "") for t in tickers[:4])
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        hist_file = history_dir / f"{ts}_discovery_{slug}.json"
        with open(hist_file, "w") as f:
            json.dump(batch_report, f, indent=2, default=str)
    except Exception as exc:
        log.warning("Failed to save discovery to history: %s", exc)

    log.info(
        "Discovery complete: %d analyzed, %d strong buys, %d buys",
        len(tickers), len(new_strong_buys), len(new_buys),
    )
    return live_report


def load_discovery_results() -> dict:
    """Load the latest discovery analysis from cache."""
    if not DISCOVERY_FILE.exists():
        return {}
    try:
        with open(DISCOVERY_FILE) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to load discovery results: %s", exc)
        return {}
