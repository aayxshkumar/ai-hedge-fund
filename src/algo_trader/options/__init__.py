"""Options trading engine — pricing, strategies, and simulation."""

from src.algo_trader.options.pricing import black_scholes, greeks, implied_volatility
from src.algo_trader.options.strategies import OPTIONS_STRATEGY_REGISTRY

__all__ = [
    "black_scholes",
    "greeks",
    "implied_volatility",
    "OPTIONS_STRATEGY_REGISTRY",
]
