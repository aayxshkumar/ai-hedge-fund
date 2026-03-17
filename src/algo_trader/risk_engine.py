"""Risk management engine — enforces guardrails before any order reaches the broker.

Inspired by NautilusTrader's pre-trade risk engine pattern: every order passes
through validation checks before it can be submitted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from src.algo_trader.config import AlgoTraderConfig
from src.algo_trader.executor import Order, OrderSide, Position

log = logging.getLogger(__name__)


@dataclass
class DailyPnL:
    """Tracks intraday profit/loss for drawdown guard."""

    date: date = field(default_factory=date.today)
    realized: float = 0.0
    unrealized: float = 0.0

    @property
    def total(self) -> float:
        return self.realized + self.unrealized

    def reset_if_new_day(self):
        today = date.today()
        if self.date != today:
            self.date = today
            self.realized = 0.0
            self.unrealized = 0.0


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str = ""


class RiskEngine:
    """Pre-trade validation and portfolio-level risk monitoring."""

    def __init__(self, config: AlgoTraderConfig):
        self.config = config.risk
        self.daily_pnl = DailyPnL()
        self._order_log: list[dict] = []

    def check_order(
        self,
        order: Order,
        portfolio_value: float,
        available_cash: float,
        positions: list[Position],
        current_price: float,
        is_exit: bool = False,
    ) -> RiskCheckResult:
        """Run all pre-trade checks. Returns approval or rejection with reason.

        Protective exits (stop-loss, take-profit) pass ``is_exit=True`` to skip
        daily-drawdown and concentration checks -- blocking an exit would only
        deepen the loss the stop was designed to prevent.
        """
        self.daily_pnl.reset_if_new_day()

        checks: list[RiskCheckResult] = []
        if not is_exit:
            checks.append(self._check_daily_drawdown(portfolio_value))
        checks.extend([
            self._check_single_order_size(order, current_price),
            self._check_position_concentration(order, portfolio_value, positions, current_price),
            self._check_portfolio_exposure(order, portfolio_value, positions, current_price),
            self._check_open_position_count(order, positions),
            self._check_available_margin(order, available_cash, current_price),
        ])

        for result in checks:
            if not result.approved:
                log.warning("RISK REJECTED: %s %s — %s", order.side.value, order.ticker, result.reason)
                return result

        log.info("RISK APPROVED: %s %s x%d", order.side.value, order.ticker, order.quantity)
        return RiskCheckResult(approved=True, reason="All checks passed")

    def update_daily_pnl(self, realized: float = 0.0, unrealized: float = 0.0):
        self.daily_pnl.reset_if_new_day()
        self.daily_pnl.realized = realized
        self.daily_pnl.unrealized = unrealized

    def calculate_position_size(
        self,
        ticker: str,
        side: OrderSide,
        portfolio_value: float,
        current_price: float,
        signal_confidence: float = 0.5,
    ) -> int:
        """Kelly-criterion-inspired position sizing scaled by signal confidence.

        Returns the number of shares to trade, respecting all risk limits.
        """
        if current_price <= 0 or portfolio_value <= 0:
            return 0

        max_allocation = portfolio_value * self.config.max_position_pct
        confidence_scaled = max_allocation * min(max(signal_confidence, 0.1), 1.0)
        order_value = min(confidence_scaled, self.config.max_single_order_value)
        shares = int(order_value / current_price)

        return max(shares, 0)

    def should_stop_loss(self, position: Position) -> bool:
        if position.quantity == 0 or position.average_price == 0:
            return False
        pnl_pct = (position.last_price - position.average_price) / position.average_price
        if position.quantity > 0:
            return pnl_pct <= -self.config.stop_loss_pct
        else:
            return pnl_pct >= self.config.stop_loss_pct

    def should_take_profit(self, position: Position) -> bool:
        if position.quantity == 0 or position.average_price == 0:
            return False
        pnl_pct = (position.last_price - position.average_price) / position.average_price
        if position.quantity > 0:
            return pnl_pct >= self.config.take_profit_pct
        else:
            return pnl_pct <= -self.config.take_profit_pct

    # ── Individual checks ────────────────────────────────────────────

    def _check_daily_drawdown(self, portfolio_value: float) -> RiskCheckResult:
        if portfolio_value <= 0:
            return RiskCheckResult(approved=False, reason="Portfolio value is zero")
        loss_pct = abs(min(self.daily_pnl.total, 0)) / portfolio_value
        if loss_pct >= self.config.max_daily_loss_pct:
            return RiskCheckResult(
                approved=False,
                reason=f"Daily loss {loss_pct:.1%} exceeds limit {self.config.max_daily_loss_pct:.1%}",
            )
        return RiskCheckResult(approved=True)

    def _check_single_order_size(self, order: Order, price: float) -> RiskCheckResult:
        value = order.quantity * price
        if value > self.config.max_single_order_value:
            return RiskCheckResult(
                approved=False,
                reason=f"Order value ₹{value:,.0f} exceeds single-order limit ₹{self.config.max_single_order_value:,.0f}",
            )
        return RiskCheckResult(approved=True)

    def _check_position_concentration(
        self, order: Order, portfolio_value: float, positions: list[Position], price: float
    ) -> RiskCheckResult:
        existing_value = sum(
            abs(p.quantity) * p.last_price for p in positions if p.ticker == order.ticker
        )
        order_value = order.quantity * price
        if order.side == OrderSide.SELL:
            new_value = max(existing_value - order_value, 0)
        else:
            new_value = existing_value + order_value
        concentration = new_value / portfolio_value if portfolio_value > 0 else 1.0
        if concentration > self.config.max_position_pct:
            return RiskCheckResult(
                approved=False,
                reason=f"Position in {order.ticker} would be {concentration:.1%} of portfolio (limit {self.config.max_position_pct:.1%})",
            )
        return RiskCheckResult(approved=True)

    def _check_portfolio_exposure(
        self, order: Order, portfolio_value: float, positions: list[Position], price: float
    ) -> RiskCheckResult:
        total_exposure = sum(abs(p.quantity) * p.last_price for p in positions)
        order_value = order.quantity * price
        if order.side == OrderSide.SELL:
            new_exposure = max(total_exposure - order_value, 0)
        else:
            new_exposure = total_exposure + order_value
        exposure_pct = new_exposure / portfolio_value if portfolio_value > 0 else 1.0
        if exposure_pct > self.config.max_portfolio_exposure:
            return RiskCheckResult(
                approved=False,
                reason=f"Total exposure {exposure_pct:.1%} would exceed limit {self.config.max_portfolio_exposure:.1%}",
            )
        return RiskCheckResult(approved=True)

    def _check_open_position_count(self, order: Order, positions: list[Position]) -> RiskCheckResult:
        unique_tickers = {p.ticker for p in positions if p.quantity != 0}
        if order.side == OrderSide.BUY and order.ticker not in unique_tickers:
            if len(unique_tickers) >= self.config.max_open_positions:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Already at max {self.config.max_open_positions} open positions",
                )
        return RiskCheckResult(approved=True)

    def _check_available_margin(self, order: Order, available_cash: float, price: float) -> RiskCheckResult:
        if order.side == OrderSide.BUY:
            required = order.quantity * price
            if required > available_cash:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Insufficient funds: need ₹{required:,.0f}, have ₹{available_cash:,.0f}",
                )
        return RiskCheckResult(approved=True)

    # ── F&O risk checks ──────────────────────────────────────────

    def check_fno_order(
        self,
        instrument_type: str,
        underlying: str,
        lots: int,
        lot_size: int,
        price: float,
        portfolio_value: float,
        available_cash: float,
        fno_exposure: float = 0.0,
        margin_pct: float = 0.12,
    ) -> RiskCheckResult:
        """Validate an F&O order against risk limits."""
        self.daily_pnl.reset_if_new_day()

        # Daily drawdown
        if portfolio_value > 0:
            loss_pct = abs(min(self.daily_pnl.total, 0)) / portfolio_value
            if loss_pct >= self.config.max_daily_loss_pct:
                return RiskCheckResult(approved=False, reason="Daily loss limit reached")

        notional = lots * lot_size * price

        # F&O exposure limit
        new_exposure = fno_exposure + notional
        if portfolio_value > 0:
            exp_pct = new_exposure / portfolio_value
            if exp_pct > self.config.max_fno_exposure_pct:
                return RiskCheckResult(
                    approved=False,
                    reason=f"F&O exposure {exp_pct:.1%} exceeds limit {self.config.max_fno_exposure_pct:.1%}",
                )

        # Max lots per underlying
        if lots > self.config.max_lots_per_underlying:
            return RiskCheckResult(
                approved=False,
                reason=f"Lots {lots} exceed max {self.config.max_lots_per_underlying} per underlying",
            )

        # Margin check for futures
        if instrument_type == "futures":
            margin_needed = notional * margin_pct
            if margin_needed > available_cash:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Insufficient margin: need ₹{margin_needed:,.0f}, have ₹{available_cash:,.0f}",
                )

        # Premium risk check for options
        if instrument_type == "options":
            premium_cost = lots * lot_size * price
            if premium_cost > self.config.max_premium_risk_per_trade:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Premium ₹{premium_cost:,.0f} exceeds limit ₹{self.config.max_premium_risk_per_trade:,.0f}",
                )

        log.info("F&O RISK APPROVED: %s %s x%d lots", instrument_type, underlying, lots)
        return RiskCheckResult(approved=True, reason="All F&O checks passed")

    def calculate_options_size(
        self, portfolio_value: float, premium: float, confidence: float = 0.5,
    ) -> int:
        """Position sizing for options based on max premium risk."""
        if premium <= 0 or portfolio_value <= 0:
            return 0
        max_risk = min(
            self.config.max_premium_risk_per_trade,
            portfolio_value * self.config.max_position_pct,
        )
        scaled = max_risk * min(max(confidence, 0.1), 1.0)
        return max(int(scaled / premium), 0)

    def calculate_futures_size(
        self, portfolio_value: float, price: float, lot_size: int,
        margin_pct: float = 0.12, confidence: float = 0.5,
    ) -> int:
        """Position sizing for futures based on margin requirements."""
        if price <= 0 or lot_size <= 0 or portfolio_value <= 0:
            return 0
        margin_per_lot = price * lot_size * margin_pct
        max_allocation = portfolio_value * self.config.max_position_pct * min(max(confidence, 0.1), 1.0)
        return max(int(max_allocation / margin_per_lot), 0)
