"""Multi-leg options portfolio simulator.

Tracks open positions across multiple option legs with realistic
Indian market transaction costs for F&O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class OptionLeg:
    strike: float
    option_type: str  # "call" or "put"
    side: Literal["long", "short"]
    lots: int
    lot_size: int
    entry_premium: float
    current_premium: float = 0.0

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    @property
    def unrealized_pnl(self) -> float:
        multiplier = 1 if self.side == "long" else -1
        return multiplier * (self.current_premium - self.entry_premium) * self.quantity

    @property
    def cost(self) -> float:
        if self.side == "long":
            return self.entry_premium * self.quantity
        return 0  # Short positions receive premium


@dataclass
class OptionTrade:
    date: str
    strategy: str
    legs: list[dict]
    entry_cost: float
    exit_value: float
    pnl: float
    charges: float


class OptionsPortfolio:
    """Multi-leg options position tracker with F&O transaction costs.

    Costs (Zerodha F&O):
        Brokerage: Rs 20 per executed order
        STT: 0.0125% on sell side (options)
        Exchange: 0.053% (NSE F&O)
        GST: 18% on (brokerage + exchange)
        SEBI: Rs 10 per crore
        Stamp: 0.003% on buy side
    """

    BROKERAGE_PER_ORDER = 20.0
    STT_SELL_PCT = 0.000125
    EXCHANGE_PCT = 0.00053
    GST_PCT = 0.18
    STAMP_BUY_PCT = 0.00003
    SEBI_PER_CRORE = 10.0
    SLIPPAGE_PCT = 0.001

    def __init__(self, initial_cash: float = 10_00_000):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: list[OptionLeg] = []
        self.trades: list[OptionTrade] = []
        self._wins = 0
        self._losses = 0

    @property
    def win_rate(self) -> float:
        total = self._wins + self._losses
        return self._wins / total if total > 0 else 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    def _calculate_charges(self, turnover: float, num_legs: int, is_sell: bool = False) -> float:
        brokerage = self.BROKERAGE_PER_ORDER * num_legs
        stt = turnover * self.STT_SELL_PCT if is_sell else 0
        exchange = turnover * self.EXCHANGE_PCT
        gst = (brokerage + exchange) * self.GST_PCT
        sebi = turnover / 1e7 * self.SEBI_PER_CRORE
        stamp = turnover * self.STAMP_BUY_PCT if not is_sell else 0
        return brokerage + stt + exchange + gst + sebi + stamp

    def margin_required(self, legs: list[OptionLeg]) -> float:
        """Approximate SPAN margin for multi-leg positions."""
        max_risk = 0.0
        for leg in legs:
            if leg.side == "short":
                max_risk += leg.entry_premium * leg.quantity * 0.15
            else:
                max_risk += leg.entry_premium * leg.quantity

        # Multi-leg benefit (hedged positions require less margin)
        has_hedge = any(l.side == "long" for l in legs) and any(l.side == "short" for l in legs)
        if has_hedge:
            max_risk *= 0.4

        return max_risk

    def open_position(self, date: str, strategy: str, legs: list[OptionLeg]) -> bool:
        """Open a multi-leg options position."""
        net_cost = 0.0
        total_turnover = 0.0

        for leg in legs:
            premium_with_slip = leg.entry_premium * (1 + self.SLIPPAGE_PCT if leg.side == "long" else 1 - self.SLIPPAGE_PCT)
            leg.entry_premium = round(premium_with_slip, 2)
            turnover = leg.entry_premium * leg.quantity

            if leg.side == "long":
                net_cost += turnover
            else:
                net_cost -= turnover
            total_turnover += turnover

        charges = self._calculate_charges(total_turnover, len(legs))
        margin = self.margin_required(legs)
        required = max(net_cost, 0) + charges + margin

        if required > self.cash:
            return False

        self.cash -= (net_cost + charges)
        self.positions = legs
        return True

    def close_position(self, date: str, strategy: str, current_premiums: dict[tuple[float, str], float]) -> float:
        """Close all open legs at current premiums. Returns P&L."""
        if not self.positions:
            return 0.0

        exit_value = 0.0
        entry_cost = 0.0
        total_turnover = 0.0

        for leg in self.positions:
            key = (leg.strike, leg.option_type)
            current = current_premiums.get(key, leg.entry_premium)
            current_with_slip = current * (1 - self.SLIPPAGE_PCT if leg.side == "long" else 1 + self.SLIPPAGE_PCT)

            if leg.side == "long":
                entry_cost += leg.entry_premium * leg.quantity
                exit_value += current_with_slip * leg.quantity
            else:
                entry_cost -= leg.entry_premium * leg.quantity
                exit_value -= current_with_slip * leg.quantity

            total_turnover += abs(current_with_slip * leg.quantity)

        charges = self._calculate_charges(total_turnover, len(self.positions), is_sell=True)
        pnl = exit_value - entry_cost - charges

        self.cash += exit_value - charges
        if pnl > 0:
            self._wins += 1
        else:
            self._losses += 1

        self.trades.append(OptionTrade(
            date=date,
            strategy=strategy,
            legs=[{"strike": l.strike, "type": l.option_type, "side": l.side, "lots": l.lots, "entry": l.entry_premium}
                  for l in self.positions],
            entry_cost=round(entry_cost, 2),
            exit_value=round(exit_value, 2),
            pnl=round(pnl, 2),
            charges=round(charges, 2),
        ))
        self.positions = []
        return pnl

    def portfolio_value(self, current_premiums: dict[tuple[float, str], float] | None = None) -> float:
        """Current portfolio value including unrealized P&L."""
        if not self.positions or not current_premiums:
            return self.cash

        unrealized = 0.0
        for leg in self.positions:
            key = (leg.strike, leg.option_type)
            current = current_premiums.get(key, leg.entry_premium)
            multiplier = 1 if leg.side == "long" else -1
            unrealized += multiplier * (current - leg.entry_premium) * leg.quantity

        return self.cash + unrealized
