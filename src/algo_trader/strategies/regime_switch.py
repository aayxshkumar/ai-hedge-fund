"""Regime-switch strategy — detects volatility regime and adapts.

In low-volatility regimes → mean-reversion signals (buy dips, sell rips).
In high-volatility regimes → trend-following signals (ride momentum).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig


class RegimeSwitchStrategy:

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()
        self.vol_lookback = 20
        self.vol_threshold = 0.25  # annualized; above = high-vol regime

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < 60:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"] if "close" in price_df.columns else price_df["Close"]
        returns = close.pct_change().dropna()

        recent_vol = float(returns.iloc[-self.vol_lookback:].std() * np.sqrt(252))
        long_vol = float(returns.std() * np.sqrt(252))
        high_vol = recent_vol > self.vol_threshold

        regime = "trending" if high_vol else "mean_reverting"

        if regime == "trending":
            signal, confidence = self._trend_signal(close, returns)
        else:
            signal, confidence = self._mean_revert_signal(close)

        return {
            "signal": signal,
            "confidence": round(confidence, 3),
            "indicators": {
                "regime": regime,
                "recent_volatility": round(recent_vol, 4),
                "long_volatility": round(long_vol, 4),
            },
        }

    def _trend_signal(self, close: pd.Series, returns: pd.Series) -> tuple[str, float]:
        ema_fast = close.ewm(span=10).mean()
        ema_slow = close.ewm(span=30).mean()
        trend_up = float(ema_fast.iloc[-1]) > float(ema_slow.iloc[-1])

        mom_5d = float(returns.iloc[-5:].sum())

        if trend_up and mom_5d > 0.01:
            return "buy", min(abs(mom_5d) * 5, 0.85)
        elif not trend_up and mom_5d < -0.01:
            return "sell", min(abs(mom_5d) * 5, 0.85)
        return "hold", 0.0

    def _mean_revert_signal(self, close: pd.Series) -> tuple[str, float]:
        ma = close.rolling(20).mean()
        std = close.rolling(20).std()
        z = (close.iloc[-1] - ma.iloc[-1]) / std.iloc[-1] if std.iloc[-1] != 0 else 0.0

        if z < -1.5:
            return "buy", min(abs(z) / 3, 0.8)
        elif z > 1.5:
            return "sell", min(abs(z) / 3, 0.8)
        return "hold", 0.0
