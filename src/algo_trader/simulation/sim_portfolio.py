"""Lightweight portfolio simulator with realistic Indian-market transaction costs.

Costs modelled (Zerodha-like):
  - Brokerage:  0 for delivery, 0.03% or Rs 20 per executed order for intraday
  - STT:        0.1% on sell side (delivery), 0.025% on sell side (intraday)
  - Exchange:   0.00345% (NSE)
  - GST:        18% on brokerage + exchange charges
  - SEBI:       Rs 10 per crore
  - Stamp:      0.015% on buy side (delivery)
  - Slippage:   configurable (default 0.05%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SimPosition:
    quantity: int = 0
    avg_price: float = 0.0
    invested: float = 0.0


@dataclass
class SimTrade:
    date: str
    ticker: str
    side: Literal["buy", "sell"]
    quantity: int
    price: float
    cost: float
    slippage: float


class SimPortfolio:
    """Single-stock-per-backtest portfolio tracker with transaction costs."""

    BROKERAGE_PCT = 0.0003      # 0.03% (delivery is actually 0, we use this as conservative estimate)
    STT_SELL_PCT = 0.001        # 0.1% on sell
    EXCHANGE_PCT = 0.0000345    # 0.00345%
    GST_PCT = 0.18              # 18% on (brokerage + exchange)
    STAMP_BUY_PCT = 0.00015     # 0.015% on buy
    SEBI_PER_CRORE = 10.0

    def __init__(self, initial_cash: float = 10_00_000, slippage_pct: float = 0.0005, max_position_pct: float = 1.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.slippage_pct = slippage_pct
        self.max_position_pct = max_position_pct
        self.position = SimPosition()
        self.trades: list[SimTrade] = []
        self.realized_pnl = 0.0
        self._wins = 0
        self._losses = 0

    @property
    def win_rate(self) -> float:
        total = self._wins + self._losses
        return self._wins / total if total > 0 else 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    def portfolio_value(self, current_price: float) -> float:
        return self.cash + self.position.quantity * current_price

    def buy(self, date: str, ticker: str, price: float, confidence: float = 0.5) -> bool:
        if self.position.quantity > 0:
            return False
        exec_price = price * (1 + self.slippage_pct)
        max_invest = self.cash * self.max_position_pct * min(max(confidence, 0.2), 1.0)
        cost_per_share = exec_price * (1 + self.BROKERAGE_PCT + self.STAMP_BUY_PCT + self.EXCHANGE_PCT)
        gst = exec_price * (self.BROKERAGE_PCT + self.EXCHANGE_PCT) * self.GST_PCT
        total_per_share = cost_per_share + gst
        if total_per_share <= 0:
            return False
        qty = int(max_invest / total_per_share)
        if qty <= 0:
            return False
        total_cost = qty * total_per_share
        slippage_amount = qty * price * self.slippage_pct
        if total_cost > self.cash:
            qty = int(self.cash / total_per_share)
            if qty <= 0:
                return False
            total_cost = qty * total_per_share
            slippage_amount = qty * price * self.slippage_pct
        self.cash -= total_cost
        self.position.quantity = qty
        self.position.avg_price = exec_price
        self.position.invested = total_cost
        self.trades.append(SimTrade(date=date, ticker=ticker, side="buy", quantity=qty, price=exec_price, cost=total_cost - qty * exec_price, slippage=slippage_amount))
        return True

    def sell(self, date: str, ticker: str, price: float) -> bool:
        if self.position.quantity <= 0:
            return False
        exec_price = price * (1 - self.slippage_pct)
        qty = self.position.quantity
        gross = qty * exec_price
        brokerage = gross * self.BROKERAGE_PCT
        stt = gross * self.STT_SELL_PCT
        exchange = gross * self.EXCHANGE_PCT
        gst = (brokerage + exchange) * self.GST_PCT
        sebi = gross / 1_00_00_000 * self.SEBI_PER_CRORE
        total_charges = brokerage + stt + exchange + gst + sebi
        net = gross - total_charges
        slippage_amount = qty * price * self.slippage_pct
        pnl = net - self.position.invested
        self.realized_pnl += pnl
        if pnl > 0:
            self._wins += 1
        else:
            self._losses += 1
        self.cash += net
        self.position = SimPosition()
        self.trades.append(SimTrade(date=date, ticker=ticker, side="sell", quantity=qty, price=exec_price, cost=total_charges, slippage=slippage_amount))
        return True
