"""Synthetic options chain generator.

Generates realistic option chains from underlying price data
using Black-Scholes pricing with IV smile/skew modelling.
Used for backtesting options strategies on Nifty 50 and Bank Nifty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.algo_trader.options.pricing import black_scholes, greeks, Greeks


@dataclass
class OptionContract:
    strike: float
    expiry_date: str
    option_type: str  # "call" or "put"
    premium: float
    iv: float
    greeks: Greeks
    days_to_expiry: int
    lot_size: int


@dataclass
class OptionChain:
    underlying: str
    spot_price: float
    date: str
    contracts: list[OptionContract] = field(default_factory=list)

    def get_atm_strike(self, step: float = 50) -> float:
        return round(self.spot_price / step) * step

    def calls(self) -> list[OptionContract]:
        return [c for c in self.contracts if c.option_type == "call"]

    def puts(self) -> list[OptionContract]:
        return [c for c in self.contracts if c.option_type == "put"]

    def get_strike(self, strike: float, opt_type: str) -> OptionContract | None:
        for c in self.contracts:
            if abs(c.strike - strike) < 0.01 and c.option_type == opt_type:
                return c
        return None


INDEX_CONFIG = {
    "NIFTY": {"symbol": "^NSEI", "lot_size": 25, "strike_step": 50, "num_strikes": 20},
    "BANKNIFTY": {"symbol": "^NSEBANK", "lot_size": 15, "strike_step": 100, "num_strikes": 20},
}


def _iv_smile(moneyness: float, base_iv: float) -> float:
    """Simplified volatility smile — deeper OTM options have higher IV."""
    skew = 0.0005 * (moneyness - 1.0) ** 2
    put_skew = 0.02 if moneyness < 0.97 else 0.0
    return base_iv + skew + put_skew


def compute_historical_volatility(prices: pd.Series, window: int = 20) -> float:
    """Annualised historical volatility from close prices."""
    if len(prices) < window + 1:
        return 0.15
    log_returns = np.log(prices / prices.shift(1)).dropna()
    return float(log_returns.tail(window).std() * math.sqrt(252))


def generate_chain(
    underlying: str,
    spot_price: float,
    date_str: str,
    days_to_expiry: int,
    historical_vol: float = 0.15,
) -> OptionChain:
    """Generate a synthetic option chain for a given date.

    Creates strikes around ATM with IV smile applied.
    Realistic for weekly/monthly Nifty and Bank Nifty options.
    """
    cfg = INDEX_CONFIG.get(underlying, INDEX_CONFIG["NIFTY"])
    lot_size = cfg["lot_size"]
    step = cfg["strike_step"]
    num_strikes = cfg["num_strikes"]

    atm = round(spot_price / step) * step
    T = max(days_to_expiry, 1) / 365.0
    r = 0.07

    base_iv = max(historical_vol * 1.05, 0.10)

    contracts: list[OptionContract] = []
    for i in range(-num_strikes, num_strikes + 1):
        strike = atm + i * step
        if strike <= 0:
            continue

        moneyness = spot_price / strike

        for opt_type in ("call", "put"):
            iv = _iv_smile(moneyness if opt_type == "call" else 1 / moneyness, base_iv)
            bs = black_scholes(spot_price, strike, T, r, iv)
            premium = bs.call if opt_type == "call" else bs.put
            g = greeks(spot_price, strike, T, r, iv, opt_type)

            contracts.append(OptionContract(
                strike=strike,
                expiry_date=date_str,
                option_type=opt_type,
                premium=round(premium, 2),
                iv=round(iv, 4),
                greeks=g,
                days_to_expiry=days_to_expiry,
                lot_size=lot_size,
            ))

    return OptionChain(
        underlying=underlying,
        spot_price=spot_price,
        date=date_str,
        contracts=contracts,
    )
