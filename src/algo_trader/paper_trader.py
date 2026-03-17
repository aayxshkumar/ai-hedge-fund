"""Paper trading engine — simulates order execution with virtual portfolio tracking.

Maintains a virtual portfolio with positions, cash, P&L, and trade history.
Used when the executor is in read_only mode to simulate realistic trading.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from threading import Lock

import yfinance as yf

from src.algo_trader.fill_model import DEFAULT_FILL_MODEL, OPTIONS_FILL_MODEL, FUTURES_FILL_MODEL

log = logging.getLogger(__name__)

PAPER_STATE_FILE = Path(__file__).parent.parent.parent / "outputs" / "paper_portfolio.json"

FUTURES_CONFIG = {
    "NIFTY":    {"lot_size": 25,  "margin_pct": 0.12, "tick_size": 0.05},
    "BANKNIFTY": {"lot_size": 15, "margin_pct": 0.15, "tick_size": 0.05},
    "FINNIFTY":  {"lot_size": 25, "margin_pct": 0.12, "tick_size": 0.05},
}


@dataclass
class FnOPosition:
    position_id: str
    instrument_type: str       # "options" or "futures"
    underlying: str
    strategy_name: str = ""
    side: str = "BUY"
    lots: int = 1
    lot_size: int = 25
    entry_price: float = 0.0
    current_price: float = 0.0
    margin_blocked: float = 0.0
    entry_date: str = ""
    legs: list[dict] = field(default_factory=list)
    unrealized_pnl: float = 0.0


@dataclass
class FnOTrade:
    timestamp: str
    position_id: str
    instrument_type: str
    underlying: str
    strategy_name: str
    side: str
    lots: int
    lot_size: int
    entry_price: float
    exit_price: float = 0.0
    pnl: float = 0.0
    charges: float = 0.0
    legs: list[dict] = field(default_factory=list)


@dataclass
class PaperPosition:
    ticker: str
    quantity: int
    avg_price: float
    entry_date: str
    current_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class PaperTrade:
    timestamp: str
    ticker: str
    side: str  # "BUY" or "SELL"
    quantity: int
    price: float
    value: float
    commission: float
    pnl: float = 0.0  # realized P&L for sells


@dataclass
class PaperPortfolio:
    initial_capital: float = 1_000_000.0
    cash: float = 1_000_000.0
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    trades: list[PaperTrade] = field(default_factory=list)
    realized_pnl: float = 0.0
    commission_rate: float = 0.001  # 0.1% per side (approx Zerodha)

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def total_value(self) -> float:
        position_value = sum(p.quantity * p.current_price for p in self.positions.values())
        return self.cash + position_value

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def total_return_pct(self) -> float:
        return ((self.total_value - self.initial_capital) / self.initial_capital) * 100


class PaperTrader:
    """Thread-safe paper trading engine with persistence."""

    def __init__(self, initial_capital: float = 1_000_000.0):
        self._lock = Lock()
        self.portfolio = PaperPortfolio(initial_capital=initial_capital, cash=initial_capital)
        self.fno_positions: dict[str, FnOPosition] = {}
        self.fno_trades: list[FnOTrade] = []
        self.margin_used: float = 0.0
        self._fno_counter: int = 0
        self._load_state()

    def execute_buy(self, ticker: str, quantity: int, price: float | None = None) -> dict:
        """Execute a simulated buy order with slippage and transaction costs."""
        with self._lock:
            if price is None:
                price = self._fetch_ltp(ticker)
            if price <= 0:
                return {"success": False, "message": f"Could not fetch price for {ticker}"}

            fill = DEFAULT_FILL_MODEL.estimate("BUY", quantity, price)
            price = fill.fill_price
            cost = quantity * price
            commission = fill.transaction_cost
            total_cost = cost + commission

            if total_cost > self.portfolio.cash:
                max_qty = int(self.portfolio.cash / (price * (1 + self.portfolio.commission_rate)))
                if max_qty <= 0:
                    return {"success": False, "message": f"Insufficient cash (need {total_cost:.0f}, have {self.portfolio.cash:.0f})"}
                quantity = max_qty
                fill = DEFAULT_FILL_MODEL.estimate("BUY", quantity, price)
                cost = quantity * fill.fill_price
                commission = fill.transaction_cost
                total_cost = cost + commission

            self.portfolio.cash -= total_cost

            if ticker in self.portfolio.positions:
                pos = self.portfolio.positions[ticker]
                total_qty = pos.quantity + quantity
                pos.avg_price = ((pos.avg_price * pos.quantity) + (price * quantity)) / total_qty
                pos.quantity = total_qty
            else:
                self.portfolio.positions[ticker] = PaperPosition(
                    ticker=ticker, quantity=quantity, avg_price=price,
                    entry_date=datetime.now().isoformat(), current_price=price,
                )

            trade = PaperTrade(
                timestamp=datetime.now().isoformat(), ticker=ticker, side="BUY",
                quantity=quantity, price=price, value=cost, commission=commission,
            )
            self.portfolio.trades.append(trade)
            self._save_state()

            log.info("PAPER BUY: %s x%d @ %.2f (cost: %.0f, commission: %.0f)",
                     ticker, quantity, price, cost, commission)
            return {
                "success": True,
                "message": f"Paper BUY {ticker} x{quantity} @ {price:.2f}",
                "order_id": f"PAPER-{len(self.portfolio.trades)}",
                "price": price,
                "quantity": quantity,
                "cost": total_cost,
            }

    def execute_sell(self, ticker: str, quantity: int, price: float | None = None) -> dict:
        """Execute a simulated sell order."""
        with self._lock:
            if ticker not in self.portfolio.positions:
                return {"success": False, "message": f"No position in {ticker}"}

            pos = self.portfolio.positions[ticker]
            if quantity > pos.quantity:
                quantity = pos.quantity

            if price is None:
                price = self._fetch_ltp(ticker)
            if price <= 0:
                return {"success": False, "message": f"Could not fetch price for {ticker}"}

            fill = DEFAULT_FILL_MODEL.estimate("SELL", quantity, price)
            price = fill.fill_price
            proceeds = quantity * price
            commission = fill.transaction_cost
            net_proceeds = proceeds - commission
            pnl = (price - pos.avg_price) * quantity - commission

            self.portfolio.cash += net_proceeds
            self.portfolio.realized_pnl += pnl

            pos.quantity -= quantity
            if pos.quantity <= 0:
                del self.portfolio.positions[ticker]

            trade = PaperTrade(
                timestamp=datetime.now().isoformat(), ticker=ticker, side="SELL",
                quantity=quantity, price=price, value=proceeds, commission=commission, pnl=round(pnl, 2),
            )
            self.portfolio.trades.append(trade)
            self._save_state()

            log.info("PAPER SELL: %s x%d @ %.2f (PnL: %.0f)", ticker, quantity, price, pnl)
            return {
                "success": True,
                "message": f"Paper SELL {ticker} x{quantity} @ {price:.2f} (PnL: {pnl:+.0f})",
                "order_id": f"PAPER-{len(self.portfolio.trades)}",
                "price": price,
                "quantity": quantity,
                "pnl": pnl,
            }

    def update_prices(self):
        """Update current prices for all open positions."""
        with self._lock:
            for ticker, pos in self.portfolio.positions.items():
                ltp = self._fetch_ltp(ticker)
                if ltp > 0:
                    pos.current_price = ltp
                    pos.unrealized_pnl = (ltp - pos.avg_price) * pos.quantity
            self._save_state()

    def get_summary(self) -> dict:
        """Return portfolio summary."""
        with self._lock:
            return {
                "initial_capital": self.portfolio.initial_capital,
                "cash": round(self.portfolio.cash, 2),
                "positions": {
                    t: {
                        "quantity": p.quantity,
                        "avg_price": round(p.avg_price, 2),
                        "current_price": round(p.current_price, 2),
                        "unrealized_pnl": round(p.unrealized_pnl, 2),
                        "entry_date": p.entry_date,
                    }
                    for t, p in self.portfolio.positions.items()
                },
                "realized_pnl": round(self.portfolio.realized_pnl, 2),
                "unrealized_pnl": round(self.portfolio.unrealized_pnl, 2),
                "total_pnl": round(self.portfolio.total_pnl, 2),
                "total_value": round(self.portfolio.total_value, 2),
                "total_return_pct": round(self.portfolio.total_return_pct, 2),
                "trade_count": len(self.portfolio.trades),
                "open_positions": len(self.portfolio.positions),
            }

    def get_trades(self, limit: int = 50) -> list[dict]:
        """Return recent trades."""
        with self._lock:
            return [asdict(t) for t in self.portfolio.trades[-limit:]]

    def reset(self, initial_capital: float = 1_000_000.0):
        """Reset paper portfolio to fresh state."""
        with self._lock:
            self.portfolio = PaperPortfolio(initial_capital=initial_capital, cash=initial_capital)
            self.fno_positions.clear()
            self.fno_trades.clear()
            self.margin_used = 0.0
            self._fno_counter = 0
            self._save_state()

    # ── F&O Paper Trading ─────────────────────────────────────────

    def execute_options_trade(
        self, legs: list[dict], underlying: str, strategy_name: str = "",
        price: float | None = None,
    ) -> dict:
        """Simulate a multi-leg options entry.

        Each leg: {strike, opt_type, side, lots, premium}
        """
        with self._lock:
            self._fno_counter += 1
            pid = f"OPT-{self._fno_counter}"
            total_premium = 0.0
            lot_size = FUTURES_CONFIG.get(underlying, {}).get("lot_size", 25)
            processed_legs = []

            for leg in legs:
                lots = leg.get("lots", 1)
                prem = leg.get("premium", 0)
                side = leg.get("side", "BUY")
                fill = OPTIONS_FILL_MODEL.estimate(side, lots, lot_size, prem)

                cost = lots * lot_size * fill.fill_price
                if side.upper() == "BUY":
                    total_premium += cost + fill.transaction_cost
                else:
                    total_premium -= cost - fill.transaction_cost

                processed_legs.append({
                    **leg,
                    "fill_price": fill.fill_price,
                    "lot_size": lot_size,
                    "charges": fill.transaction_cost,
                })

            if total_premium > self.portfolio.cash:
                return {"success": False, "message": f"Insufficient cash for options (need ₹{total_premium:,.0f})"}

            self.portfolio.cash -= total_premium

            self.fno_positions[pid] = FnOPosition(
                position_id=pid,
                instrument_type="options",
                underlying=underlying,
                strategy_name=strategy_name,
                side="MULTI",
                lots=legs[0].get("lots", 1) if legs else 1,
                lot_size=lot_size,
                entry_price=total_premium,
                margin_blocked=max(total_premium, 0),
                entry_date=datetime.now().isoformat(),
                legs=processed_legs,
            )

            self.fno_trades.append(FnOTrade(
                timestamp=datetime.now().isoformat(),
                position_id=pid,
                instrument_type="options",
                underlying=underlying,
                strategy_name=strategy_name,
                side="OPEN",
                lots=legs[0].get("lots", 1) if legs else 1,
                lot_size=lot_size,
                entry_price=total_premium,
                legs=processed_legs,
            ))
            self._save_state()

            log.info("PAPER OPTIONS %s: %s %d legs, premium ₹%.0f",
                     strategy_name, underlying, len(legs), total_premium)
            return {"success": True, "position_id": pid, "premium_paid": total_premium}

    def execute_futures_trade(
        self, underlying: str, side: str, lots: int, price: float | None = None
    ) -> dict:
        """Simulate a futures entry (long or short)."""
        with self._lock:
            cfg = FUTURES_CONFIG.get(underlying, {"lot_size": 25, "margin_pct": 0.12})
            lot_size = cfg["lot_size"]
            margin_pct = cfg["margin_pct"]

            if price is None:
                price = self._fetch_ltp(f"{underlying}.NS") or 0
            if price <= 0:
                return {"success": False, "message": f"Cannot fetch price for {underlying}"}

            fill = FUTURES_FILL_MODEL.estimate(side, lots, lot_size, price)
            margin_needed = lots * lot_size * fill.fill_price * margin_pct

            if margin_needed > self.portfolio.cash:
                return {"success": False, "message": f"Insufficient margin (need ₹{margin_needed:,.0f})"}

            self._fno_counter += 1
            pid = f"FUT-{self._fno_counter}"
            self.portfolio.cash -= margin_needed
            self.margin_used += margin_needed

            self.fno_positions[pid] = FnOPosition(
                position_id=pid,
                instrument_type="futures",
                underlying=underlying,
                side=side.upper(),
                lots=lots,
                lot_size=lot_size,
                entry_price=fill.fill_price,
                current_price=fill.fill_price,
                margin_blocked=margin_needed,
                entry_date=datetime.now().isoformat(),
            )

            self.fno_trades.append(FnOTrade(
                timestamp=datetime.now().isoformat(),
                position_id=pid,
                instrument_type="futures",
                underlying=underlying,
                strategy_name="",
                side=side.upper(),
                lots=lots,
                lot_size=lot_size,
                entry_price=fill.fill_price,
                charges=fill.transaction_cost,
            ))
            self._save_state()

            log.info("PAPER FUTURES %s: %s %s x%d @ %.2f, margin ₹%.0f",
                     underlying, side, underlying, lots, fill.fill_price, margin_needed)
            return {"success": True, "position_id": pid, "margin_blocked": margin_needed,
                    "fill_price": fill.fill_price}

    def close_fno_position(self, position_id: str, exit_price: float | None = None) -> dict:
        """Close an F&O position and compute P&L."""
        with self._lock:
            pos = self.fno_positions.get(position_id)
            if not pos:
                return {"success": False, "message": f"Position {position_id} not found"}

            if pos.instrument_type == "futures":
                if exit_price is None:
                    exit_price = self._fetch_ltp(f"{pos.underlying}.NS") or pos.current_price
                qty = pos.lots * pos.lot_size
                if pos.side == "BUY":
                    pnl = (exit_price - pos.entry_price) * qty
                else:
                    pnl = (pos.entry_price - exit_price) * qty

                fill = FUTURES_FILL_MODEL.estimate(
                    "SELL" if pos.side == "BUY" else "BUY",
                    pos.lots, pos.lot_size, exit_price
                )
                pnl -= fill.transaction_cost
                self.portfolio.cash += pos.margin_blocked + pnl
                self.margin_used -= pos.margin_blocked
                self.portfolio.realized_pnl += pnl

            elif pos.instrument_type == "options":
                pnl = -(pos.entry_price)
                if exit_price is not None:
                    pnl = exit_price - pos.entry_price
                self.portfolio.cash += exit_price or 0
                self.portfolio.realized_pnl += pnl

            else:
                return {"success": False, "message": "Unknown instrument type"}

            self.fno_trades.append(FnOTrade(
                timestamp=datetime.now().isoformat(),
                position_id=position_id,
                instrument_type=pos.instrument_type,
                underlying=pos.underlying,
                strategy_name=pos.strategy_name,
                side="CLOSE",
                lots=pos.lots,
                lot_size=pos.lot_size,
                entry_price=pos.entry_price,
                exit_price=exit_price or 0,
                pnl=round(pnl, 2),
            ))

            del self.fno_positions[position_id]
            self._save_state()

            log.info("PAPER CLOSE %s: P&L ₹%.0f", position_id, pnl)
            return {"success": True, "pnl": round(pnl, 2), "position_id": position_id}

    def get_fno_summary(self) -> dict:
        """Return F&O positions and P&L summary."""
        with self._lock:
            positions = {}
            for pid, pos in self.fno_positions.items():
                positions[pid] = {
                    "instrument_type": pos.instrument_type,
                    "underlying": pos.underlying,
                    "strategy_name": pos.strategy_name,
                    "side": pos.side,
                    "lots": pos.lots,
                    "lot_size": pos.lot_size,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "margin_blocked": pos.margin_blocked,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "entry_date": pos.entry_date,
                    "legs": pos.legs,
                }
            fno_pnl = sum(t.pnl for t in self.fno_trades if t.pnl)
            return {
                "positions": positions,
                "open_count": len(self.fno_positions),
                "total_trades": len(self.fno_trades),
                "margin_used": round(self.margin_used, 2),
                "realized_pnl": round(fno_pnl, 2),
            }

    @staticmethod
    def _fetch_ltp(ticker: str) -> float:
        """Fetch last traded price via yfinance (fast)."""
        try:
            clean = ticker.replace(".NS", "").replace(".BO", "")
            t = yf.Ticker(f"{clean}.NS")
            fi = t.fast_info
            price = fi.get("lastPrice", 0)
            if price and price > 0:
                return float(price)
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return 0.0

    def _save_state(self):
        """Persist portfolio to disk."""
        try:
            PAPER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "initial_capital": self.portfolio.initial_capital,
                "cash": self.portfolio.cash,
                "realized_pnl": self.portfolio.realized_pnl,
                "positions": {t: asdict(p) for t, p in self.portfolio.positions.items()},
                "trades": [asdict(t) for t in self.portfolio.trades[-200:]],
                "fno_positions": {pid: asdict(p) for pid, p in self.fno_positions.items()},
                "fno_trades": [asdict(t) for t in self.fno_trades[-200:]],
                "margin_used": self.margin_used,
                "fno_counter": self._fno_counter,
                "last_updated": datetime.now().isoformat(),
            }
            with open(PAPER_STATE_FILE, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            log.warning("Failed to save paper state: %s", e)

    def _load_state(self):
        """Load persisted portfolio state."""
        if not PAPER_STATE_FILE.exists():
            return
        try:
            with open(PAPER_STATE_FILE) as f:
                state = json.load(f)
            self.portfolio.initial_capital = state.get("initial_capital", 1_000_000.0)
            self.portfolio.cash = state.get("cash", self.portfolio.initial_capital)
            self.portfolio.realized_pnl = state.get("realized_pnl", 0.0)

            for ticker, pdata in state.get("positions", {}).items():
                self.portfolio.positions[ticker] = PaperPosition(**pdata)

            for tdata in state.get("trades", []):
                self.portfolio.trades.append(PaperTrade(**tdata))

            for pid, fdata in state.get("fno_positions", {}).items():
                self.fno_positions[pid] = FnOPosition(**fdata)
            for ftdata in state.get("fno_trades", []):
                self.fno_trades.append(FnOTrade(**ftdata))
            self.margin_used = state.get("margin_used", 0.0)
            self._fno_counter = state.get("fno_counter", 0)

            log.info("Loaded paper portfolio: %.0f cash, %d eq positions, %d F&O positions",
                     self.portfolio.cash, len(self.portfolio.positions), len(self.fno_positions))
        except Exception as e:
            log.warning("Failed to load paper state: %s", e)
