"""Futures portfolio simulator with margin-based trading.

Models Nifty/Bank Nifty futures with realistic costs:
  - Brokerage: Rs 20 per order (Zerodha F&O)
  - STT: 0.0125% on sell side
  - Exchange: 0.0019% (NSE)
  - GST: 18% on (brokerage + exchange)
  - SEBI: Rs 10 per crore
  - Stamp: 0.002% on buy side
  - SPAN margin: ~12-15% of contract value
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


FUTURES_CONFIG = {
    "NIFTY": {"lot_size": 25, "margin_pct": 0.12, "tick_size": 0.05},
    "BANKNIFTY": {"lot_size": 15, "margin_pct": 0.15, "tick_size": 0.05},
}


@dataclass
class FuturesPosition:
    underlying: str
    side: Literal["long", "short"]
    lots: int
    lot_size: int
    entry_price: float
    margin_blocked: float

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    def unrealized_pnl(self, current_price: float) -> float:
        multiplier = 1 if self.side == "long" else -1
        return multiplier * (current_price - self.entry_price) * self.quantity


@dataclass
class FuturesTrade:
    date: str
    underlying: str
    side: str
    lots: int
    entry_price: float
    exit_price: float
    pnl: float
    charges: float


class FuturesPortfolio:

    BROKERAGE_PER_ORDER = 20.0
    STT_SELL_PCT = 0.000125
    EXCHANGE_PCT = 0.000019
    GST_PCT = 0.18
    STAMP_BUY_PCT = 0.00002
    SEBI_PER_CRORE = 10.0
    SLIPPAGE_PCT = 0.0003

    def __init__(self, initial_cash: float = 10_00_000):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.position: FuturesPosition | None = None
        self.trades: list[FuturesTrade] = []
        self._wins = 0
        self._losses = 0

    @property
    def win_rate(self) -> float:
        total = self._wins + self._losses
        return self._wins / total if total > 0 else 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    def _charges(self, turnover: float, is_sell: bool = False) -> float:
        brokerage = self.BROKERAGE_PER_ORDER
        stt = turnover * self.STT_SELL_PCT if is_sell else 0
        exchange = turnover * self.EXCHANGE_PCT
        gst = (brokerage + exchange) * self.GST_PCT
        sebi = turnover / 1e7 * self.SEBI_PER_CRORE
        stamp = turnover * self.STAMP_BUY_PCT if not is_sell else 0
        return brokerage + stt + exchange + gst + sebi + stamp

    def open_long(self, date: str, underlying: str, price: float, confidence: float = 0.5) -> bool:
        if self.position:
            return False

        cfg = FUTURES_CONFIG.get(underlying, FUTURES_CONFIG["NIFTY"])
        lot_size = cfg["lot_size"]
        margin_pct = cfg["margin_pct"]

        exec_price = price * (1 + self.SLIPPAGE_PCT)
        margin_per_lot = exec_price * lot_size * margin_pct
        max_lots = int(self.cash * min(max(confidence, 0.3), 0.8) / margin_per_lot)

        if max_lots <= 0:
            return False

        lots = min(max_lots, 3)
        margin = margin_per_lot * lots
        turnover = exec_price * lot_size * lots
        charges = self._charges(turnover)

        if margin + charges > self.cash:
            return False

        self.cash -= charges
        self.position = FuturesPosition(
            underlying=underlying, side="long", lots=lots,
            lot_size=lot_size, entry_price=exec_price, margin_blocked=margin,
        )
        return True

    def open_short(self, date: str, underlying: str, price: float, confidence: float = 0.5) -> bool:
        if self.position:
            return False

        cfg = FUTURES_CONFIG.get(underlying, FUTURES_CONFIG["NIFTY"])
        lot_size = cfg["lot_size"]
        margin_pct = cfg["margin_pct"]

        exec_price = price * (1 - self.SLIPPAGE_PCT)
        margin_per_lot = exec_price * lot_size * margin_pct
        max_lots = int(self.cash * min(max(confidence, 0.3), 0.8) / margin_per_lot)

        if max_lots <= 0:
            return False

        lots = min(max_lots, 3)
        margin = margin_per_lot * lots
        turnover = exec_price * lot_size * lots
        charges = self._charges(turnover)

        if margin + charges > self.cash:
            return False

        self.cash -= charges
        self.position = FuturesPosition(
            underlying=underlying, side="short", lots=lots,
            lot_size=lot_size, entry_price=exec_price, margin_blocked=margin,
        )
        return True

    def close_position(self, date: str, price: float) -> float:
        if not self.position:
            return 0.0

        pos = self.position
        if pos.side == "long":
            exec_price = price * (1 - self.SLIPPAGE_PCT)
        else:
            exec_price = price * (1 + self.SLIPPAGE_PCT)

        pnl = pos.unrealized_pnl(exec_price)
        turnover = exec_price * pos.quantity
        charges = self._charges(turnover, is_sell=True)
        net_pnl = pnl - charges

        self.cash += net_pnl
        if net_pnl > 0:
            self._wins += 1
        else:
            self._losses += 1

        self.trades.append(FuturesTrade(
            date=date, underlying=pos.underlying, side=pos.side,
            lots=pos.lots, entry_price=pos.entry_price,
            exit_price=exec_price, pnl=round(net_pnl, 2), charges=round(charges, 2),
        ))
        self.position = None
        return net_pnl

    def portfolio_value(self, current_price: float) -> float:
        if not self.position:
            return self.cash
        return self.cash + self.position.unrealized_pnl(current_price)
