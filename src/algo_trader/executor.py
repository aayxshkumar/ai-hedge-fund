"""Zerodha Kite Connect executor — translates trading decisions into live orders.

Uses the official kiteconnect Python library for portfolio reads and order execution.
Requires: api_key, api_secret, and a daily access_token obtained via the login flow.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from src.algo_trader.config import AlgoTraderConfig

log = logging.getLogger(__name__)


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"


@dataclass
class Order:
    ticker: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    trigger_price: float | None = None
    exchange: Exchange = Exchange.NSE
    product: str = "CNC"


@dataclass
class Position:
    ticker: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    product: str


@dataclass
class Holding:
    ticker: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float


@dataclass
class ExecutionResult:
    success: bool
    order_id: str | None = None
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class Product(str, Enum):
    CNC = "CNC"      # equity delivery
    MIS = "MIS"      # intraday
    NRML = "NRML"    # F&O normal


class ZerodhaExecutor:
    """Interfaces with Zerodha via the official kiteconnect Python library."""

    def __init__(self, config: AlgoTraderConfig):
        self.config = config
        self.read_only = config.broker.read_only
        self._kite = None
        self._connected = False
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._nfo_instruments: list[dict] = []
        self._nfo_cache_date: str = ""
        self._init_kite()

    def _init_kite(self):
        """Initialize the KiteConnect client if credentials are available."""
        api_key = self.config.broker.api_key
        access_token = self.config.broker.access_token
        if not api_key:
            self._last_error = "No API key configured"
            return
        try:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=api_key)
            if access_token:
                self._kite.set_access_token(access_token)
                self._connected = True
                self._last_error = None
            else:
                self._last_error = "No access token — login required"
        except Exception as e:
            self._last_error = str(e)
            log.error("Failed to init KiteConnect: %s", e)

    def set_access_token(self, token: str):
        """Set a new access token (called after daily login)."""
        with self._lock:
            self.config.broker.access_token = token
            if self._kite:
                self._kite.set_access_token(token)
                self._connected = True
                self._last_error = None
            else:
                self._init_kite()

    def generate_login_url(self) -> str | None:
        """Generate the Kite Connect login URL for the user."""
        api_key = self.config.broker.api_key
        if not api_key:
            return None
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"

    def generate_session(self, request_token: str) -> dict:
        """Exchange a request_token for an access_token."""
        if not self._kite:
            return {"error": "KiteConnect not initialized — check API key"}
        try:
            data = self._kite.generate_session(
                request_token, api_secret=self.config.broker.api_secret
            )
            access_token = data.get("access_token", "")
            if access_token:
                self.set_access_token(access_token)
                return {
                    "success": True,
                    "access_token": access_token,
                    "user_name": data.get("user_name", ""),
                    "email": data.get("email", ""),
                    "user_id": data.get("user_id", ""),
                }
            return {"error": "No access token in response"}
        except Exception as e:
            self._last_error = str(e)
            return {"error": str(e)}

    def is_connected(self) -> bool:
        return self._connected and self._kite is not None

    def connection_status(self) -> dict:
        """Full connection status for the UI."""
        with self._lock:
            result: dict[str, Any] = {
                "connected": False,
                "has_api_key": bool(self.config.broker.api_key),
                "has_access_token": bool(self.config.broker.access_token),
                "error": self._last_error,
            }
            if not self._kite or not self.config.broker.access_token:
                return result

            try:
                profile = self._kite.profile()
                result["connected"] = True
                result["error"] = None
                result["user_id"] = profile.get("user_id", "")
                result["user_name"] = profile.get("user_name", "")
                result["email"] = profile.get("email", "")
                result["broker"] = profile.get("broker", "ZERODHA")
                self._connected = True
                self._last_error = None
            except Exception as e:
                err = str(e)
                if "TokenException" in type(e).__name__ or "token" in err.lower():
                    result["error"] = "Access token expired — please login again"
                else:
                    result["error"] = err
                self._connected = False
                self._last_error = result["error"]

            return result

    # ── Portfolio reads ──────────────────────────────────────────────

    def get_holdings(self) -> list[Holding]:
        if not self._kite or not self._connected:
            return []
        try:
            data = self._kite.holdings()
            return [
                Holding(
                    ticker=h.get("tradingsymbol", ""),
                    quantity=int(h.get("quantity", 0)),
                    average_price=float(h.get("average_price", 0)),
                    last_price=float(h.get("last_price", 0)),
                    pnl=float(h.get("pnl", 0)),
                )
                for h in data
                if h.get("quantity", 0) > 0
            ]
        except Exception as e:
            log.error("get_holdings error: %s", e)
            return []

    def get_positions(self, include_closed: bool = False) -> list[Position]:
        if not self._kite or not self._connected:
            return []
        try:
            data = self._kite.positions()
            net = data.get("net", [])
            return [
                Position(
                    ticker=p.get("tradingsymbol", ""),
                    quantity=int(p.get("quantity", 0)),
                    average_price=float(p.get("average_price", 0)),
                    last_price=float(p.get("last_price", 0)),
                    pnl=float(p.get("pnl", 0)),
                    product=p.get("product", "CNC"),
                )
                for p in net
                if include_closed or p.get("quantity", 0) != 0
            ]
        except Exception as e:
            log.error("get_positions error: %s", e)
            return []

    def get_funds(self) -> dict:
        if not self._kite or not self._connected:
            return {"available_cash": 0, "used_margin": 0}
        try:
            margins = self._kite.margins(segment="equity")
            return {
                "available_cash": float(margins.get("available", {}).get("cash", 0)),
                "used_margin": float(margins.get("utilised", {}).get("debits", 0)),
            }
        except Exception as e:
            log.error("get_funds error: %s", e)
            return {"available_cash": 0, "used_margin": 0}

    def get_quote(self, ticker: str, exchange: str = "NSE") -> dict:
        if not self._kite or not self._connected:
            return {}
        try:
            key = f"{exchange}:{ticker}"
            return self._kite.quote(key).get(key, {})
        except Exception as e:
            log.error("get_quote error: %s", e)
            return {}

    def get_ltp(self, tickers: list[str], exchange: str = "NSE") -> dict[str, float]:
        if not self._kite or not self._connected:
            return {}
        try:
            instruments = [f"{exchange}:{t}" for t in tickers]
            data = self._kite.ltp(instruments)
            prices = {}
            for key, val in data.items():
                symbol = key.split(":")[-1] if ":" in key else key
                prices[symbol] = float(val.get("last_price", 0))
            return prices
        except Exception as e:
            log.error("get_ltp error: %s", e)
            return {}

    # ── Order execution ──────────────────────────────────────────────

    def place_order(self, order: Order) -> ExecutionResult:
        if self.read_only:
            log.warning("READ-ONLY — order NOT placed: %s %s %d", order.side.value, order.ticker, order.quantity)
            return ExecutionResult(success=False, message="Read-only mode enabled")

        with self._lock:
            if not self._kite or not self._connected:
                return ExecutionResult(success=False, message="Not connected to Zerodha")

            try:
                params: dict[str, Any] = {
                    "exchange": order.exchange.value,
                    "tradingsymbol": order.ticker,
                    "transaction_type": order.side.value,
                    "quantity": order.quantity,
                    "order_type": order.order_type.value,
                    "product": order.product,
                    "variety": "regular",
                }
                if order.price is not None:
                    params["price"] = order.price
                if order.trigger_price is not None:
                    params["trigger_price"] = order.trigger_price

                log.info("Placing order: %s %s x%d @ %s", order.side.value, order.ticker, order.quantity, order.order_type.value)
                order_id = self._kite.place_order(**params)
                return ExecutionResult(success=True, order_id=str(order_id), message="Order placed")
            except Exception as e:
                log.error("place_order error: %s", e)
                return ExecutionResult(success=False, message=str(e))

    # ── F&O helpers ────────────────────────────────────────────────

    def load_nfo_instruments(self) -> list[dict]:
        """Fetch and cache NFO instruments (once per day)."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._nfo_cache_date == today and self._nfo_instruments:
            return self._nfo_instruments
        if not self._kite or not self._connected:
            return []
        try:
            instruments = self._kite.instruments("NFO")
            self._nfo_instruments = instruments
            self._nfo_cache_date = today
            log.info("Loaded %d NFO instruments", len(instruments))
            return instruments
        except Exception as e:
            log.error("Failed to load NFO instruments: %s", e)
            return self._nfo_instruments

    def resolve_tradingsymbol(
        self, underlying: str, expiry: str, strike: float, opt_type: str
    ) -> str | None:
        """Map (underlying, expiry, strike, CE/PE) to a Kite trading symbol."""
        instruments = self.load_nfo_instruments()
        for inst in instruments:
            if (inst.get("name") == underlying
                    and str(inst.get("expiry")) == expiry
                    and inst.get("strike") == strike
                    and inst.get("instrument_type") == opt_type):
                return inst.get("tradingsymbol")
        return None

    def resolve_futures_symbol(self, underlying: str, expiry: str | None = None) -> str | None:
        """Find the nearest-month futures trading symbol."""
        instruments = self.load_nfo_instruments()
        futs = [i for i in instruments
                if i.get("name") == underlying and i.get("instrument_type") == "FUT"]
        if not futs:
            return None
        futs.sort(key=lambda i: str(i.get("expiry", "")))
        if expiry:
            match = [f for f in futs if str(f.get("expiry")) == expiry]
            if match:
                return match[0].get("tradingsymbol")
        return futs[0].get("tradingsymbol") if futs else None

    def get_option_chain(self, underlying: str) -> list[dict]:
        """Return live option chain for an underlying from NFO instruments."""
        instruments = self.load_nfo_instruments()
        chain = [i for i in instruments
                 if i.get("name") == underlying and i.get("instrument_type") in ("CE", "PE")]
        chain.sort(key=lambda i: (str(i.get("expiry", "")), i.get("strike", 0)))
        return chain

    def get_fno_margins(self) -> dict:
        """Fetch F&O margins from Kite (segment='equity' includes F&O on Zerodha)."""
        if not self._kite or not self._connected:
            return {"available": 0, "used": 0}
        try:
            margins = self._kite.margins(segment="equity")
            return {
                "available": float(margins.get("available", {}).get("live_balance", 0)),
                "used": float(margins.get("utilised", {}).get("debits", 0)),
            }
        except Exception as e:
            log.error("get_fno_margins error: %s", e)
            return {"available": 0, "used": 0}

    def get_fno_positions(self) -> list[Position]:
        """Return only NFO positions."""
        all_pos = self.get_positions(include_closed=False)
        return [p for p in all_pos if p.product in ("NRML", "MIS")]

    def place_multi_leg_order(self, legs: list[Order]) -> list[ExecutionResult]:
        """Place multiple orders for multi-leg option strategies."""
        results = []
        for leg in legs:
            results.append(self.place_order(leg))
        return results

    def cancel_order(self, order_id: str) -> ExecutionResult:
        if self.read_only:
            return ExecutionResult(success=False, message="Read-only mode")
        if not self._kite or not self._connected:
            return ExecutionResult(success=False, message="Not connected")
        try:
            self._kite.cancel_order(variety="regular", order_id=order_id)
            return ExecutionResult(success=True, order_id=order_id, message="Cancelled")
        except Exception as e:
            return ExecutionResult(success=False, message=str(e))
