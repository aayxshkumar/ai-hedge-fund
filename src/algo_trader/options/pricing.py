"""Black-Scholes option pricing and Greeks calculation.

Provides analytical pricing for European-style options used in
Nifty 50 and Bank Nifty index options simulation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from scipy import stats, optimize


@dataclass
class OptionPrice:
    call: float
    put: float


@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    return (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def black_scholes(
    S: float,
    K: float,
    T: float,
    r: float = 0.07,
    sigma: float = 0.15,
) -> OptionPrice:
    """European option price via Black-Scholes.

    Args:
        S: Current underlying price
        K: Strike price
        T: Time to expiration in years (e.g., 7/365 for weekly)
        r: Risk-free rate (annual, default 7% for India)
        sigma: Annualized implied volatility
    """
    if T <= 0:
        call = max(S - K, 0)
        put = max(K - S, 0)
        return OptionPrice(call=call, put=put)

    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)

    call = S * stats.norm.cdf(d1) - K * math.exp(-r * T) * stats.norm.cdf(d2)
    put = K * math.exp(-r * T) * stats.norm.cdf(-d2) - S * stats.norm.cdf(-d1)

    return OptionPrice(call=max(call, 0), put=max(put, 0))


def greeks(
    S: float,
    K: float,
    T: float,
    r: float = 0.07,
    sigma: float = 0.15,
    option_type: str = "call",
) -> Greeks:
    """Calculate option Greeks."""
    if T <= 0 or sigma <= 0:
        intrinsic_delta = 1.0 if (option_type == "call" and S > K) else (-1.0 if option_type == "put" and K > S else 0.0)
        return Greeks(delta=intrinsic_delta, gamma=0, theta=0, vega=0, rho=0)

    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    sqrt_T = math.sqrt(T)
    pdf_d1 = stats.norm.pdf(d1)

    if option_type == "call":
        delta = stats.norm.cdf(d1)
        theta = (
            -S * pdf_d1 * sigma / (2 * sqrt_T)
            - r * K * math.exp(-r * T) * stats.norm.cdf(d2)
        ) / 365
        rho = K * T * math.exp(-r * T) * stats.norm.cdf(d2) / 100
    else:
        delta = stats.norm.cdf(d1) - 1
        theta = (
            -S * pdf_d1 * sigma / (2 * sqrt_T)
            + r * K * math.exp(-r * T) * stats.norm.cdf(-d2)
        ) / 365
        rho = -K * T * math.exp(-r * T) * stats.norm.cdf(-d2) / 100

    gamma = pdf_d1 / (S * sigma * sqrt_T)
    vega = S * pdf_d1 * sqrt_T / 100

    return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.07,
    option_type: str = "call",
) -> float:
    """Newton-Raphson IV solver."""
    if T <= 0 or market_price <= 0:
        return 0.15

    def objective(sigma):
        bs = black_scholes(S, K, T, r, sigma)
        price = bs.call if option_type == "call" else bs.put
        return price - market_price

    try:
        result = optimize.brentq(objective, 0.01, 5.0, xtol=1e-6)
        return result
    except (ValueError, RuntimeError):
        return 0.15
