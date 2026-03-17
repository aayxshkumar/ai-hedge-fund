"""Batch runner — orchestrates mass backtesting across strategies, tickers, and periods.

Uses ProcessPoolExecutor for parallel execution and streams progress via a
callback.  Results are persisted to a JSON file for the frontend to consume.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

from src.algo_trader.simulation.nifty50 import NIFTY_50
from src.algo_trader.simulation.sim_engine import BacktestResult, run_single_backtest
from src.algo_trader.strategies import STRATEGY_REGISTRY

log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
RESULTS_FILE = RESULTS_DIR / "backtest_results.json"


@dataclass
class BatchConfig:
    tickers: list[str] = field(default_factory=lambda: NIFTY_50[:])
    strategy_names: list[str] = field(default_factory=lambda: list(STRATEGY_REGISTRY.keys()))
    periods: list[dict] = field(default_factory=lambda: [
        {"label": "1Y", "months": 12},
        {"label": "6M", "months": 6},
    ])
    initial_capital: float = 10_00_000
    max_workers: int = 6

    @property
    def total_jobs(self) -> int:
        effective_strategies = [s for s in self.strategy_names if s != "pairs_trading"]
        return len(effective_strategies) * len(self.tickers) * len(self.periods)


@dataclass
class BatchProgress:
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_strategy: str = ""
    current_ticker: str = ""
    start_time: float = 0.0

    @property
    def pct(self) -> float:
        return self.completed / self.total * 100 if self.total else 0

    @property
    def elapsed_sec(self) -> float:
        return time.time() - self.start_time if self.start_time else 0

    @property
    def eta_sec(self) -> float:
        if self.completed == 0:
            return 0
        rate = self.elapsed_sec / self.completed
        return rate * (self.total - self.completed)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "pct": round(self.pct, 1),
            "elapsed_sec": round(self.elapsed_sec, 1),
            "eta_sec": round(self.eta_sec, 1),
            "current_strategy": self.current_strategy,
            "current_ticker": self.current_ticker,
        }


# Global progress shared with the API layer
_current_progress = BatchProgress()
_is_running = False


def get_progress() -> BatchProgress:
    return _current_progress


def is_running() -> bool:
    return _is_running


def _fetch_price_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """Fetch price data with in-process yfinance (safe for multiprocessing)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(start=start_date, end=end_date, auto_adjust=True)
        if hist.empty:
            return None
        df = hist.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        log.debug("Price fetch failed for %s: %s", ticker, e)
        return None


def _run_one_job(args: tuple) -> dict:
    """Worker function for process pool — runs one strategy/ticker/period combo."""
    strategy_name, ticker, period_label, months, initial_capital = args
    try:
        cls, _desc = STRATEGY_REGISTRY[strategy_name]
        strategy = cls()

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

        df = _fetch_price_data(ticker, start_date, end_date)
        result = run_single_backtest(
            strategy_name=strategy_name,
            strategy_instance=strategy,
            price_df=df,
            ticker=ticker,
            period_label=period_label,
            initial_capital=initial_capital,
        )
        return result.to_dict()
    except Exception as e:
        return BacktestResult(
            strategy=strategy_name, ticker=ticker, period=period_label,
            initial_capital=initial_capital, final_value=initial_capital,
            total_return_pct=0, sharpe_ratio=None, sortino_ratio=None,
            max_drawdown_pct=None, win_rate=0, total_trades=0,
            avg_holding_days=0, error=str(e),
        ).to_dict()


def run_batch(
    config: BatchConfig | None = None,
    progress_callback: Callable[[BatchProgress], None] | None = None,
) -> list[dict]:
    """Execute all backtests and return results.  Thread-safe for API usage."""
    global _current_progress, _is_running

    if _is_running:
        raise RuntimeError("A batch is already running")

    cfg = config or BatchConfig()
    _is_running = True
    _current_progress = BatchProgress(total=cfg.total_jobs, start_time=time.time())

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Skip pairs_trading for batch (needs two tickers)
    effective_strategies = [s for s in cfg.strategy_names if s != "pairs_trading"]

    jobs = []
    for strategy_name in effective_strategies:
        for ticker in cfg.tickers:
            for period in cfg.periods:
                jobs.append((strategy_name, ticker, period["label"], period["months"], cfg.initial_capital))

    results: list[dict] = []

    try:
        with ProcessPoolExecutor(max_workers=cfg.max_workers) as pool:
            futures = {pool.submit(_run_one_job, job): job for job in jobs}
            for future in as_completed(futures):
                job = futures[future]
                _current_progress.current_strategy = job[0]
                _current_progress.current_ticker = job[1]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    _current_progress.failed += 1
                    log.error("Job %s failed: %s", job, e)
                _current_progress.completed += 1
                if progress_callback:
                    progress_callback(_current_progress)

        # Persist results
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f)
        log.info("Batch complete: %d results saved to %s", len(results), RESULTS_FILE)

    finally:
        _is_running = False

    return results


def load_results() -> list[dict]:
    """Load previously computed results from disk."""
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return []


def get_strategy_summary(results: list[dict] | None = None) -> list[dict]:
    """Aggregate results by strategy for the comparison table."""
    data = results or load_results()
    if not data:
        return []

    import numpy as np
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
        sortinos = [r["sortino_ratio"] for r in items if r["sortino_ratio"] is not None]
        drawdowns = [r["max_drawdown_pct"] for r in items if r["max_drawdown_pct"] is not None]
        win_rates = [r["win_rate"] for r in items]
        trades = [r["total_trades"] for r in items]

        summaries.append({
            "strategy": name,
            "description": STRATEGY_REGISTRY.get(name, (None, ""))[1],
            "backtests": len(items),
            "avg_return_pct": round(float(np.mean(returns)), 4) if returns else 0,
            "median_return_pct": round(float(np.median(returns)), 4) if returns else 0,
            "best_return_pct": round(float(max(returns)), 4) if returns else 0,
            "worst_return_pct": round(float(min(returns)), 4) if returns else 0,
            "avg_sharpe": round(float(np.mean(sharpes)), 4) if sharpes else None,
            "avg_sortino": round(float(np.mean(sortinos)), 4) if sortinos else None,
            "avg_max_drawdown": round(float(np.mean(drawdowns)), 4) if drawdowns else None,
            "avg_win_rate": round(float(np.mean(win_rates)), 4) if win_rates else 0,
            "avg_trades": round(float(np.mean(trades)), 1) if trades else 0,
            "profitable_pct": round(sum(1 for r in returns if r > 0) / len(returns), 4) if returns else 0,
        })

    summaries.sort(key=lambda s: s["avg_return_pct"], reverse=True)
    return summaries
