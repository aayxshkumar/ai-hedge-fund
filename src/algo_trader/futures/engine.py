"""Futures backtest engine and batch runner."""

from __future__ import annotations

import json
import logging
import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.algo_trader.futures.portfolio import FuturesPortfolio
from src.algo_trader.futures.strategies import FUTURES_STRATEGY_REGISTRY

log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
FUTURES_RESULTS_FILE = RESULTS_DIR / "futures_backtest_results.json"

INDICES = [
    {"name": "NIFTY", "symbol": "^NSEI"},
    {"name": "BANKNIFTY", "symbol": "^NSEBANK"},
]


@dataclass
class EquityPoint:
    date: str
    value: float


@dataclass
class FuturesBacktestResult:
    strategy: str
    underlying: str
    period: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown_pct: float | None
    win_rate: float
    total_trades: int
    avg_pnl_per_trade: float
    equity_curve: list[EquityPoint] = field(default_factory=list)
    error: str | None = None
    instrument_type: str = "futures"

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "ticker": self.underlying,
            "period": self.period,
            "initial_capital": self.initial_capital,
            "final_value": round(self.final_value, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4) if self.sharpe_ratio is not None else None,
            "sortino_ratio": round(self.sortino_ratio, 4) if self.sortino_ratio is not None else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 4) if self.max_drawdown_pct is not None else None,
            "win_rate": round(self.win_rate, 4),
            "total_trades": self.total_trades,
            "avg_pnl_per_trade": round(self.avg_pnl_per_trade, 2),
            "equity_curve": [{"date": p.date, "value": round(p.value, 2)} for p in self.equity_curve],
            "error": self.error,
            "instrument_type": "futures",
        }


def _compute_metrics(equity_values: list[float], rf_annual: float = 0.07) -> dict:
    if len(equity_values) < 3:
        return {"sharpe": None, "sortino": None, "max_drawdown": None}

    arr = np.array(equity_values)
    returns = np.diff(arr) / arr[:-1]
    returns = returns[np.isfinite(returns)]

    if len(returns) < 2:
        return {"sharpe": None, "sortino": None, "max_drawdown": None}

    rf_daily = (1 + rf_annual) ** (1 / 252) - 1
    excess = returns - rf_daily
    mean_excess = float(np.mean(excess))
    std = float(np.std(returns, ddof=1))
    sharpe = (mean_excess / std * math.sqrt(252)) if std > 0 else None

    downside = returns[returns < rf_daily] - rf_daily
    down_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0
    sortino = (mean_excess / down_std * math.sqrt(252)) if down_std > 0 else None

    peak = arr[0]
    max_dd = 0.0
    for v in arr[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    return {"sharpe": sharpe, "sortino": sortino, "max_drawdown": max_dd}


MIN_WARMUP = 60


def run_futures_backtest(
    strategy_name: str,
    strategy_instance,
    price_df: pd.DataFrame,
    underlying: str,
    period_label: str,
    initial_capital: float = 10_00_000,
) -> FuturesBacktestResult:

    if price_df is None or price_df.empty or len(price_df) < MIN_WARMUP:
        return FuturesBacktestResult(
            strategy=strategy_name, underlying=underlying, period=period_label,
            initial_capital=initial_capital, final_value=initial_capital,
            total_return_pct=0, sharpe_ratio=None, sortino_ratio=None,
            max_drawdown_pct=None, win_rate=0, total_trades=0, avg_pnl_per_trade=0,
            error="Insufficient price data",
        )

    portfolio = FuturesPortfolio(initial_cash=initial_capital)
    equity_curve: list[EquityPoint] = []

    for i in range(MIN_WARMUP, len(price_df)):
        window = price_df.iloc[:i + 1]
        spot = float(window["close"].iloc[-1])
        date_str = str(window.index[-1])[:10]

        has_position = portfolio.position is not None
        position_side = portfolio.position.side if has_position else None

        try:
            signal = strategy_instance.analyse(window, has_position, position_side)
        except Exception:
            signal = None

        if signal:
            if signal.action == "close" and has_position:
                portfolio.close_position(date_str, spot)
            elif signal.action == "long" and not has_position and signal.confidence >= 0.3:
                portfolio.open_long(date_str, underlying, spot, signal.confidence)
            elif signal.action == "short" and not has_position and signal.confidence >= 0.3:
                portfolio.open_short(date_str, underlying, spot, signal.confidence)

        # Stop-loss: 3% of portfolio
        if portfolio.position:
            unrealized = portfolio.position.unrealized_pnl(spot)
            if unrealized < -initial_capital * 0.03:
                portfolio.close_position(date_str, spot)

        value = portfolio.portfolio_value(spot)
        equity_curve.append(EquityPoint(date=date_str, value=value))

    if portfolio.position:
        last_price = float(price_df["close"].iloc[-1])
        last_date = str(price_df.index[-1])[:10]
        portfolio.close_position(last_date, last_price)

    final_value = portfolio.cash
    total_return = (final_value - initial_capital) / initial_capital

    equity_values = [p.value for p in equity_curve]
    metrics = _compute_metrics(equity_values)

    pnls = [t.pnl for t in portfolio.trades]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0

    if len(equity_curve) > 250:
        step = len(equity_curve) // 250
        equity_curve = equity_curve[::step] + [equity_curve[-1]]

    return FuturesBacktestResult(
        strategy=strategy_name,
        underlying=underlying,
        period=period_label,
        initial_capital=initial_capital,
        final_value=final_value,
        total_return_pct=total_return,
        sharpe_ratio=metrics["sharpe"],
        sortino_ratio=metrics["sortino"],
        max_drawdown_pct=metrics["max_drawdown"],
        win_rate=portfolio.win_rate,
        total_trades=portfolio.total_trades,
        avg_pnl_per_trade=avg_pnl,
        equity_curve=equity_curve,
    )


# ── Batch Runner ──

@dataclass
class FuturesBatchConfig:
    indices: list[dict] = field(default_factory=lambda: INDICES[:])
    strategy_names: list[str] = field(default_factory=lambda: list(FUTURES_STRATEGY_REGISTRY.keys()))
    periods: list[dict] = field(default_factory=lambda: [
        {"label": "6M", "months": 6},
        {"label": "1Y", "months": 12},
    ])
    initial_capital: float = 10_00_000
    max_workers: int = 4

    @property
    def total_jobs(self) -> int:
        return len(self.strategy_names) * len(self.indices) * len(self.periods)


@dataclass
class FuturesBatchProgress:
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_strategy: str = ""
    current_index: str = ""
    start_time: float = 0.0

    @property
    def pct(self) -> float:
        return self.completed / self.total * 100 if self.total else 0

    @property
    def elapsed_sec(self) -> float:
        return time.time() - self.start_time if self.start_time else 0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "pct": round(self.pct, 1),
            "elapsed_sec": round(self.elapsed_sec, 1),
            "current_strategy": self.current_strategy,
            "current_index": self.current_index,
        }


_futures_progress = FuturesBatchProgress()
_futures_running = False


def get_futures_progress() -> FuturesBatchProgress:
    return _futures_progress


def is_futures_running() -> bool:
    return _futures_running


def _fetch_index_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(start=start_date, end=end_date, auto_adjust=True)
        if hist.empty:
            return None
        df = hist.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        log.debug("Index fetch failed for %s: %s", symbol, e)
        return None


def _run_one_futures_job(args: tuple) -> dict:
    strategy_name, index_name, symbol, period_label, months, initial_capital = args
    try:
        cls, _desc = FUTURES_STRATEGY_REGISTRY[strategy_name]
        strategy = cls()

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

        df = _fetch_index_data(symbol, start_date, end_date)
        result = run_futures_backtest(
            strategy_name=strategy_name,
            strategy_instance=strategy,
            price_df=df,
            underlying=index_name,
            period_label=period_label,
            initial_capital=initial_capital,
        )
        return result.to_dict()
    except Exception as e:
        return FuturesBacktestResult(
            strategy=strategy_name, underlying=index_name, period=period_label,
            initial_capital=initial_capital, final_value=initial_capital,
            total_return_pct=0, sharpe_ratio=None, sortino_ratio=None,
            max_drawdown_pct=None, win_rate=0, total_trades=0, avg_pnl_per_trade=0,
            error=str(e),
        ).to_dict()


def run_futures_batch(config: FuturesBatchConfig | None = None) -> list[dict]:
    global _futures_progress, _futures_running

    if _futures_running:
        raise RuntimeError("A futures batch is already running")

    cfg = config or FuturesBatchConfig()
    _futures_running = True
    _futures_progress = FuturesBatchProgress(total=cfg.total_jobs, start_time=time.time())

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    jobs = []
    for strategy_name in cfg.strategy_names:
        for idx in cfg.indices:
            for period in cfg.periods:
                jobs.append((
                    strategy_name, idx["name"], idx["symbol"],
                    period["label"], period["months"], cfg.initial_capital,
                ))

    results: list[dict] = []

    try:
        with ProcessPoolExecutor(max_workers=cfg.max_workers) as pool:
            futures_map = {pool.submit(_run_one_futures_job, job): job for job in jobs}
            for future in as_completed(futures_map):
                job = futures_map[future]
                _futures_progress.current_strategy = job[0]
                _futures_progress.current_index = job[1]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    _futures_progress.failed += 1
                    log.error("Futures job %s failed: %s", job, e)
                _futures_progress.completed += 1

        with open(FUTURES_RESULTS_FILE, "w") as f:
            json.dump(results, f)

    finally:
        _futures_running = False

    return results


def load_futures_results() -> list[dict]:
    if FUTURES_RESULTS_FILE.exists():
        with open(FUTURES_RESULTS_FILE) as f:
            return json.load(f)
    return []


def get_futures_summary(results: list[dict] | None = None) -> list[dict]:
    data = results or load_futures_results()
    if not data:
        return []

    from collections import defaultdict

    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for r in data:
        if r.get("error"):
            continue
        by_strategy[r["strategy"]].append(r)

    summaries = []
    for name, items in by_strategy.items():
        returns = [r["total_return_pct"] for r in items]
        sharpes = [r["sharpe_ratio"] for r in items if r["sharpe_ratio"] is not None]
        win_rates = [r["win_rate"] for r in items]
        trades = [r["total_trades"] for r in items]
        avg_pnls = [r.get("avg_pnl_per_trade", 0) for r in items]

        summaries.append({
            "strategy": name,
            "description": FUTURES_STRATEGY_REGISTRY.get(name, (None, ""))[1],
            "backtests": len(items),
            "avg_return_pct": round(float(np.mean(returns)), 4) if returns else 0,
            "median_return_pct": round(float(np.median(returns)), 4) if returns else 0,
            "best_return_pct": round(float(max(returns)), 4) if returns else 0,
            "worst_return_pct": round(float(min(returns)), 4) if returns else 0,
            "avg_sharpe": round(float(np.mean(sharpes)), 4) if sharpes else None,
            "avg_win_rate": round(float(np.mean(win_rates)), 4) if win_rates else 0,
            "avg_trades": round(float(np.mean(trades)), 1) if trades else 0,
            "avg_pnl_per_trade": round(float(np.mean(avg_pnls)), 2) if avg_pnls else 0,
            "profitable_pct": round(sum(1 for r in returns if r > 0) / len(returns), 4) if returns else 0,
            "instrument_type": "futures",
        })

    summaries.sort(key=lambda s: s["avg_return_pct"], reverse=True)
    return summaries
