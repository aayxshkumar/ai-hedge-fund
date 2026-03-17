"""Base class for all trading strategies.

Every strategy must implement ``analyse(price_df)`` returning a dict with
``signal`` ("buy" | "sell" | "hold"), ``confidence`` (0.0–1.0), and
``indicators`` (dict of computed values for debugging / display).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from src.algo_trader.config import StrategyConfig


class StrategySignal:
    """Typed wrapper around the signal dict for forward compatibility."""

    __slots__ = ("signal", "confidence", "indicators")

    def __init__(self, signal: str = "hold", confidence: float = 0.0, indicators: dict[str, Any] | None = None):
        self.signal = signal
        self.confidence = max(0.0, min(1.0, confidence))
        self.indicators = indicators or {}

    def to_dict(self) -> dict[str, Any]:
        return {"signal": self.signal, "confidence": self.confidence, "indicators": self.indicators}


class BaseStrategy(ABC):
    """Abstract base for all quant strategies."""

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()

    @abstractmethod
    def analyse(self, price_df: pd.DataFrame) -> dict[str, Any]:
        """Analyse a single ticker's OHLCV DataFrame.

        Must return {"signal": "buy"|"sell"|"hold", "confidence": float, "indicators": dict}.
        """
        ...

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"signal": "hold", "confidence": 0.0, "indicators": {}}
