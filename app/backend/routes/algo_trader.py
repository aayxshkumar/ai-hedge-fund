"""Auto-trading dashboard routes — REST + SSE for the algo trader lifecycle.

Shared state lives in ``algo_state.py``.  New route groups can be extracted
into separate modules that import from there.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import pandas as pd

from src.algo_trader.hermes_bridge import (
    log_trade, log_analyst_review, log_scan_results, log_daily_digest,
    log_action, log_penny_scan, log_daily_analysis, log_rebalance,
)
from src.algo_trader.review_differ import (
    save_review_snapshot, load_previous_review, diff_reviews,
    list_snapshots, load_snapshot_by_filename,
)

from app.backend.routes.algo_state import (
    state as _state,
    get_meta_verdict as _get_meta_verdict,
    is_market_hours as _is_market_hours,
    IST, SCAN_INTERVAL_MINUTES,
    ConfigUpdate, RunCycleRequest, ScreenRequest,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/algo-trader", tags=["algo-trader"])


# ── Background trader loop ───────────────────────────────────────────

def _run_daily_screen() -> list[str]:
    """Run the screener once per day to refresh the watchlist with top candidates.

    Uses a hard timeout — if the screener hangs, falls back to current watchlist.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
    from src.algo_trader.screener import screen_stocks
    from src.data.nse_stocks import NIFTY_50

    tickers = [f"{s}.NS" for s in NIFTY_50]

    def _do_screen():
        return screen_stocks(tickers, top_n=15, max_workers=10)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_screen)
            results = future.result(timeout=120)
        screened = [r.ticker for r in results]
        return screened if screened else _state.config.watchlist
    except (FutTimeout, Exception) as e:
        log.warning("Daily screen timed out or failed (%s), using current watchlist", e)
        return _state.config.watchlist


def _pre_trade_filter(tickers: list[str]) -> list[str]:
    """Filter tickers through volume, volatility, ADX, and candle gates (parallel).

    Only stocks passing all gates are sent to the decision engine, reducing
    noise and ensuring we only trade liquid, trending instruments.
    """
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.algo_trader.strategies.candle_patterns import detect_patterns

    def _check_single(ticker: str) -> str | None:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.history(period="40d")
            if df is None or len(df) < 22:
                return None

            df.columns = [str(c).strip().capitalize() for c in df.columns]
            high = df["High"]
            low = df["Low"]
            close = df["Close"]
            volume = df["Volume"]

            avg_vol = float(volume.iloc[-21:-1].mean())
            if avg_vol < 100_000:
                return None
            rel_vol = float(volume.iloc[-1]) / avg_vol if avg_vol > 0 else 0
            if rel_vol < 1.0:
                return None

            returns = close.pct_change().dropna()
            vol = float(returns.iloc[-20:].std() * np.sqrt(252))
            if vol < 0.12 or vol > 0.85:
                return None

            plus_dm = high.diff()
            minus_dm = -low.diff()
            plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
            minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
            tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
            atr_s = tr.rolling(14).mean()
            plus_di = 100 * (plus_dm.rolling(14).mean() / atr_s)
            minus_di = 100 * (minus_dm.rolling(14).mean() / atr_s)
            dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
            adx = float(dx.rolling(14).mean().iloc[-1])
            if np.isnan(adx) or adx < 18:
                return None

            candle = detect_patterns(df, lookback=5)
            if candle.bias == "bearish" and candle.strength > 0.7:
                return None

            return ticker
        except Exception:
            return None

    qualified: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_check_single, t): t for t in tickers}
        for future in as_completed(futures, timeout=90):
            try:
                result = future.result(timeout=20)
                if result:
                    qualified.append(result)
            except Exception:
                pass

    return qualified


def _morning_portfolio_pull():
    """Pull portfolio from Zerodha at market open and log holdings."""
    try:
        holdings = _state.executor.get_holdings()
        positions = _state.executor.get_positions()
        funds = _state.executor.get_funds()

        tickers = set(_state.config.watchlist)
        for h in holdings:
            if h.ticker and h.quantity > 0:
                tickers.add(f"{h.ticker}.NS")
        for p in positions:
            if p.ticker and p.quantity != 0:
                tickers.add(f"{p.ticker}.NS")

        if tickers != set(_state.config.watchlist):
            _state.config.watchlist = sorted(tickers)

        cash = funds.get("available_cash", 0)
        n_hold = len([h for h in holdings if h.quantity > 0])
        n_pos = len([p for p in positions if p.quantity != 0])
        _state.push_event({
            "type": "portfolio",
            "msg": f"Morning pull — ₹{cash:,.0f} cash, {n_hold} holdings, {n_pos} positions, {len(_state.config.watchlist)} in watchlist",
        })
    except Exception as e:
        _state.push_event({"type": "error", "msg": f"Morning portfolio pull failed: {e}"})


def _trader_loop():
    """Background thread that periodically runs analysis cycles with pre-trade screening."""
    from src.algo_trader.runner import AlgoTrader
    import pandas as pd

    global _current_session_plan
    trader = AlgoTrader(_state.config)
    trader.paper_trader = _state.paper_trader
    trader.tradebook = _state.tradebook
    _state.push_event({"type": "status", "msg": "Trader loop started"})

    # Pre-session: Hermes generates session plan
    try:
        plan = trader.pre_session(tradebook=_state.tradebook)
        if plan:
            _current_session_plan = plan.to_dict() if hasattr(plan, "to_dict") else plan
            _state.push_event({"type": "session_plan", "msg": f"Hermes session plan: {len(plan.strategy_weights)} strategies"})
    except Exception as e:
        log.warning("Pre-session plan failed: %s", e)

    last_screen_date: str | None = None
    morning_pull_done: str | None = None

    while not _state.stop_event.is_set():
        now_ist = datetime.now(IST)
        hour, minute = now_ist.hour, now_ist.minute
        current_minutes = hour * 60 + minute
        today_str = now_ist.strftime("%Y-%m-%d")

        if now_ist.weekday() >= 5:
            _state.push_event({"type": "info", "msg": "Weekend — sleeping 1h"})
            _state.stop_event.wait(3600)
            continue

        market_open = 9 * 60 + 15
        market_close = 15 * 60 + 30

        # Morning portfolio pull (9:00 IST, before market open)
        if current_minutes >= market_open - 15 and morning_pull_done != today_str:
            _state.push_event({"type": "portfolio", "msg": "Running morning portfolio pull..."})
            _morning_portfolio_pull()
            morning_pull_done = today_str

        if current_minutes < market_open - 15:
            wait = max((market_open - 15 - current_minutes) * 60, 60)
            _state.push_event({"type": "info", "msg": f"Pre-market in {wait // 60}m"})
            _state.stop_event.wait(min(wait, 300))
            continue

        if current_minutes > market_close + 5:
            _state.push_event({"type": "info", "msg": "Market closed — sleeping until tomorrow"})
            _state.stop_event.wait(3600)
            continue

        try:
            # ── Daily screener (runs once per day, non-blocking) ────────
            if last_screen_date != today_str:
                _state.push_event({"type": "screener", "msg": "Running daily stock screener (background)..."})
                try:
                    import signal as _signal

                    class _ScreenTimeout(Exception):
                        pass

                    def _alarm_handler(signum, frame):
                        raise _ScreenTimeout("Screener timed out")

                    old_handler = _signal.signal(_signal.SIGALRM, _alarm_handler)
                    _signal.alarm(90)
                    try:
                        screened = _run_daily_screen()
                        _signal.alarm(0)
                        if screened:
                            _state.config.watchlist = screened
                            _state.push_event({"type": "screener", "msg": f"Watchlist updated: {len(screened)} stocks — {', '.join(s.replace('.NS','') for s in screened[:5])}..."})
                    except _ScreenTimeout:
                        _state.push_event({"type": "screener", "msg": "Screener timed out (90s) — using current watchlist"})
                        log.warning("Daily screener timed out, proceeding with current watchlist")
                    finally:
                        _signal.signal(_signal.SIGALRM, old_handler)
                        _signal.alarm(0)
                except Exception as e:
                    _state.push_event({"type": "screener", "msg": f"Screener skipped: {e}"})
                    log.warning("Screener error: %s", e)
                last_screen_date = today_str

            # ── Pre-trade filter (parallel, with timeout) ─────────────
            _state.push_event({"type": "cycle_start", "msg": f"Pre-trade filter on {len(_state.config.watchlist)} stocks at {now_ist.strftime('%H:%M')} IST"})
            qualified = _pre_trade_filter(_state.config.watchlist)

            if not qualified:
                _state.push_event({"type": "info", "msg": "No stocks passed pre-trade filters — skipping cycle"})
            else:
                _state.push_event({"type": "cycle_start", "msg": f"{len(qualified)} stocks qualified — running analysis"})
                original_wl = trader.config.watchlist
                trader.config.watchlist = qualified
                actions = trader.run_cycle()
                trader.config.watchlist = original_wl
                _state.last_cycle_time = now_ist.isoformat()

                for a in (actions or []):
                    entry = {
                        **a,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "result_msg": a.get("result").message if a.get("result") else "",
                        "result_ok": a.get("result").success if a.get("result") else False,
                    }
                    _state.execution_log.append(entry)

                    result_obj = a.get("result")
                    meta_v = _get_meta_verdict(a.get("ticker", ""))
                    _state.tradebook.record_trade({
                        "ticker": a.get("ticker", ""),
                        "action": a.get("action", "hold"),
                        "side": "BUY" if "buy" in str(a.get("action", "")).lower() else "SELL",
                        "quantity": a.get("quantity", 0),
                        "price": a.get("price", 0),
                        "mode": "paper" if _state.config.broker.read_only else "live",
                        "confidence": a.get("confidence", 0),
                        "decision_score": a.get("score", 0),
                        "reasoning": a.get("reasoning", ""),
                        "strategy_scores": a.get("strategy_scores", {}),
                        "analyst_signals": a.get("analyst_signals", {}),
                        "rsi": a.get("rsi"),
                        "macd": a.get("macd"),
                        "trend": a.get("trend"),
                        "volatility": a.get("volatility"),
                        "order_id": result_obj.order_id if result_obj and hasattr(result_obj, "order_id") else None,
                        "executed": result_obj.success if result_obj else False,
                        "execution_price": a.get("price", 0),
                        "execution_msg": result_obj.message if result_obj else "",
                        "model_name": _state.config.model_name,
                        "source": "auto_trader",
                        "instrument_type": a.get("instrument_type", "equity"),
                        "strategy_name": a.get("strategy_name", ""),
                        "legs": a.get("legs", []),
                    })

                    log_trade({
                        "ticker": a.get("ticker", ""), "action": a.get("action", "hold"),
                        "quantity": a.get("quantity", 0), "price": a.get("price", 0),
                        "confidence": a.get("confidence", 0), "reasoning": a.get("reasoning", ""),
                        "mode": "paper" if _state.config.broker.read_only else "live",
                        "executed": result_obj.success if result_obj else False,
                        "meta_verdict": _get_meta_verdict(a.get("ticker", "")),
                    })

                    if _state.config.broker.read_only and a.get("action") in ("buy", "sell"):
                        ticker = a.get("ticker", "")
                        qty = a.get("quantity", 0)
                        if a["action"] == "buy" and qty > 0:
                            _state.paper_trader.execute_buy(ticker, qty)
                        elif a["action"] == "sell" and qty > 0:
                            _state.paper_trader.execute_sell(ticker, qty)

                paper_summary = ""
                if _state.config.broker.read_only:
                    ps = _state.paper_trader.get_summary()
                    paper_summary = f" | Paper P&L: {ps['total_pnl']:+.0f} ({ps['total_return_pct']:+.1f}%)"

                _state.push_event({"type": "cycle_done", "msg": f"Cycle complete — {len(actions or [])} actions on {len(qualified)} qualified stocks{paper_summary}"})
        except Exception as e:
            log.error("Trader cycle error: %s", e, exc_info=True)
            _state.push_event({"type": "error", "msg": str(e)})

        interval = _state.config.scheduler.analysis_interval_minutes * 60
        _state.stop_event.wait(interval)

    # Post-session: Hermes reviews and writes lessons
    try:
        trader.post_session(tradebook=_state.tradebook)
        _state.push_event({"type": "session_review", "msg": "Post-session review completed"})
    except Exception as e:
        log.warning("Post-session review failed: %s", e)

    _state.push_event({"type": "status", "msg": "Trader loop stopped"})


# ── Live Scanner Loop ────────────────────────────────────────────────

def _scanner_loop():
    """Background thread: runs stock screener every SCAN_INTERVAL_MINUTES during market hours."""
    from src.algo_trader.screener import screen_stocks
    from src.data.nse_stocks import NIFTY_50

    log.info("Live scanner started (every %d min during market hours)", SCAN_INTERVAL_MINUTES)
    _state.push_event({"type": "scanner", "msg": "Live scanner started"})

    while not _state.scanner_stop.is_set():
        now_ist = datetime.now(IST)
        if _is_market_hours(now_ist):
            _state.push_event({"type": "scanner", "msg": "Running scheduled scan..."})
            try:
                tickers = [f"{s}.NS" for s in NIFTY_50]
                results = screen_stocks(tickers, top_n=20, max_workers=10)
                scan_rows = []
                for r in results:
                    scan_rows.append({
                        "ticker": r.ticker,
                        "score": round(r.score, 2),
                        "avg_volume": r.avg_volume_20d,
                        "volatility": round(r.volatility_20d * 100, 2),
                        "adx": round(r.adx, 1) if r.adx else None,
                        "sentiment": r.sentiment_score,
                        "trend": r.trend,
                        "last_close": round(r.last_close, 2) if r.last_close else None,
                    })
                _state.last_scan_results = scan_rows
                _state.last_scan_time = now_ist.isoformat()
                log_scan_results(scan_rows)

                screened_tickers = [r.ticker for r in results]
                if screened_tickers:
                    combined = list(set(_state.config.watchlist) | set(screened_tickers[:10]))
                    _state.config.watchlist = sorted(combined)

                _state.push_event({
                    "type": "scanner",
                    "msg": f"Scan done — {len(results)} stocks qualify. Watchlist: {len(_state.config.watchlist)}",
                    "count": len(results),
                })
            except Exception as e:
                log.error("Scanner error: %s", e, exc_info=True)
                _state.push_event({"type": "scanner_error", "msg": str(e)})
        else:
            _state.push_event({"type": "scanner", "msg": "Market closed — scanner idle"})

        _state.scanner_stop.wait(SCAN_INTERVAL_MINUTES * 60)

    _state.push_event({"type": "scanner", "msg": "Live scanner stopped"})


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    now_ist = datetime.now(IST)
    hour, minute = now_ist.hour, now_ist.minute
    current_minutes = hour * 60 + minute
    market_open = 9 * 60 + 15
    market_close = 15 * 60 + 30
    is_market_hours = market_open <= current_minutes <= market_close and now_ist.weekday() < 5

    zerodha = _state.zerodha_status()

    paper = _state.paper_trader.get_summary()

    return {
        "running": _state.running,
        "mode": "paper" if _state.config.broker.read_only else "live",
        "is_market_hours": is_market_hours,
        "current_time_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S"),
        "last_cycle": _state.last_cycle_time,
        "zerodha": zerodha,
        "watchlist": _state.config.watchlist,
        "model_name": _state.config.model_name,
        "read_only": _state.config.broker.read_only,
        "auto_trade": not _state.config.risk.require_confirmation,
        "scanner_running": _state.scanner_running,
        "paper_portfolio": paper,
    }


@router.post("/start")
async def start_trader():
    with _state._lifecycle_lock:
        if _state.running:
            raise HTTPException(400, "Trader is already running")
        _state.running = True
        _state.stop_event.clear()
        _state.thread = threading.Thread(target=_trader_loop, daemon=True)
        _state.thread.start()
    return {"message": "Trader started", "mode": _state.mode}


@router.post("/stop")
async def stop_trader():
    with _state._lifecycle_lock:
        if not _state.running:
            raise HTTPException(400, "Trader is not running")
        _state.stop_event.set()
        _state.running = False
    return {"message": "Trader stop signal sent"}


@router.get("/portfolio")
async def get_portfolio():
    loop = asyncio.get_running_loop()
    try:
        holdings = await loop.run_in_executor(None, _state.executor.get_holdings)
        positions = await loop.run_in_executor(None, _state.executor.get_positions)
        funds = await loop.run_in_executor(None, _state.executor.get_funds)

        holdings_data = [
            {"ticker": h.ticker, "quantity": h.quantity, "avg_price": h.average_price,
             "last_price": h.last_price, "pnl": h.pnl}
            for h in holdings
        ]
        positions_data = [
            {"ticker": p.ticker, "quantity": p.quantity, "avg_price": p.average_price,
             "last_price": p.last_price, "pnl": p.pnl, "product": p.product}
            for p in positions if p.quantity != 0
        ]

        total_value = funds.get("available_cash", 0) + sum(abs(p.quantity) * p.last_price for p in positions)
        total_value += sum(h.quantity * h.last_price for h in holdings)

        return {
            "holdings": holdings_data,
            "positions": positions_data,
            "funds": funds,
            "total_value": total_value,
            "day_pnl": sum(p.pnl for p in positions) + sum(h.pnl for h in holdings),
        }
    except Exception as e:
        return {
            "holdings": [],
            "positions": [],
            "funds": {"available_cash": 0, "used_margin": 0},
            "total_value": 0,
            "day_pnl": 0,
            "error": str(e),
        }


@router.get("/signals")
async def get_signals():
    return {"signals": _state.signals[-50:]}


@router.post("/sync-portfolio")
async def sync_portfolio_to_watchlist():
    """Pull holdings/positions from Zerodha and add them to the watchlist."""
    loop = asyncio.get_running_loop()
    try:
        holdings = await loop.run_in_executor(None, _state.executor.get_holdings)
        positions = await loop.run_in_executor(None, _state.executor.get_positions)

        tickers = set(_state.config.watchlist)
        for h in holdings:
            if h.ticker and h.quantity > 0:
                sym = f"{h.ticker}.NS"
                tickers.add(sym)
        for p in positions:
            if p.ticker and p.quantity != 0:
                sym = f"{p.ticker}.NS"
                tickers.add(sym)

        _state.config.watchlist = sorted(tickers)
        _state.push_event({"type": "config_update", "msg": f"Portfolio synced — watchlist now {len(_state.config.watchlist)} stocks"})
        return {
            "message": f"Synced {len(holdings)} holdings + {len(positions)} positions",
            "watchlist": _state.config.watchlist,
            "holdings_count": len(holdings),
            "positions_count": len(positions),
        }
    except Exception as e:
        return {"message": f"Sync failed: {e}", "watchlist": _state.config.watchlist}


def _safe_float(v, default=0) -> float:
    """Convert to float, replacing NaN/Inf with default."""
    import math
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


@router.get("/portfolio/detailed")
async def get_portfolio_with_analysis():
    """Return portfolio holdings with per-stock technical analysis and fundamentals."""
    import yfinance as yf
    import numpy as np
    from datetime import datetime, timedelta
    from fastapi.responses import JSONResponse
    import json as _json

    loop = asyncio.get_running_loop()

    try:
        holdings = await loop.run_in_executor(None, _state.executor.get_holdings)
        positions = await loop.run_in_executor(None, _state.executor.get_positions)
        funds = await loop.run_in_executor(None, _state.executor.get_funds)
    except Exception:
        holdings, positions, funds = [], [], {"available_cash": 0, "used_margin": 0}

    cash = funds.get("available_cash", 0)
    used_margin = funds.get("used_margin", 0)

    stocks: list[dict] = []
    all_tickers: list[str] = []

    for h in holdings:
        if h.quantity > 0:
            sym = f"{h.ticker}.NS" if not h.ticker.endswith((".NS", ".BO")) else h.ticker
            all_tickers.append(sym)
            invested = h.average_price * h.quantity
            current = h.last_price * h.quantity
            stocks.append({
                "ticker": h.ticker,
                "yf_ticker": sym,
                "type": "holding",
                "quantity": h.quantity,
                "avg_price": h.average_price,
                "last_price": h.last_price,
                "invested_value": round(invested, 2),
                "current_value": round(current, 2),
                "pnl": round(h.pnl, 2),
                "pnl_pct": round(((current / invested) - 1) * 100, 2) if invested > 0 else 0,
                "day_pnl": round(h.pnl, 2),
            })
    for p in positions:
        if p.quantity != 0:
            sym = f"{p.ticker}.NS" if not p.ticker.endswith((".NS", ".BO")) else p.ticker
            if sym not in all_tickers:
                all_tickers.append(sym)
            invested = abs(p.average_price * p.quantity)
            current = abs(p.last_price * p.quantity)
            stocks.append({
                "ticker": p.ticker,
                "yf_ticker": sym,
                "type": "position",
                "product": p.product,
                "quantity": p.quantity,
                "avg_price": p.average_price,
                "last_price": p.last_price,
                "invested_value": round(invested, 2),
                "current_value": round(current, 2),
                "pnl": round(p.pnl, 2),
                "pnl_pct": round(((current / invested) - 1) * 100, 2) if invested > 0 else 0,
            })

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    _fetch_sem = asyncio.Semaphore(8)

    async def _enrich_stock(stock: dict):
        sym = stock["yf_ticker"]
        async with _fetch_sem:
            try:
                df = await loop.run_in_executor(
                    None, lambda s=sym: yf.Ticker(s).history(start=start_date, end=end_date)
                )
                if df is not None and not df.empty:
                    df.columns = [str(c).strip().capitalize() for c in df.columns]

                    close = df["Close"]
                    high = df["High"]
                    low = df["Low"]

                    delta = close.diff()
                    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
                    rs = gain / loss.replace(0, np.nan)
                    rsi = 100 - (100 / (1 + rs))

                    ema50 = close.ewm(span=50).mean()
                    ema200 = close.ewm(span=200).mean()

                    ema12 = close.ewm(span=12).mean()
                    ema26 = close.ewm(span=26).mean()
                    macd_line = ema12 - ema26
                    signal_line = macd_line.ewm(span=9).mean()

                    bb_mid = close.rolling(20).mean()
                    bb_std = close.rolling(20).std()
                    bb_upper = bb_mid + 2 * bb_std
                    bb_lower = bb_mid - 2 * bb_std

                    returns = close.pct_change().dropna()
                    vol = _safe_float(returns.std() * np.sqrt(252))
                    max_dd = _safe_float(((close / close.cummax()) - 1).min())

                    high_52w = _safe_float(high.tail(252).max()) if len(high) >= 252 else _safe_float(high.max())
                    low_52w = _safe_float(low.tail(252).min()) if len(low) >= 252 else _safe_float(low.min())

                    trend = "Bullish" if len(ema50) > 0 and len(ema200) > 0 and float(ema50.iloc[-1]) > float(ema200.iloc[-1]) else "Bearish"

                    last_30 = df.tail(30)
                    mini_chart = [{"d": idx.strftime("%m/%d"), "c": round(_safe_float(row["Close"]), 2)} for idx, row in last_30.iterrows()]

                    stock["analysis"] = {
                        "rsi": round(rv, 1) if (rv := _safe_float(rsi.iloc[-1] if len(rsi) > 0 else 0)) > 0 else None,
                        "macd": round(_safe_float(macd_line.iloc[-1]), 2),
                        "macd_signal": round(_safe_float(signal_line.iloc[-1]), 2),
                        "ema50": round(_safe_float(ema50.iloc[-1]), 2),
                        "ema200": round(_safe_float(ema200.iloc[-1]), 2),
                        "bb_upper": round(_safe_float(bb_upper.iloc[-1]), 2),
                        "bb_lower": round(_safe_float(bb_lower.iloc[-1]), 2),
                        "trend": trend,
                        "volatility": round(_safe_float(vol * 100), 1),
                        "max_drawdown": round(_safe_float(max_dd * 100), 1),
                        "high_52w": round(_safe_float(high_52w), 2),
                        "low_52w": round(_safe_float(low_52w), 2),
                    }
                    stock["mini_chart"] = mini_chart

                    rsi_val = stock["analysis"]["rsi"]
                    macd_val = stock["analysis"]["macd"]
                    macd_sig = stock["analysis"]["macd_signal"]
                    if rsi_val and rsi_val < 30 and macd_val > macd_sig:
                        stock["signal"] = "Strong Buy"
                        stock["signal_color"] = "emerald"
                    elif rsi_val and rsi_val < 40 and trend == "Bullish":
                        stock["signal"] = "Buy"
                        stock["signal_color"] = "green"
                    elif rsi_val and rsi_val > 70 and macd_val < macd_sig:
                        stock["signal"] = "Strong Sell"
                        stock["signal_color"] = "red"
                    elif rsi_val and rsi_val > 60 and trend == "Bearish":
                        stock["signal"] = "Sell"
                        stock["signal_color"] = "orange"
                    else:
                        stock["signal"] = "Hold"
                        stock["signal_color"] = "gray"
                else:
                    stock["analysis"] = None
                    stock["signal"] = "N/A"
                    stock["signal_color"] = "gray"
            except Exception:
                stock["analysis"] = None
                stock["signal"] = "N/A"
                stock["signal_color"] = "gray"

    await asyncio.gather(*[_enrich_stock(s) for s in stocks])

    total_invested = sum(s["invested_value"] for s in stocks)
    total_current = sum(s["current_value"] for s in stocks)
    total_pnl = sum(s["pnl"] for s in stocks)

    result = {
        "stocks": stocks,
        "summary": {
            "cash": _safe_float(cash),
            "used_margin": _safe_float(used_margin),
            "total_invested": round(_safe_float(total_invested), 2),
            "total_current": round(_safe_float(total_current), 2),
            "total_pnl": round(_safe_float(total_pnl), 2),
            "total_pnl_pct": round(((total_current / total_invested) - 1) * 100, 2) if total_invested > 0 else 0,
            "portfolio_value": round(_safe_float(cash) + _safe_float(total_current), 2),
            "num_holdings": len([s for s in stocks if s["type"] == "holding"]),
            "num_positions": len([s for s in stocks if s["type"] == "position"]),
        },
        "broker_connected": _state.executor.is_connected(),
    }
    def _sanitize(obj):
        """Recursively replace NaN/Inf with None in nested dicts/lists."""
        import math
        if isinstance(obj, float):
            return None if (math.isnan(obj) or math.isinf(obj)) else obj
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj]
        return obj

    return JSONResponse(content=_sanitize(result))


class PaperOrderRequest(BaseModel):
    ticker: str
    side: str  # "BUY" or "SELL"
    quantity: int
    price: float | None = None


@router.get("/paper/summary")
async def paper_summary():
    """Get paper trading portfolio summary."""
    _state.paper_trader.update_prices()
    return _state.paper_trader.get_summary()


@router.get("/paper/trades")
async def paper_trades(limit: int = 50):
    return {"trades": _state.paper_trader.get_trades(limit)}


@router.post("/paper/order")
async def paper_order(req: PaperOrderRequest):
    """Execute a paper trade."""
    if req.side.upper() == "BUY":
        result = _state.paper_trader.execute_buy(req.ticker, req.quantity, req.price)
    elif req.side.upper() == "SELL":
        result = _state.paper_trader.execute_sell(req.ticker, req.quantity, req.price)
    else:
        return {"success": False, "message": f"Invalid side: {req.side}"}
    return result


@router.post("/paper/reset")
async def paper_reset():
    _state.paper_trader.reset()
    return {"message": "Paper portfolio reset", "summary": _state.paper_trader.get_summary()}


@router.post("/mode/paper")
async def switch_to_paper():
    """Switch to paper trading mode (safe — no real orders)."""
    _state.config.broker.read_only = True
    _state.push_event({"type": "mode", "msg": "Switched to PAPER trading mode"})
    return {"mode": "paper", "read_only": True}


@router.post("/mode/live/request")
async def request_live_mode():
    """Step 1: Generate a short-lived confirmation token for switching to live mode."""
    token = secrets.token_urlsafe(32)
    _state._live_confirm_token = token
    _state._live_confirm_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    return {"confirmation_token": token, "expires_in_seconds": 300}


@router.post("/mode/live")
async def switch_to_live(confirm: bool = False, confirmation_token: str | None = None):
    """Step 2: Switch to live trading mode.

    Requires a valid confirmation_token obtained from /mode/live/request
    within the last 5 minutes.
    """
    if not confirm:
        raise HTTPException(400, "Live mode requires ?confirm=true and a confirmation_token")

    if (
        not confirmation_token
        or not _state._live_confirm_token
        or not _state._live_confirm_expiry
        or datetime.now(timezone.utc) > _state._live_confirm_expiry
        or not secrets.compare_digest(confirmation_token, _state._live_confirm_token)
    ):
        raise HTTPException(403, "Invalid or expired confirmation token — call /mode/live/request first")

    _state._live_confirm_token = None
    _state._live_confirm_expiry = None

    _state.config.broker.read_only = False
    _state.config.risk.require_confirmation = False
    _state.push_event({"type": "mode", "msg": "SWITCHED TO LIVE TRADING — real orders enabled!"})
    return {"mode": "live", "read_only": False, "warning": "Live trading active — real money at risk"}


@router.post("/run-cycle")
async def run_single_cycle(req: RunCycleRequest | None = None):
    from src.algo_trader.runner import AlgoTrader

    loop = asyncio.get_running_loop()

    if req and req.tickers:
        _state.config.watchlist = req.tickers

    trader = AlgoTrader(_state.config)
    trader.paper_trader = _state.paper_trader
    trader.tradebook = _state.tradebook

    # Pre-session: generate Hermes plan
    try:
        trader.pre_session(tradebook=_state.tradebook)
    except Exception as e:
        log.warning("Pre-session plan failed for manual cycle: %s", e)

    _state.push_event({"type": "cycle_start", "msg": f"Manual cycle on {len(_state.config.watchlist)} stocks..."})

    try:
        actions = await loop.run_in_executor(None, trader.run_cycle)
        _state.last_cycle_time = datetime.now(timezone.utc).isoformat()

        for a in (actions or []):
            entry = {
                "ticker": a.get("ticker", ""),
                "action": a.get("action", ""),
                "quantity": a.get("quantity", 0),
                "price": a.get("price", 0),
                "confidence": a.get("confidence", 0),
                "reasoning": a.get("reasoning", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result_ok": a.get("result").success if a.get("result") else False,
                "result_msg": a.get("result").message if a.get("result") else "",
                "instrument_type": a.get("instrument_type", "equity"),
                "strategy_name": a.get("strategy_name", ""),
            }
            _state.execution_log.append(entry)

            result_obj = a.get("result")
            _state.tradebook.record_trade({
                "ticker": a.get("ticker", ""),
                "action": a.get("action", "hold"),
                "side": "BUY" if "buy" in str(a.get("action", "")).lower() else "SELL",
                "quantity": a.get("quantity", 0),
                "price": a.get("price", 0),
                "mode": "paper" if _state.config.broker.read_only else "live",
                "confidence": a.get("confidence", 0),
                "decision_score": a.get("score", 0),
                "reasoning": a.get("reasoning", ""),
                "strategy_scores": a.get("strategy_scores", {}),
                "analyst_signals": a.get("analyst_signals", {}),
                "rsi": a.get("rsi"),
                "macd": a.get("macd"),
                "trend": a.get("trend"),
                "volatility": a.get("volatility"),
                "order_id": result_obj.order_id if result_obj else None,
                "executed": result_obj.success if result_obj else False,
                "execution_price": a.get("price", 0),
                "execution_msg": result_obj.message if result_obj else "",
                "model_name": _state.config.model_name,
                "source": "manual_cycle",
                "instrument_type": a.get("instrument_type", "equity"),
                "strategy_name": a.get("strategy_name", ""),
            })

            log_trade({
                "ticker": a.get("ticker", ""), "action": a.get("action", "hold"),
                "quantity": a.get("quantity", 0), "price": a.get("price", 0),
                "confidence": a.get("confidence", 0), "reasoning": a.get("reasoning", ""),
                "mode": "paper" if _state.config.broker.read_only else "live",
                "executed": result_obj.success if result_obj else False,
                "meta_verdict": _get_meta_verdict(a.get("ticker", "")),
            })

            # Route paper trades
            if _state.config.broker.read_only:
                ticker = a.get("ticker", "")
                qty = a.get("quantity", 0)
                act = str(a.get("action", "")).lower()
                if "buy" in act and qty > 0 and a.get("instrument_type", "equity") == "equity":
                    _state.paper_trader.execute_buy(ticker, qty)
                elif "sell" in act and qty > 0 and a.get("instrument_type", "equity") == "equity":
                    _state.paper_trader.execute_sell(ticker, qty)

        paper_summary = ""
        if _state.config.broker.read_only:
            ps = _state.paper_trader.get_summary()
            paper_summary = f" | Paper: ₹{ps['total_value']:,.0f} ({ps['total_return_pct']:+.1f}%)"

        _state.push_event({"type": "cycle_done", "msg": f"Manual cycle — {len(actions or [])} actions{paper_summary}"})
        return {"actions": len(actions or []), "log": _state.execution_log[-20:]}
    except Exception as e:
        log.error("Manual cycle failed: %s", e, exc_info=True)
        _state.push_event({"type": "error", "msg": f"Cycle failed: {e}"})
        raise HTTPException(500, f"Cycle failed: {e}")


@router.get("/execution-log")
async def get_execution_log():
    return {"log": _state.execution_log[-100:]}


@router.get("/config")
async def get_config():
    cfg = _state.config
    return {
        "watchlist": cfg.watchlist,
        "model_name": cfg.model_name,
        "model_provider": cfg.model_provider,
        "read_only": cfg.broker.read_only,
        "auto_trade": not cfg.risk.require_confirmation,
        "broker_connected": _state.executor.is_connected(),
        "risk": {
            "max_position_pct": cfg.risk.max_position_pct,
            "max_portfolio_exposure": cfg.risk.max_portfolio_exposure,
            "max_single_order_value": cfg.risk.max_single_order_value,
            "max_daily_loss_pct": cfg.risk.max_daily_loss_pct,
            "max_open_positions": cfg.risk.max_open_positions,
            "stop_loss_pct": cfg.risk.stop_loss_pct,
            "take_profit_pct": cfg.risk.take_profit_pct,
        },
        "scheduler": {
            "market_open": cfg.scheduler.market_open,
            "market_close": cfg.scheduler.market_close,
            "analysis_interval_minutes": cfg.scheduler.analysis_interval_minutes,
        },
    }


@router.put("/config")
async def update_config(update: ConfigUpdate):
    cfg = _state.config
    if update.watchlist is not None:
        cfg.watchlist = update.watchlist
    if update.auto_trade is not None:
        cfg.risk.require_confirmation = not update.auto_trade
    if update.read_only is not None:
        cfg.broker.read_only = update.read_only
        _state.mode = "paper" if update.read_only else "live"
    if update.max_daily_loss_pct is not None:
        cfg.risk.max_daily_loss_pct = update.max_daily_loss_pct
    if update.stop_loss_pct is not None:
        cfg.risk.stop_loss_pct = update.stop_loss_pct
    if update.take_profit_pct is not None:
        cfg.risk.take_profit_pct = update.take_profit_pct
    if update.max_position_pct is not None:
        cfg.risk.max_position_pct = update.max_position_pct
    if update.model_name is not None:
        cfg.model_name = update.model_name

    _state.push_event({"type": "config_update", "msg": "Config updated via API"})
    return {"message": "Config updated", "config": await get_config()}


@router.get("/risk")
async def get_risk():
    daily = _state.risk.daily_pnl
    cfg = _state.config.risk
    return {
        "daily_pnl": {"realized": daily.realized, "unrealized": daily.unrealized, "total": daily.total},
        "limits": {
            "max_daily_loss_pct": cfg.max_daily_loss_pct,
            "max_position_pct": cfg.max_position_pct,
            "max_portfolio_exposure": cfg.max_portfolio_exposure,
            "stop_loss_pct": cfg.stop_loss_pct,
            "take_profit_pct": cfg.take_profit_pct,
            "max_open_positions": cfg.max_open_positions,
        },
    }


@router.post("/screen")
async def screen_stocks_endpoint(req: ScreenRequest):
    """Run the daily stock screener to find high-volatility, high-volume candidates."""
    from src.algo_trader.screener import screen_stocks
    from src.data.nse_stocks import NIFTY_50

    tickers = req.tickers
    if not tickers:
        tickers = [f"{s}.NS" for s in NIFTY_50]

    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, lambda: screen_stocks(tickers, top_n=req.top_n))

    if req.auto_update_watchlist and results:
        _state.config.watchlist = [r.ticker for r in results]
        _state.push_event({"type": "screener", "msg": f"Watchlist updated to {len(results)} screened stocks"})

    return {
        "screened": [
            {
                "ticker": r.ticker, "score": r.score,
                "avg_volume_20d": r.avg_volume_20d, "relative_volume": r.relative_volume,
                "volatility_20d": r.volatility_20d, "adx": r.adx,
                "liquidity_ratio": r.liquidity_ratio, "sentiment": r.sentiment_score,
                "trend": r.trend, "last_close": r.last_close,
            }
            for r in results
        ],
        "total_scanned": len(tickers),
        "passed": len(results),
    }


@router.post("/scanner/start")
async def start_scanner():
    """Start the live background scanner (every 30 min during market hours)."""
    with _state._lifecycle_lock:
        if _state.scanner_running:
            return {"message": "Scanner already running", "running": True}
        _state.scanner_stop.clear()
        _state.scanner_thread = threading.Thread(target=_scanner_loop, daemon=True)
        _state.scanner_thread.start()
        _state.scanner_running = True
    return {"message": "Live scanner started", "running": True}


@router.post("/scanner/stop")
async def stop_scanner():
    """Stop the live background scanner."""
    with _state._lifecycle_lock:
        if not _state.scanner_running:
            return {"message": "Scanner not running", "running": False}
        _state.scanner_stop.set()
        _state.scanner_running = False
    return {"message": "Scanner stopping", "running": False}


@router.get("/scanner/status")
async def scanner_status():
    return {
        "running": _state.scanner_running,
        "last_scan_time": _state.last_scan_time,
        "results_count": len(_state.last_scan_results),
        "results": _state.last_scan_results,
        "scan_interval_minutes": SCAN_INTERVAL_MINUTES,
    }


@router.post("/scanner/run-now")
async def scanner_run_now():
    """Trigger an immediate scan (regardless of market hours)."""
    from src.algo_trader.screener import screen_stocks
    from src.data.nse_stocks import NIFTY_50

    loop = asyncio.get_running_loop()
    tickers = [f"{s}.NS" for s in NIFTY_50]

    results = await loop.run_in_executor(None, lambda: screen_stocks(tickers, top_n=20, max_workers=10))

    scan_rows = []
    for r in results:
        scan_rows.append({
            "ticker": r.ticker,
            "score": round(r.score, 2),
            "avg_volume": r.avg_volume_20d,
            "volatility": round(r.volatility_20d * 100, 2),
            "adx": round(r.adx, 1) if r.adx else None,
            "sentiment": r.sentiment_score,
            "trend": r.trend,
            "last_close": round(r.last_close, 2) if r.last_close else None,
        })
    _state.last_scan_results = scan_rows
    _state.last_scan_time = datetime.now(IST).isoformat()

    screened_tickers = [r.ticker for r in results]
    if screened_tickers:
        combined = list(set(_state.config.watchlist) | set(screened_tickers[:10]))
        _state.config.watchlist = sorted(combined)

    _state.push_event({"type": "scanner", "msg": f"Manual scan done — {len(results)} qualify"})

    return {
        "results": scan_rows,
        "count": len(scan_rows),
        "watchlist": _state.config.watchlist,
    }


@router.get("/stream")
async def event_stream():
    """SSE endpoint for real-time dashboard updates."""
    seen = 0

    async def generate():
        nonlocal seen
        while True:
            with _state._event_lock:
                new_events = _state.events[seen:]
                seen = len(_state.events)
            for ev in new_events:
                yield f"data: {json.dumps(ev)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Tradebook endpoints ──────────────────────────────────────────────

@router.get("/tradebook")
async def get_tradebook(limit: int = 50, ticker: str | None = None, action: str | None = None, open_only: bool = False):
    trades = _state.tradebook.get_trades(limit=limit, ticker=ticker, action=action, only_open=open_only)
    return {"trades": trades, "count": len(trades)}


@router.get("/tradebook/stats")
async def get_tradebook_stats():
    return _state.tradebook.get_performance_stats()


@router.get("/tradebook/learning-context")
async def get_learning_context(ticker: str | None = None, limit: int = 10):
    """Get formatted trade history for model prompting / Hermes memory."""
    return {"context": _state.tradebook.get_learning_context(ticker=ticker, limit=limit)}


@router.get("/tradebook/daily")
async def get_daily_summaries(limit: int = 30):
    return {"summaries": _state.tradebook.get_daily_summaries(limit=limit)}


@router.post("/tradebook/record-exit")
async def record_trade_exit(trade_id: int, exit_price: float, exit_reason: str = "manual"):
    _state.tradebook.record_exit(trade_id, exit_price, exit_reason)
    return {"message": f"Exit recorded for trade {trade_id}"}


@router.post("/tradebook/daily-summary")
async def record_daily_summary(lessons: str = ""):
    _state.tradebook.record_daily_summary(lessons=lessons)
    log_daily_digest(_state.tradebook.get_performance_stats(), lessons=lessons)
    return {"message": "Daily summary recorded"}


# ── Portfolio Analyst Review (Daily 12PM) ────────────────────────────

REVIEW_FILE = __import__("pathlib").Path(__file__).resolve().parents[3] / "outputs" / "portfolio_review.json"


def _run_analyst_review_sync():
    """Run 21-agent AI analysis (incl. Swarm + Options) on all portfolio holdings via Hermes."""
    import yfinance as yf
    import numpy as np

    _state.analyst_review_running = True
    _state.push_event({"type": "review", "msg": "Starting daily portfolio analyst review..."})
    log_action("ANALYST_REVIEW", "Starting daily 12PM portfolio analyst review")

    try:
        holdings = _state.executor.get_holdings()
        positions = _state.executor.get_positions()

        tickers = []
        for h in holdings:
            if h.quantity > 0:
                sym = f"{h.ticker}.NS" if not h.ticker.endswith((".NS", ".BO")) else h.ticker
                tickers.append(sym)
        for p in positions:
            if p.quantity != 0:
                sym = f"{p.ticker}.NS" if not p.ticker.endswith((".NS", ".BO")) else p.ticker
                if sym not in tickers:
                    tickers.append(sym)

        if not tickers:
            _state.push_event({"type": "review", "msg": "No holdings to review"})
            _state.analyst_review_running = False
            return

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

        n_agents = len(selected_analysts)
        _state.push_event({"type": "review", "msg": f"Running {n_agents}-agent analysis on {len(tickers)} stocks: {', '.join(t.replace('.NS','') for t in tickers[:8])}..."})

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
                "model_name": _state.config.model_name,
                "model_provider": "Anthropic",
                "request": type("Req", (), {
                    "api_keys": api_keys,
                    "get_agent_model_config": lambda self, agent_id: (_state.config.model_name, "Anthropic"),
                })(),
            },
        })

        analyst_signals = ai_result.get("data", {}).get("analyst_signals", {})

        from src.algo_trader.meta_analyst import run_meta_analysis
        verdicts = run_meta_analysis(analyst_signals, tickers)

        for ticker in tickers:
            ticker_signals = {}
            for agent_name, signals in analyst_signals.items():
                if isinstance(signals, dict) and ticker in signals:
                    ticker_signals[agent_name] = signals[ticker]
            verdicts[ticker]["analyst_signals"] = ticker_signals

        now_ist = datetime.now(IST).isoformat()

        review = {
            "timestamp": now_ist,
            "review_time": now_ist,
            "tickers": tickers,
            "verdicts": verdicts,
            "model_used": _state.config.model_name,
            "stocks_reviewed": len(tickers),
        }

        prev_review = load_previous_review()

        _state.analyst_review = review
        _state.analyst_review_time = now_ist

        REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        with open(REVIEW_FILE, "w") as f:
            _json.dump(review, f, indent=2, default=str)

        save_review_snapshot(review)

        changes = None
        if prev_review:
            changes = diff_reviews(review, prev_review)
            review["changes"] = changes
            _state.analyst_review["changes"] = changes
            n_flips = changes["summary"]["signal_flips"]
            if n_flips > 0:
                flip_details = ", ".join(
                    f"{f['ticker'].replace('.NS','')}: {f['from']}->{f['to']}"
                    for f in changes["signal_flips"][:5]
                )
                log_action("REVIEW_DIFF", f"{n_flips} signal flips vs previous scan: {flip_details}")

            # Push individual signal flip events for the notification system
            for flip in changes.get("signal_flips", []):
                _state.push_event({
                    "type": "signal_flip",
                    "ticker": flip["ticker"],
                    "from": flip["from"],
                    "to": flip["to"],
                    "score_delta": flip.get("score_delta", 0),
                    "msg": f"Signal flip: {flip['ticker'].replace('.NS','')} {flip['from']} → {flip['to']}",
                })

            # Push summary change event
            cs = changes["summary"]
            if cs["signal_flips"] > 0 or cs["improved"] > 0 or cs["declined"] > 0:
                _state.push_event({
                    "type": "review_changes",
                    "summary": cs,
                    "biggest_movers": changes.get("biggest_movers", []),
                    "msg": f"Review changes: {cs['signal_flips']} flips, {cs['improved']} improved, {cs['declined']} declined",
                })

        log_analyst_review({
            "stocks_reviewed": tickers,
            "verdicts": verdicts,
            "summary": f"{len(tickers)} stocks reviewed. Model: {_state.config.model_name}",
        })

        buys = sum(1 for v in verdicts.values() if 'buy' in str(v.get('action', '')).lower())
        sells = sum(1 for v in verdicts.values() if 'sell' in str(v.get('action', '')).lower())
        holds = sum(1 for v in verdicts.values() if 'hold' in str(v.get('action', '')).lower())
        change_msg = ""
        if changes:
            cs = changes["summary"]
            change_msg = f" | Changes: {cs['signal_flips']} flips, {cs['improved']} improved, {cs['declined']} declined"

        _state.push_event({
            "type": "review",
            "msg": f"Analyst review complete — {len(tickers)} stocks analyzed. "
                   f"Buys: {buys}, Sells: {sells}, Holds: {holds}{change_msg}"
        })

    except Exception as e:
        log.error("Analyst review failed: %s", e, exc_info=True)
        _state.push_event({"type": "error", "msg": f"Analyst review failed: {e}"})
        log_action("ANALYST_REVIEW_FAILED", str(e)[:300])
    finally:
        _state.analyst_review_running = False


def _review_scheduler_loop():
    """Background thread: runs analyst review at 12:00 IST on weekdays."""
    log.info("Review scheduler started — daily at 12:00 IST")
    _state.push_event({"type": "review", "msg": "Review scheduler started — daily at 12:00 IST"})

    last_run_date: str | None = None

    while not _state.review_scheduler_stop.is_set():
        now_ist = datetime.now(IST)
        today_str = now_ist.strftime("%Y-%m-%d")
        hour, minute = now_ist.hour, now_ist.minute

        if now_ist.weekday() < 5 and hour == 12 and minute < 5 and last_run_date != today_str:
            last_run_date = today_str
            log.info("Triggering scheduled 12PM analyst review")
            try:
                _run_analyst_review_sync()
            except Exception as e:
                log.error("Scheduled review error: %s", e, exc_info=True)

        _state.review_scheduler_stop.wait(60)

    log.info("Review scheduler stopped")


@router.post("/portfolio/analyst-review")
async def trigger_analyst_review(background_tasks: BackgroundTasks):
    """Manually trigger the 21-agent analyst review (Swarm + Options + Meta) on all portfolio holdings."""
    if _state.analyst_review_running:
        return {"message": "Analyst review already in progress", "running": True}

    loop = asyncio.get_running_loop()
    background_tasks.add_task(loop.run_in_executor, None, _run_analyst_review_sync)
    return {"message": "Analyst review started", "running": True}


def _reprocess_verdicts_meta(review: dict) -> dict:
    """Re-run meta-analyst on existing review data to fix stale verdicts."""
    from src.algo_trader.meta_analyst import run_meta_analysis
    verdicts = review.get("verdicts", {})
    tickers = review.get("tickers", list(verdicts.keys()))

    analyst_signals: dict = {}
    for ticker, v in verdicts.items():
        for agent_name, sig in (v.get("analyst_signals") or {}).items():
            analyst_signals.setdefault(agent_name, {})[ticker] = sig

    if not analyst_signals:
        return review

    new_verdicts = run_meta_analysis(analyst_signals, tickers)
    for ticker in tickers:
        new_verdicts[ticker]["analyst_signals"] = verdicts.get(ticker, {}).get("analyst_signals", {})

    review["verdicts"] = new_verdicts
    return review


@router.get("/portfolio/analyst-review")
async def get_analyst_review():
    """Get the latest analyst review results."""
    if _state.analyst_review is None and REVIEW_FILE.exists():
        import json as _json
        with open(REVIEW_FILE) as f:
            _state.analyst_review = _json.load(f)
            _state.analyst_review_time = _state.analyst_review.get("timestamp")

    if _state.analyst_review and not _state.analyst_review_running:
        v0 = next(iter((_state.analyst_review.get("verdicts") or {}).values()), {})
        if "signal_breakdown" not in v0:
            _state.analyst_review = _reprocess_verdicts_meta(_state.analyst_review)
            if REVIEW_FILE.exists():
                import json as _json
                with open(REVIEW_FILE, "w") as f:
                    _json.dump(_state.analyst_review, f, indent=2, default=str)

    return {
        "review": _state.analyst_review,
        "timestamp": _state.analyst_review_time,
        "running": _state.analyst_review_running,
    }


@router.post("/portfolio/reprocess-verdicts")
async def reprocess_verdicts():
    """Re-run the Meta Analyst on existing analyst signals without re-running the full AI review."""
    if _state.analyst_review is None:
        return {"error": "No review data available to reprocess"}
    _state.analyst_review = _reprocess_verdicts_meta(_state.analyst_review)
    if REVIEW_FILE.exists():
        import json as _json
        with open(REVIEW_FILE, "w") as f:
            _json.dump(_state.analyst_review, f, indent=2, default=str)
    return {"message": "Verdicts reprocessed via Meta Analyst", "review": _state.analyst_review}


@router.get("/portfolio/review-history")
async def get_review_history():
    """List all stored review snapshots with summary metadata."""
    return {"snapshots": list_snapshots()}


@router.get("/portfolio/review-diff")
async def get_review_diff(scan_a: str | None = None, scan_b: str | None = None):
    """Compare two review scans. Defaults to latest vs previous if no params given."""
    if scan_a and scan_b:
        a = load_snapshot_by_filename(scan_a)
        b = load_snapshot_by_filename(scan_b)
        if not a or not b:
            raise HTTPException(404, "One or both snapshots not found")
        return {"diff": diff_reviews(a, b)}

    review = _state.analyst_review
    if review and "changes" in review:
        return {"diff": review["changes"]}

    prev = load_previous_review()
    if not review or not prev:
        return {"diff": None, "message": "Need at least two reviews to compare"}
    return {"diff": diff_reviews(review, prev)}


@router.post("/portfolio/review-scheduler/start")
async def start_review_scheduler():
    """Start the daily 12PM review scheduler."""
    with _state._lifecycle_lock:
        if _state.review_scheduler_running:
            return {"message": "Review scheduler already running", "running": True}
        _state.review_scheduler_stop.clear()
        _state.review_scheduler_thread = threading.Thread(target=_review_scheduler_loop, daemon=True)
        _state.review_scheduler_thread.start()
        _state.review_scheduler_running = True
    return {"message": "Review scheduler started (daily 12:00 IST)", "running": True}


@router.post("/portfolio/review-scheduler/stop")
async def stop_review_scheduler():
    with _state._lifecycle_lock:
        if not _state.review_scheduler_running:
            return {"message": "Review scheduler not running", "running": False}
        _state.review_scheduler_stop.set()
        _state.review_scheduler_running = False
    return {"message": "Review scheduler stopping", "running": False}


# ── Penny Stock Scanner (Full AI Pipeline) ───────────────────────────

_penny_progress: dict = {}


def _update_penny_progress(stage: str, detail: str = "", done: int = 0, total: int = 0):
    """Update penny scan progress and push SSE event."""
    global _penny_progress
    _penny_progress = {
        "stage": stage, "detail": detail,
        "stocks_done": done, "stocks_total": total,
        "started_at": _penny_progress.get("started_at", ""),
    }
    _state.push_event({
        "type": "penny_progress", "stage": stage,
        "detail": detail, "stocks_done": done, "stocks_total": total,
    })


def _run_penny_scan_sync():
    """Execute full AI penny stock scan in background thread."""
    global _penny_progress
    from src.algo_trader.penny_scanner import run_penny_scan

    _penny_progress = {
        "stage": "starting", "detail": "Initializing...",
        "stocks_done": 0, "stocks_total": 0,
        "started_at": datetime.now(IST).isoformat(),
    }
    _state.push_event({"type": "penny_scan", "msg": "Starting AI-powered penny stock scan..."})

    try:
        report = run_penny_scan(progress_callback=_update_penny_progress)
        strong = report.get("strong_buys", [])
        buys = report.get("buys", [])
        all_results = strong + buys
        log_penny_scan(all_results[:10])

        for sb in strong:
            _state.push_event({
                "type": "penny_strong_buy",
                "ticker": sb["ticker"],
                "msg": f"Penny Strong Buy: {sb['ticker'].replace('.NS','').replace('.BO','')} @ ₹{sb.get('last_close', '?')} — AI score {sb.get('ai_score', 0):.3f}",
                "score": sb.get("ai_score", 0),
            })
        for b in buys:
            _state.push_event({
                "type": "penny_buy",
                "ticker": b["ticker"],
                "msg": f"Penny Buy: {b['ticker'].replace('.NS','').replace('.BO','')} @ ₹{b.get('last_close', '?')} — AI score {b.get('ai_score', 0):.3f}",
                "score": b.get("ai_score", 0),
            })

        _state.push_event({
            "type": "penny_scan",
            "msg": f"Penny AI scan complete — {len(strong)} strong buys, {len(buys)} buys from {report.get('total_scanned', 0)} analyzed",
        })
        _state.penny_scan_ready = True
    except Exception as e:
        log.error("Penny scan error: %s", e, exc_info=True)
        _state.push_event({"type": "error", "msg": f"Penny scan failed: {e}"})
    finally:
        _state.penny_scan_running = False
        _penny_progress = {}


@router.post("/penny-scanner/scan")
async def trigger_penny_scan():
    """Manually trigger the full AI-powered penny stock scan."""
    global _penny_progress
    if not _state.try_start_penny_scan():
        return {"message": "Penny scan already in progress", "running": True}
    _penny_progress = {
        "stage": "starting", "detail": "Initializing...",
        "stocks_done": 0, "stocks_total": 0,
        "started_at": datetime.now(IST).isoformat(),
    }
    t = threading.Thread(target=_run_penny_scan_sync, daemon=True)
    t.start()
    return {"message": "AI penny scan started (full agent pipeline)", "running": True}


@router.get("/penny-scanner/status")
async def get_penny_scan_status():
    """Polling endpoint with real-time progress."""
    status: dict[str, Any] = {
        "scanning": _state.penny_scan_running,
        "ready": _state.penny_scan_ready,
    }
    if _state.penny_scan_running and _penny_progress:
        status["progress"] = _penny_progress
    return status


@router.get("/penny-scanner/results")
async def get_penny_scan_results(refresh_prices: bool = False):
    """Get the latest penny scan results (only buy-recommended stocks)."""
    from src.algo_trader.penny_scanner import load_scan_results, refresh_live_prices, IST
    data = load_scan_results()
    if refresh_prices and data.get("results"):
        loop = asyncio.get_running_loop()
        data["results"] = await loop.run_in_executor(
            None, refresh_live_prices, data["results"]
        )
        from datetime import datetime
        data["prices_refreshed_at"] = datetime.now(IST).isoformat()
    return data


# ── Market Discovery ─────────────────────────────────────────────────

_discovery_running = False
_discovery_progress: dict = {}


def _update_discovery_progress(stage: str, detail: str = "", stocks_done: int = 0, stocks_total: int = 0):
    """Update progress and push an SSE event."""
    global _discovery_progress
    _discovery_progress = {
        "stage": stage,
        "detail": detail,
        "stocks_done": stocks_done,
        "stocks_total": stocks_total,
        "started_at": _discovery_progress.get("started_at", ""),
    }
    _state.push_event({
        "type": "discovery_progress",
        "stage": stage,
        "detail": detail,
        "stocks_done": stocks_done,
        "stocks_total": stocks_total,
    })


def _run_discovery_sync():
    """Run full AI swarm discovery in background thread.

    Analyzes 4 random stocks with all 21 agents + swarm + meta analyst,
    keeps only strong buys, logs to Hermes, and pushes notifications.
    """
    global _discovery_running, _discovery_progress
    from src.algo_trader.daily_analysis import run_discovery_scan

    _discovery_progress = {"stage": "starting", "detail": "Preparing stock universe...", "stocks_done": 0, "stocks_total": 0, "started_at": datetime.now(IST).isoformat()}
    _state.push_event({"type": "discovery", "msg": "Starting market discovery (4 stocks, full AI swarm)..."})

    try:
        exclude = []
        try:
            holdings = _state.executor.get_holdings()
            exclude = [h.ticker for h in holdings if h.quantity > 0]
        except Exception:
            pass
        if _state.analyst_review:
            exclude.extend(_state.analyst_review.get("tickers", []))

        def on_progress(stage: str, detail: str = "", stocks_done: int = 0, stocks_total: int = 0):
            _update_discovery_progress(stage, detail, stocks_done, stocks_total)

        report = run_discovery_scan(
            exclude_tickers=exclude,
            sample_size=4,
            model_name=_state.config.model_name,
            progress_callback=on_progress,
        )

        strong = report.get("strong_buys", [])
        buys = report.get("buys", [])
        batch = report.get("last_batch", [])
        log_action("DISCOVERY", f"Scanned {', '.join(batch)} — {len(strong)} strong buys, {len(buys)} buys total")

        batch_set = {f"{t}.NS" for t in batch}
        for sb in strong:
            if sb["ticker"] in batch_set:
                tk = sb["ticker"].replace(".NS", "")
                _state.push_event({
                    "type": "strong_buy_found",
                    "ticker": sb["ticker"],
                    "msg": (
                        f"Strong Buy: {tk} @ {sb.get('current_price', '?')} — "
                        f"score {sb.get('score', 0):.3f}, "
                        f"target {sb.get('target_price', 0)}, "
                        f"SL {sb.get('stop_loss', 0)}"
                    ),
                    "score": sb.get("score", 0),
                    "action": sb.get("action", ""),
                    "target_price": sb.get("target_price", 0),
                    "stop_loss": sb.get("stop_loss", 0),
                })
        for b in buys:
            if b["ticker"] in batch_set:
                tk = b["ticker"].replace(".NS", "")
                _state.push_event({
                    "type": "buy_found",
                    "ticker": b["ticker"],
                    "msg": (
                        f"Buy: {tk} @ {b.get('current_price', '?')} — "
                        f"score {b.get('score', 0):.3f}"
                    ),
                    "score": b.get("score", 0),
                    "action": b.get("action", ""),
                })

        _state.push_event({
            "type": "discovery",
            "msg": f"Discovery complete — analyzed {', '.join(batch)}, {len(strong)} strong buys, {len(buys)} buys found",
        })
    except Exception as e:
        log.error("Discovery scan error: %s", e, exc_info=True)
        _state.push_event({"type": "error", "msg": f"Discovery scan failed: {e}"})
    finally:
        _discovery_running = False
        _discovery_progress = {}


@router.post("/discovery/generate")
async def trigger_discovery_scan():
    """Run full AI swarm analysis on 4 random stocks outside the portfolio."""
    global _discovery_running, _discovery_progress
    if _discovery_running:
        return {"message": "Discovery scan already in progress", "running": True}
    _discovery_running = True
    _discovery_progress = {"stage": "starting", "detail": "Initializing...", "stocks_done": 0, "stocks_total": 0, "started_at": datetime.now(IST).isoformat()}
    t = threading.Thread(target=_run_discovery_sync, daemon=True)
    t.start()
    return {"message": "Discovery scan started (4 stocks, full AI swarm)", "running": True}


@router.get("/discovery/results")
async def get_discovery_results():
    """Get the accumulated strong buy discoveries."""
    from src.algo_trader.daily_analysis import load_discovery_results
    report = load_discovery_results()
    if not report:
        return {"report": None, "message": "No discovery results. Click Discover or start the hourly scheduler."}
    return {"report": report}


@router.get("/discovery/status")
async def get_discovery_status():
    """Polling endpoint with real-time progress info."""
    status: dict[str, Any] = {
        "running": _discovery_running,
        "scheduler_running": _discovery_scheduler_running,
    }
    if _discovery_running and _discovery_progress:
        status["progress"] = _discovery_progress
    return status


# ── Discovery auto-scheduler (hourly) ────────────────────────────────

_discovery_scheduler_running = False
_discovery_scheduler_stop = threading.Event()


def _discovery_scheduler_loop():
    """Run discovery scan every hour (24/7)."""
    global _discovery_scheduler_running, _discovery_running
    log.info("Discovery scheduler started — every hour (24/7)")
    _state.push_event({"type": "discovery", "msg": "Hourly discovery scheduler started (24/7)"})

    while not _discovery_scheduler_stop.is_set():
        try:
            _discovery_running = True
            _run_discovery_sync()
        except Exception as e:
            log.error("Discovery scheduler error: %s", e)
        _discovery_scheduler_stop.wait(3600)
    _discovery_scheduler_running = False
    log.info("Discovery scheduler stopped")


@router.post("/discovery/schedule")
async def start_discovery_scheduler():
    """Start the hourly market discovery scheduler."""
    global _discovery_scheduler_running
    if _discovery_scheduler_running:
        return {"message": "Discovery scheduler already running", "running": True}
    _discovery_scheduler_stop.clear()
    t = threading.Thread(target=_discovery_scheduler_loop, daemon=True)
    t.start()
    _discovery_scheduler_running = True
    return {"message": "Hourly discovery scheduler started", "running": True}


@router.post("/discovery/schedule/stop")
async def stop_discovery_scheduler():
    """Stop the hourly market discovery scheduler."""
    global _discovery_scheduler_running
    _discovery_scheduler_stop.set()
    _discovery_scheduler_running = False
    return {"message": "Discovery scheduler stopping", "running": False}


@router.post("/discovery/clear")
async def clear_discovery_results():
    """Clear all accumulated discovery results to start fresh."""
    from src.algo_trader.daily_analysis import DISCOVERY_FILE
    if DISCOVERY_FILE.exists():
        DISCOVERY_FILE.unlink()
    return {"message": "Discovery results cleared"}


_penny_scheduler_running = False
_penny_scheduler_stop = threading.Event()


def _penny_scheduler_loop():
    """Background loop: runs AI penny scan every 30 minutes (24/7)."""
    global _penny_scheduler_running
    log.info("Penny scheduler started — every 30 min (24/7)")
    while not _penny_scheduler_stop.is_set():
        if _state.try_start_penny_scan():
            try:
                _run_penny_scan_sync()
            except Exception as e:
                log.error("Penny scheduler error: %s", e)
                _state.penny_scan_running = False
        _penny_scheduler_stop.wait(1800)
    _penny_scheduler_running = False


@router.post("/penny-scanner/schedule")
async def start_penny_scheduler():
    """Start the daily 10:00 IST penny scanner scheduler."""
    global _penny_scheduler_running
    if _penny_scheduler_running:
        return {"message": "Penny scheduler already running", "running": True}
    _penny_scheduler_stop.clear()
    t = threading.Thread(target=_penny_scheduler_loop, daemon=True)
    t.start()
    _penny_scheduler_running = True
    return {"message": "Penny scanner scheduled (daily 10:00 IST)", "running": True}


# ── Daily Analysis ───────────────────────────────────────────────────

def _generate_daily_analysis_sync():
    """Generate daily analysis in background thread."""
    from src.algo_trader.daily_analysis import generate_daily_analysis

    _state.push_event({"type": "daily_analysis", "msg": "Generating daily analysis..."})
    try:
        report = generate_daily_analysis()
        log_daily_analysis(report)
        n_buys = len(report.get("strong_buys", []))
        n_targets = len(report.get("target_signals", []))
        _state.push_event({
            "type": "daily_analysis",
            "msg": f"Daily analysis ready — {n_buys} strong buys, {n_targets} targets",
        })
        _state.daily_analysis_ready = True
    except Exception as e:
        log.error("Daily analysis generation error: %s", e, exc_info=True)
        _state.push_event({"type": "error", "msg": f"Daily analysis failed: {e}"})
    finally:
        _state.daily_analysis_generating = False


@router.post("/daily-analysis/generate")
async def trigger_daily_analysis(background_tasks: BackgroundTasks):
    """Manually trigger daily analysis generation."""
    if not _state.try_start_daily_analysis():
        return {"message": "Daily analysis generation already in progress", "generating": True}
    loop = asyncio.get_running_loop()
    background_tasks.add_task(loop.run_in_executor, None, _generate_daily_analysis_sync)
    return {"message": "Daily analysis generation started", "generating": True}


@router.get("/daily-analysis/status")
async def get_daily_analysis_status():
    """Polling endpoint — returns generation and scan status so the frontend
    can know when to refetch the report."""
    return {
        "generating": _state.daily_analysis_generating,
        "penny_scanning": _state.penny_scan_running,
        "ready": _state.daily_analysis_ready,
    }


@router.get("/daily-analysis")
async def get_daily_analysis():
    """Get the latest daily analysis report."""
    from src.algo_trader.daily_analysis import load_daily_analysis
    report = load_daily_analysis()
    if not report:
        return {"report": None, "message": "No daily analysis available. Trigger generation first."}
    return {"report": report}


@router.get("/daily-analysis/stock/{ticker}")
async def get_stock_detail_from_daily(ticker: str):
    """Fetch full detail (technicals, fundamentals, chart, verdicts) for a stock from daily analysis."""
    import yfinance as yf
    import numpy as np
    from datetime import timedelta
    from app.backend.routes.hedge_fund import _compute_technical, _fetch_fundamentals

    loop = asyncio.get_running_loop()
    yf_ticker = ticker if "." in ticker else f"{ticker}.NS"

    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    df = await loop.run_in_executor(
        None, lambda: yf.Ticker(yf_ticker).history(start=start_date, end=end_date)
    )

    result: dict = {"ticker": ticker, "yf_ticker": yf_ticker}

    if df is not None and not df.empty:
        df.columns = [str(c).strip().capitalize() for c in df.columns]

        result["technical"] = _compute_technical(df)
        result["current_price"] = round(float(df["Close"].iloc[-1]), 2)

        last_90 = df.tail(90)
        result["price_history"] = [
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            }
            for idx, row in last_90.iterrows()
        ]
    else:
        result["technical"] = {}
        result["price_history"] = []
        result["current_price"] = None

    result["fundamentals"] = await loop.run_in_executor(None, _fetch_fundamentals, yf_ticker)

    # Load review verdicts — from memory first, then from file
    verdicts = {}
    if _state.analyst_review:
        verdicts = _state.analyst_review.get("verdicts", {})
    elif REVIEW_FILE.exists():
        try:
            import json as _json
            with open(REVIEW_FILE) as f:
                _state.analyst_review = _json.load(f)
            verdicts = _state.analyst_review.get("verdicts", {})
        except Exception:
            pass

    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")
    verdict = (
        verdicts.get(ticker)
        or verdicts.get(yf_ticker)
        or verdicts.get(f"{clean_ticker}.NS")
        or verdicts.get(clean_ticker)
        or {}
    )
    result["verdict"] = verdict
    result["analyst_signals"] = verdict.get("analyst_signals", {})

    # If this stock was part of the penny scan, include its scanner data
    from src.algo_trader.penny_scanner import load_scan_results
    penny_data = load_scan_results()
    for p in penny_data.get("results", []):
        if p.get("ticker", "") in (ticker, yf_ticker, f"{clean_ticker}.NS"):
            result["penny_scan"] = p
            break

    result["reviewed"] = bool(verdict)

    return result


# ── Portfolio Rebalance Analysis ─────────────────────────────────────

def _run_rebalance_sync():
    """Run portfolio rebalance analysis in background."""
    from src.algo_trader.portfolio_balancer import analyse_portfolio_balance, load_rebalance_analysis
    from src.algo_trader.penny_scanner import load_scan_results
    _state.push_event({"type": "rebalance", "msg": "Running portfolio rebalance analysis..."})
    try:
        holdings = []
        try:
            from src.algo_trader.executor import ZerodhaExecutor
            executor = ZerodhaExecutor(_state.config)
            raw_holdings = executor.get_holdings()
            for h in raw_holdings:
                holdings.append({
                    "ticker": h.ticker if hasattr(h, "ticker") else h.get("tradingsymbol", ""),
                    "quantity": h.quantity if hasattr(h, "quantity") else h.get("quantity", 0),
                    "last_price": h.last_price if hasattr(h, "last_price") else h.get("last_price", 0),
                })
        except Exception:
            pass

        if not holdings and _state.analyst_review:
            for ticker in _state.analyst_review.get("tickers", []):
                holdings.append({"ticker": ticker, "quantity": 1, "last_price": 0})

        verdicts = (_state.analyst_review or {}).get("verdicts", {})
        penny = load_scan_results().get("results", [])

        result = analyse_portfolio_balance(holdings, verdicts, penny)
        log_rebalance(result)
        n_sug = len(result.get("suggestions", []))
        n_picks = len(result.get("short_term_picks", []))
        _state.push_event({
            "type": "rebalance",
            "msg": f"Rebalance analysis done — {n_sug} suggestions, {n_picks} picks",
        })
    except Exception as e:
        log.error("Rebalance analysis error: %s", e, exc_info=True)
        _state.push_event({"type": "error", "msg": f"Rebalance analysis failed: {e}"})


@router.post("/portfolio/rebalance-analysis")
async def trigger_rebalance(background_tasks: BackgroundTasks):
    """Trigger portfolio rebalance analysis."""
    loop = asyncio.get_running_loop()
    background_tasks.add_task(loop.run_in_executor, None, _run_rebalance_sync)
    return {"message": "Rebalance analysis started"}


@router.get("/portfolio/rebalance-analysis")
async def get_rebalance():
    """Get the latest portfolio rebalance analysis."""
    from src.algo_trader.portfolio_balancer import load_rebalance_analysis
    result = load_rebalance_analysis()
    if not result:
        return {"result": None, "message": "No rebalance analysis available. Trigger generation first."}
    return {"result": result}


# ── Session Plan / Hermes / Strategy Performance ──────────────────────

_current_session_plan: dict | None = None


@router.get("/session-plan")
async def get_session_plan():
    """Return the current Hermes session plan."""
    return {"plan": _current_session_plan}


@router.post("/session-plan/generate")
async def generate_session_plan_endpoint():
    """Generate a new Hermes session plan."""
    global _current_session_plan
    from src.algo_trader.strategy_advisor import generate_session_plan as gen_plan
    try:
        plan = gen_plan(tradebook=_state.tradebook, model_name=_state.config.model_name)
        _current_session_plan = plan.to_dict()
        _state.push_event({"type": "session_plan", "msg": f"Session plan generated: {len(plan.strategy_weights)} strategies"})
        return {"plan": _current_session_plan}
    except Exception as e:
        log.error("Session plan generation failed: %s", e)
        return {"plan": None, "error": str(e)}


@router.get("/strategy-performance")
async def get_strategy_performance():
    """Return strategy leaderboard from live trading."""
    from src.algo_trader.strategy_tracker import StrategyTracker
    tracker = StrategyTracker()
    return {
        "leaderboard": tracker.get_strategy_leaderboard(days=30),
        "all_backtests": tracker.get_all_performance(),
    }


@router.get("/fno/positions")
async def get_fno_positions():
    """Return current F&O positions (paper or live)."""
    return _state.paper_trader.get_fno_summary()


@router.get("/fno/summary")
async def get_fno_summary():
    """Return combined equity + F&O portfolio summary."""
    eq_summary = _state.paper_trader.get_summary()
    fno_summary = _state.paper_trader.get_fno_summary()
    return {
        "equity": eq_summary,
        "fno": fno_summary,
        "combined_value": eq_summary.get("total_value", 0),
        "combined_pnl": eq_summary.get("total_pnl", 0) + fno_summary.get("realized_pnl", 0),
    }


@router.get("/learning/timeline")
async def get_learning_timeline():
    """Return Hermes learning timeline (recent lessons + strategy evolution)."""
    from pathlib import Path

    lessons = []
    summaries = _state.tradebook.get_daily_summaries(limit=14)
    for s in summaries:
        if s.get("lessons"):
            lessons.append({"date": s["date"], "lesson": s["lessons"],
                            "pnl": s.get("total_pnl", 0), "trades": s.get("total_trades", 0)})

    evolution_lines = []
    evo_file = Path.home() / ".hermes" / "memories" / "strategy_evolution.md"
    try:
        if evo_file.exists():
            text = evo_file.read_text()
            blocks = text.split("---")
            for block in blocks[-10:]:
                if block.strip():
                    evolution_lines.append(block.strip())
    except Exception:
        pass

    mistakes = _state.tradebook.get_mistake_patterns(days=14)

    return {
        "lessons": lessons,
        "strategy_evolution": evolution_lines,
        "mistake_patterns": mistakes,
    }


# ── Daily Analysis Auto-Scheduler (12:30 IST) ────────────────────────

_daily_analysis_scheduler_running = False
_daily_analysis_scheduler_stop = threading.Event()


def _daily_analysis_scheduler_loop():
    """Background loop: generates daily analysis at 12:30 IST (after 12:00 review)."""
    global _daily_analysis_scheduler_running
    last_run_date: str | None = None
    while not _daily_analysis_scheduler_stop.is_set():
        now_ist = datetime.now(IST)
        today_str = now_ist.strftime("%Y-%m-%d")
        if now_ist.weekday() < 5 and now_ist.hour == 12 and 28 <= now_ist.minute <= 35 and last_run_date != today_str:
            last_run_date = today_str
            try:
                _run_rebalance_sync()
                _generate_daily_analysis_sync()
            except Exception as e:
                log.error("Daily analysis scheduler error: %s", e)
        _daily_analysis_scheduler_stop.wait(60)
    _daily_analysis_scheduler_running = False


@router.post("/daily-analysis/schedule")
async def start_daily_analysis_scheduler():
    """Start the daily 12:30 IST analysis scheduler."""
    global _daily_analysis_scheduler_running
    if _daily_analysis_scheduler_running:
        return {"message": "Daily analysis scheduler already running", "running": True}
    _daily_analysis_scheduler_stop.clear()
    t = threading.Thread(target=_daily_analysis_scheduler_loop, daemon=True)
    t.start()
    _daily_analysis_scheduler_running = True
    return {"message": "Daily analysis scheduled (12:30 IST)", "running": True}


# ── Notifications via OpenClaw (Telegram / WhatsApp) ─────────────────

_msg_scheduler_running = False
_msg_scheduler_stop = threading.Event()


def _msg_scheduler_loop():
    """Background loop: sends Telegram/WhatsApp messages at 9:15, 12:00, 3:30 IST on weekdays."""
    from src.algo_trader.whatsapp_notifier import (
        send_message, format_pre_market_msg, format_midday_msg, format_closing_msg, _channel,
    )
    global _msg_scheduler_running
    channel = _channel().capitalize()

    log.info("%s scheduler started — sends at 9:15, 12:00, 3:30 IST", channel)
    _state.push_event({"type": "messaging", "msg": f"{channel} scheduler started — 9:15, 12:00, 3:30 IST"})

    sent_today: dict[str, bool] = {}

    while not _msg_scheduler_stop.is_set():
        now_ist = datetime.now(IST)
        today_str = now_ist.strftime("%Y-%m-%d")
        hour, minute = now_ist.hour, now_ist.minute

        if today_str not in str(list(sent_today.keys())[:1]):
            sent_today = {}

        if now_ist.weekday() < 5:
            slot_key = f"{today_str}-"
            if hour == 9 and 13 <= minute <= 20:
                slot_key += "premarket"
                if slot_key not in sent_today:
                    msg = format_pre_market_msg()
                    ok = send_message(msg)
                    sent_today[slot_key] = ok
                    log_action("MSG_SENT", f"Pre-market {channel} ({'ok' if ok else 'failed'})")
                    _state.push_event({"type": "messaging", "msg": f"Pre-market {channel} {'sent' if ok else 'failed'}"})

            elif hour == 12 and minute < 5:
                slot_key += "midday"
                if slot_key not in sent_today:
                    msg = format_midday_msg()
                    ok = send_message(msg)
                    sent_today[slot_key] = ok
                    log_action("MSG_SENT", f"Midday {channel} ({'ok' if ok else 'failed'})")
                    _state.push_event({"type": "messaging", "msg": f"Midday {channel} {'sent' if ok else 'failed'}"})

            elif hour == 15 and 28 <= minute <= 35:
                slot_key += "closing"
                if slot_key not in sent_today:
                    msg = format_closing_msg()
                    ok = send_message(msg)
                    sent_today[slot_key] = ok
                    log_action("MSG_SENT", f"Closing {channel} ({'ok' if ok else 'failed'})")
                    _state.push_event({"type": "messaging", "msg": f"Closing {channel} {'sent' if ok else 'failed'}"})

        _msg_scheduler_stop.wait(60)

    _msg_scheduler_running = False
    log.info("%s scheduler stopped", channel)


@router.post("/whatsapp/schedule")
async def start_msg_scheduler():
    """Start the notification scheduler (9:15, 12:00, 3:30 IST) — Telegram or WhatsApp."""
    global _msg_scheduler_running
    if _msg_scheduler_running:
        return {"message": "Notification scheduler already running", "running": True}
    _msg_scheduler_stop.clear()
    t = threading.Thread(target=_msg_scheduler_loop, daemon=True)
    t.start()
    _msg_scheduler_running = True
    from src.algo_trader.whatsapp_notifier import _channel
    return {"message": f"{_channel().capitalize()} scheduler started (9:15, 12:00, 3:30 IST)", "running": True}


@router.post("/whatsapp/stop")
async def stop_msg_scheduler():
    """Stop the notification scheduler."""
    global _msg_scheduler_running
    if not _msg_scheduler_running:
        return {"message": "Notification scheduler not running", "running": False}
    _msg_scheduler_stop.set()
    _msg_scheduler_running = False
    return {"message": "Notification scheduler stopping", "running": False}


@router.post("/whatsapp/test")
async def send_test_message():
    """Send a test message via the configured channel (Telegram/WhatsApp)."""
    from src.algo_trader.whatsapp_notifier import send_message, _channel, _target
    import os

    if not os.getenv("OPENCLAW_ENABLED", "").lower() in ("true", "1", "yes"):
        return {"success": False, "message": "OPENCLAW_ENABLED is not set to true in .env"}
    channel = _channel()
    target = _target()
    if not target:
        env_var = "TELEGRAM_TARGET" if channel == "telegram" else "WHATSAPP_TARGET"
        return {"success": False, "message": f"{env_var} not set in .env"}

    ok = send_message(f"Test message from AI Hedge Fund algo trader via {channel.capitalize()}.")
    log_action("MSG_TEST", f"Test {channel} message {'sent' if ok else 'failed'}")
    return {"success": ok, "message": f"Test {channel} message sent to {target}" if ok else f"Failed to send — check openclaw {channel} setup"}


@router.get("/whatsapp/status")
async def messaging_status():
    """Get notification scheduler status and configured channel."""
    import os
    from src.algo_trader.whatsapp_notifier import _channel, _target
    return {
        "scheduler_running": _msg_scheduler_running,
        "enabled": os.getenv("OPENCLAW_ENABLED", "").lower() in ("true", "1", "yes"),
        "channel": _channel(),
        "target_set": bool(_target()),
    }
