"""Batch runner for options backtesting across strategies and indices."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.algo_trader.options.strategies import OPTIONS_STRATEGY_REGISTRY
from src.algo_trader.options.engine import OptionsBacktestResult, run_options_backtest

log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
OPTIONS_RESULTS_FILE = RESULTS_DIR / "options_backtest_results.json"

INDICES = [
    {"name": "NIFTY", "symbol": "^NSEI"},
    {"name": "BANKNIFTY", "symbol": "^NSEBANK"},
]


@dataclass
class OptionsBatchConfig:
    indices: list[dict] = field(default_factory=lambda: INDICES[:])
    strategy_names: list[str] = field(default_factory=lambda: list(OPTIONS_STRATEGY_REGISTRY.keys()))
    periods: list[dict] = field(default_factory=lambda: [
        {"label": "6M", "months": 6},
        {"label": "1Y", "months": 12},
    ])
    initial_capital: float = 10_00_000
    max_workers: int = 4
    expiry_cycle: str = "weekly"

    @property
    def total_jobs(self) -> int:
        return len(self.strategy_names) * len(self.indices) * len(self.periods)


@dataclass
class OptionsBatchProgress:
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
            "current_index": self.current_index,
        }


_options_progress = OptionsBatchProgress()
_options_running = False


def get_options_progress() -> OptionsBatchProgress:
    return _options_progress


def is_options_running() -> bool:
    return _options_running


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


def _run_one_options_job(args: tuple) -> dict:
    strategy_name, index_name, symbol, period_label, months, initial_capital, expiry_days = args
    try:
        cls, _desc = OPTIONS_STRATEGY_REGISTRY[strategy_name]
        strategy = cls()

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

        df = _fetch_index_data(symbol, start_date, end_date)
        result = run_options_backtest(
            strategy_name=strategy_name,
            strategy_instance=strategy,
            price_df=df,
            underlying=index_name,
            period_label=period_label,
            initial_capital=initial_capital,
            expiry_cycle_days=expiry_days,
        )
        return result.to_dict()
    except Exception as e:
        return OptionsBacktestResult(
            strategy=strategy_name, underlying=index_name, period=period_label,
            initial_capital=initial_capital, final_value=initial_capital,
            total_return_pct=0, sharpe_ratio=None, sortino_ratio=None,
            max_drawdown_pct=None, win_rate=0, total_trades=0, avg_pnl_per_trade=0,
            error=str(e),
        ).to_dict()


def run_options_batch(config: OptionsBatchConfig | None = None) -> list[dict]:
    global _options_progress, _options_running

    if _options_running:
        raise RuntimeError("An options batch is already running")

    cfg = config or OptionsBatchConfig()
    _options_running = True
    _options_progress = OptionsBatchProgress(total=cfg.total_jobs, start_time=time.time())

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    expiry_days = 7 if cfg.expiry_cycle == "weekly" else 30

    jobs = []
    for strategy_name in cfg.strategy_names:
        for idx in cfg.indices:
            for period in cfg.periods:
                jobs.append((
                    strategy_name, idx["name"], idx["symbol"],
                    period["label"], period["months"],
                    cfg.initial_capital, expiry_days,
                ))

    results: list[dict] = []

    try:
        with ProcessPoolExecutor(max_workers=cfg.max_workers) as pool:
            futures = {pool.submit(_run_one_options_job, job): job for job in jobs}
            for future in as_completed(futures):
                job = futures[future]
                _options_progress.current_strategy = job[0]
                _options_progress.current_index = job[1]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    _options_progress.failed += 1
                    log.error("Options job %s failed: %s", job, e)
                _options_progress.completed += 1

        with open(OPTIONS_RESULTS_FILE, "w") as f:
            json.dump(results, f)
        log.info("Options batch complete: %d results saved", len(results))

    finally:
        _options_running = False

    return results


def load_options_results() -> list[dict]:
    if OPTIONS_RESULTS_FILE.exists():
        with open(OPTIONS_RESULTS_FILE) as f:
            return json.load(f)
    return []


def get_options_summary(results: list[dict] | None = None) -> list[dict]:
    data = results or load_options_results()
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
        win_rates = [r["win_rate"] for r in items]
        trades = [r["total_trades"] for r in items]
        avg_pnls = [r.get("avg_pnl_per_trade", 0) for r in items]

        summaries.append({
            "strategy": name,
            "description": OPTIONS_STRATEGY_REGISTRY.get(name, (None, ""))[1],
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
            "instrument_type": "options",
        })

    summaries.sort(key=lambda s: s["avg_return_pct"], reverse=True)
    return summaries
