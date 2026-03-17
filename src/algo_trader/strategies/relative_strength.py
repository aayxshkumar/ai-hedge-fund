"""Relative-strength (cross-sectional momentum) strategy.

Ranks stocks by recent returns and signals buy for the strongest,
sell for the weakest.  When used on a single ticker, compares its
recent performance to a rolling baseline to determine relative strength.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig


class RelativeStrengthStrategy:

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()
        self.lookback = 20

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < self.lookback + 5:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"] if "close" in price_df.columns else price_df["Close"]

        ret_recent = float(close.iloc[-1] / close.iloc[-self.lookback] - 1)
        ret_prior = float(close.iloc[-self.lookback] / close.iloc[-2 * self.lookback] - 1) if len(close) >= 2 * self.lookback else 0.0

        acceleration = ret_recent - ret_prior

        vol = price_df["volume"] if "volume" in price_df.columns else price_df.get("Volume")
        vol_trend = 1.0
        if vol is not None and len(vol) >= self.lookback + 1:
            recent_vol = float(vol.iloc[-5:].mean())
            avg_vol = float(vol.iloc[-self.lookback:-1].mean())
            vol_trend = recent_vol / avg_vol if avg_vol > 0 else 1.0

        score = ret_recent * 3.0 + acceleration * 2.0
        if vol_trend > 1.5:
            score *= 1.2

        confidence = min(abs(score), 1.0)

        if score > 0.1:
            signal = "buy"
        elif score < -0.1:
            signal = "sell"
        else:
            signal = "hold"

        return {
            "signal": signal,
            "confidence": round(confidence, 3),
            "indicators": {
                "return_20d": round(ret_recent * 100, 2),
                "return_prior_20d": round(ret_prior * 100, 2),
                "acceleration": round(acceleration * 100, 2),
                "volume_trend": round(vol_trend, 2),
            },
        }
