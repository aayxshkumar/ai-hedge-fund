"""Candlestick pattern strategy — uses candle formations + volume confirmation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig
from src.algo_trader.strategies.candle_patterns import detect_patterns


class CandlePatternStrategy:

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < 10:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        result = detect_patterns(price_df, lookback=5)

        vol = price_df["volume"] if "volume" in price_df.columns else price_df.get("Volume")
        vol_confirmed = False
        if vol is not None and len(vol) >= 21:
            avg_vol = vol.iloc[-21:-1].mean()
            vol_confirmed = float(vol.iloc[-1]) > avg_vol * 1.3

        score = 0.0
        if result.bias == "bullish":
            score = result.strength * 0.7
        elif result.bias == "bearish":
            score = -result.strength * 0.7

        if vol_confirmed:
            score *= 1.4

        confidence = min(abs(score), 1.0)

        if score > 0.15:
            signal = "buy"
        elif score < -0.15:
            signal = "sell"
        else:
            signal = "hold"

        return {
            "signal": signal,
            "confidence": round(confidence, 3),
            "indicators": {
                "patterns": result.patterns,
                "bias": result.bias,
                "strength": result.strength,
                "volume_confirmed": vol_confirmed,
            },
        }
