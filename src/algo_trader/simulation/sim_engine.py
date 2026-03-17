"""Strategy backtest simulation engine.

Runs a single strategy on a single ticker over a date range using the
SimPortfolio for realistic cost modelling.  Designed to be called thousands
of times in parallel by the batch runner.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.algo_trader.simulation.sim_portfolio import SimPortfolio

log = logging.getLogger(__name__)


@dataclass
class EquityPoint:
    date: str
    value: float


@dataclass
class BacktestResult:
    strategy: str
    ticker: str
    period: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown_pct: float | None
    win_rate: float
    total_trades: int
    avg_holding_days: float
    equity_curve: list[EquityPoint] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "ticker": self.ticker,
            "period": self.period,
            "initial_capital": self.initial_capital,
            "final_value": round(self.final_value, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4) if self.sharpe_ratio is not None else None,
            "sortino_ratio": round(self.sortino_ratio, 4) if self.sortino_ratio is not None else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 4) if self.max_drawdown_pct is not None else None,
            "win_rate": round(self.win_rate, 4),
            "total_trades": self.total_trades,
            "avg_holding_days": round(self.avg_holding_days, 1),
            "equity_curve": [{"date": p.date, "value": round(p.value, 2)} for p in self.equity_curve],
            "error": self.error,
        }


def _compute_metrics(equity_values: list[float], rf_annual: float = 0.07) -> dict:
    """Compute Sharpe, Sortino, and max drawdown from daily portfolio values."""
    if len(equity_values) < 3:
        return {"sharpe": None, "sortino": None, "max_drawdown": None}

    arr = np.array(equity_values)
    returns = np.diff(arr) / arr[:-1]
    returns = returns[np.isfinite(returns)]

    if len(returns) < 2:
        return {"sharpe": None, "sortino": None, "max_drawdown": None}

    rf_daily = (1 + rf_annual) ** (1 / 252) - 1
    excess = returns - rf_daily
    mean_excess = np.mean(excess)
    std = np.std(returns, ddof=1)
    sharpe = (mean_excess / std * math.sqrt(252)) if std > 0 else None

    downside = returns[returns < rf_daily] - rf_daily
    down_std = np.std(downside, ddof=1) if len(downside) > 1 else 0
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


MIN_WARMUP_BARS = 60


def run_single_backtest(
    strategy_name: str,
    strategy_instance,
    price_df: pd.DataFrame,
    ticker: str,
    period_label: str,
    initial_capital: float = 10_00_000,
) -> BacktestResult:
    """Run one strategy on one ticker's price data and return full results."""

    if price_df is None or price_df.empty or len(price_df) < MIN_WARMUP_BARS:
        return BacktestResult(
            strategy=strategy_name, ticker=ticker, period=period_label,
            initial_capital=initial_capital, final_value=initial_capital,
            total_return_pct=0, sharpe_ratio=None, sortino_ratio=None,
            max_drawdown_pct=None, win_rate=0, total_trades=0, avg_holding_days=0,
            error="Insufficient price data",
        )

    portfolio = SimPortfolio(initial_cash=initial_capital)
    equity_curve: list[EquityPoint] = []
    holding_days: list[int] = []
    entry_day_idx: int | None = None

    for i in range(MIN_WARMUP_BARS, len(price_df)):
        window = price_df.iloc[: i + 1]
        curr_price = window["close"].iloc[-1]
        date_str = str(window.index[-1])[:10] if hasattr(window.index[-1], 'strftime') else str(window.index[-1])[:10]

        try:
            result = strategy_instance.analyse(window)
        except Exception:
            result = {"signal": "hold", "confidence": 0.0}

        signal = result.get("signal", "hold")
        confidence = result.get("confidence", 0.0)

        if signal == "buy" and confidence >= 0.25 and portfolio.position.quantity == 0:
            if portfolio.buy(date_str, ticker, curr_price, confidence):
                entry_day_idx = i
        elif signal == "sell" and portfolio.position.quantity > 0:
            portfolio.sell(date_str, ticker, curr_price)
            if entry_day_idx is not None:
                holding_days.append(i - entry_day_idx)
                entry_day_idx = None

        value = portfolio.portfolio_value(curr_price)
        equity_curve.append(EquityPoint(date=date_str, value=value))

    # Force close at end if still holding
    if portfolio.position.quantity > 0:
        last_price = price_df["close"].iloc[-1]
        last_date = str(price_df.index[-1])[:10]
        portfolio.sell(last_date, ticker, last_price)
        if entry_day_idx is not None:
            holding_days.append(len(price_df) - 1 - entry_day_idx)

    final_value = portfolio.cash
    total_return = (final_value - initial_capital) / initial_capital

    equity_values = [p.value for p in equity_curve]
    metrics = _compute_metrics(equity_values)

    # Downsample equity curve to max ~250 points for storage efficiency
    if len(equity_curve) > 250:
        step = len(equity_curve) // 250
        equity_curve = equity_curve[::step] + [equity_curve[-1]]

    return BacktestResult(
        strategy=strategy_name,
        ticker=ticker,
        period=period_label,
        initial_capital=initial_capital,
        final_value=final_value,
        total_return_pct=total_return,
        sharpe_ratio=metrics["sharpe"],
        sortino_ratio=metrics["sortino"],
        max_drawdown_pct=metrics["max_drawdown"],
        win_rate=portfolio.win_rate,
        total_trades=portfolio.total_trades,
        avg_holding_days=sum(holding_days) / len(holding_days) if holding_days else 0,
        equity_curve=equity_curve,
    )
