"""Options backtest simulation engine.

Runs a single options strategy on a single underlying index over a date range.
Generates synthetic option chains daily from underlying price data and
evaluates strategy signals.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.algo_trader.options.chain import generate_chain, compute_historical_volatility
from src.algo_trader.options.portfolio import OptionsPortfolio
from src.algo_trader.options.pricing import black_scholes

log = logging.getLogger(__name__)

WEEKLY_EXPIRY_DAYS = 7
MONTHLY_EXPIRY_DAYS = 30
EXIT_DTE = 1  # Close positions 1 day before expiry


@dataclass
class EquityPoint:
    date: str
    value: float


@dataclass
class OptionsBacktestResult:
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
    instrument_type: str = "options"

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
            "instrument_type": "options",
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


MIN_WARMUP_BARS = 60


def run_options_backtest(
    strategy_name: str,
    strategy_instance,
    price_df: pd.DataFrame,
    underlying: str,
    period_label: str,
    initial_capital: float = 10_00_000,
    expiry_cycle_days: int = WEEKLY_EXPIRY_DAYS,
) -> OptionsBacktestResult:
    """Run one options strategy on underlying index price data."""

    if price_df is None or price_df.empty or len(price_df) < MIN_WARMUP_BARS:
        return OptionsBacktestResult(
            strategy=strategy_name, underlying=underlying, period=period_label,
            initial_capital=initial_capital, final_value=initial_capital,
            total_return_pct=0, sharpe_ratio=None, sortino_ratio=None,
            max_drawdown_pct=None, win_rate=0, total_trades=0, avg_pnl_per_trade=0,
            error="Insufficient price data",
        )

    portfolio = OptionsPortfolio(initial_cash=initial_capital)
    equity_curve: list[EquityPoint] = []
    days_since_expiry = 0

    for i in range(MIN_WARMUP_BARS, len(price_df)):
        window = price_df.iloc[:i + 1]
        spot = float(window["close"].iloc[-1])
        date_str = str(window.index[-1])[:10]
        days_since_expiry += 1

        hist_vol = compute_historical_volatility(window["close"])
        dte = max(expiry_cycle_days - (days_since_expiry % expiry_cycle_days), 1)

        chain = generate_chain(underlying, spot, date_str, dte, hist_vol)

        # Build current premiums for valuation
        current_premiums: dict[tuple[float, str], float] = {}
        for c in chain.contracts:
            current_premiums[(c.strike, c.option_type)] = c.premium

        has_position = len(portfolio.positions) > 0

        # Auto-close near expiry
        if has_position and dte <= EXIT_DTE:
            portfolio.close_position(date_str, strategy_name, current_premiums)
            days_since_expiry = 0
            has_position = False

        # Check for stop-loss: close if unrealized loss > 50% of position cost
        if has_position:
            unrealized = portfolio.portfolio_value(current_premiums) - portfolio.cash
            entry_cost = sum(
                l.entry_premium * l.quantity for l in portfolio.positions if l.side == "long"
            )
            if entry_cost > 0 and unrealized < -entry_cost * 0.5:
                portfolio.close_position(date_str, strategy_name, current_premiums)
                has_position = False

        # Check strategy signal
        if not has_position:
            try:
                signal = strategy_instance.analyse(chain, window, has_position=False)
            except Exception:
                signal = None

            if signal and signal.action == "open" and signal.confidence >= 0.3:
                portfolio.open_position(date_str, strategy_name, signal.legs)

        value = portfolio.portfolio_value(current_premiums)
        equity_curve.append(EquityPoint(date=date_str, value=value))

    # Force close remaining positions
    if portfolio.positions:
        spot = float(price_df["close"].iloc[-1])
        date_str = str(price_df.index[-1])[:10]
        hist_vol = compute_historical_volatility(price_df["close"])
        chain = generate_chain(underlying, spot, date_str, 1, hist_vol)
        current_premiums = {(c.strike, c.option_type): c.premium for c in chain.contracts}
        portfolio.close_position(date_str, strategy_name, current_premiums)

    final_value = portfolio.cash
    total_return = (final_value - initial_capital) / initial_capital

    equity_values = [p.value for p in equity_curve]
    metrics = _compute_metrics(equity_values)

    pnls = [t.pnl for t in portfolio.trades]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0

    if len(equity_curve) > 250:
        step = len(equity_curve) // 250
        equity_curve = equity_curve[::step] + [equity_curve[-1]]

    return OptionsBacktestResult(
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
