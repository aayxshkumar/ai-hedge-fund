"""Fill model — slippage and transaction cost estimation for Indian markets.

Implements Zerodha's fee schedule (equity delivery & intraday):
  - Brokerage:  ₹20 per executed order (or 0.03% whichever is lower for intraday)
  - STT:        0.1% on buy+sell (delivery) / 0.025% on sell (intraday)
  - Exchange:   0.00345% (NSE) / 0.003% (BSE)
  - GST:        18% on brokerage + exchange charges
  - SEBI:       ₹10 per crore
  - Stamp duty: 0.015% on buy side
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FillResult:
    """Post-slippage, post-cost fill details."""
    fill_price: float
    total_cost: float
    slippage_cost: float
    transaction_cost: float


class FillModel:
    """Configurable slippage + cost model."""

    def __init__(
        self,
        slippage_pct: float = 0.05,
        brokerage_per_order: float = 20.0,
        stt_pct: float = 0.001,
        exchange_pct: float = 0.0000345,
        gst_pct: float = 0.18,
        stamp_duty_pct: float = 0.00015,
        sebi_per_crore: float = 10.0,
    ):
        self.slippage_pct = slippage_pct / 100
        self.brokerage_per_order = brokerage_per_order
        self.stt_pct = stt_pct
        self.exchange_pct = exchange_pct
        self.gst_pct = gst_pct
        self.stamp_duty_pct = stamp_duty_pct
        self.sebi_per_crore = sebi_per_crore

    def estimate(self, side: str, quantity: int, price: float) -> FillResult:
        """Return slippage-adjusted fill price and all-in transaction cost."""
        is_buy = side.upper() in ("BUY", "B")

        slip_direction = 1 if is_buy else -1
        fill_price = price * (1 + slip_direction * self.slippage_pct)

        turnover = quantity * fill_price

        brokerage = min(self.brokerage_per_order, turnover * 0.0003)
        stt = turnover * self.stt_pct
        exchange = turnover * self.exchange_pct
        gst = (brokerage + exchange) * self.gst_pct
        sebi = turnover / 1e7 * self.sebi_per_crore
        stamp = turnover * self.stamp_duty_pct if is_buy else 0.0

        transaction_cost = brokerage + stt + exchange + gst + sebi + stamp
        slippage_cost = abs(fill_price - price) * quantity

        return FillResult(
            fill_price=round(fill_price, 2),
            total_cost=round(transaction_cost + slippage_cost, 2),
            slippage_cost=round(slippage_cost, 2),
            transaction_cost=round(transaction_cost, 2),
        )


DEFAULT_FILL_MODEL = FillModel()


class FnOFillModel:
    """Slippage + cost model for F&O segments (NFO)."""

    def __init__(
        self,
        segment: str = "options",
        slippage_pct: float = 0.15,
        brokerage_per_order: float = 20.0,
    ):
        self.segment = segment
        self.slippage_pct = slippage_pct / 100
        self.brokerage_per_order = brokerage_per_order

        if segment == "options":
            self.stt_pct = 0.000625          # 0.0625 % on sell premium
            self.exchange_pct = 0.00053       # 0.053 %
            self.stamp_duty_pct = 0.00003     # 0.003 % on buy
        else:
            self.stt_pct = 0.000125           # 0.0125 % on sell
            self.exchange_pct = 0.0000019     # 0.0019 %
            self.stamp_duty_pct = 0.00002     # 0.002 % on buy

        self.gst_pct = 0.18
        self.sebi_per_crore = 10.0

    def estimate(self, side: str, lots: int, lot_size: int, price: float) -> FillResult:
        quantity = lots * lot_size
        is_buy = side.upper() in ("BUY", "B")

        slip_dir = 1 if is_buy else -1
        fill_price = price * (1 + slip_dir * self.slippage_pct)
        turnover = quantity * fill_price

        brokerage = min(self.brokerage_per_order, turnover * 0.0003)
        stt = turnover * self.stt_pct if not is_buy else 0.0
        exchange = turnover * self.exchange_pct
        gst = (brokerage + exchange) * self.gst_pct
        sebi = turnover / 1e7 * self.sebi_per_crore
        stamp = turnover * self.stamp_duty_pct if is_buy else 0.0

        transaction_cost = brokerage + stt + exchange + gst + sebi + stamp
        slippage_cost = abs(fill_price - price) * quantity

        return FillResult(
            fill_price=round(fill_price, 2),
            total_cost=round(transaction_cost + slippage_cost, 2),
            slippage_cost=round(slippage_cost, 2),
            transaction_cost=round(transaction_cost, 2),
        )


OPTIONS_FILL_MODEL = FnOFillModel(segment="options")
FUTURES_FILL_MODEL = FnOFillModel(segment="futures", slippage_pct=0.10)
