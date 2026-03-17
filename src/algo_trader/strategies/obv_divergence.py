"""On-Balance Volume (OBV) Divergence strategy.

Detects divergences between price and OBV:
- Bullish divergence: price makes lower low but OBV makes higher low (accumulation)
- Bearish divergence: price makes higher high but OBV makes lower high (distribution)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import obv as _obv


class OBVDivergenceStrategy:
    def __init__(self, lookback: int = 20, divergence_window: int = 5):
        self.lookback = lookback
        self.divergence_window = divergence_window

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < self.lookback + 10:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]
        volume = price_df["volume"].fillna(0)

        obv = _obv(close, volume)

        obv_sma = obv.rolling(self.lookback).mean()
        obv_trend = obv.iloc[-1] - obv.iloc[-self.divergence_window]
        price_trend = close.iloc[-1] - close.iloc[-self.divergence_window]

        recent_close = close.iloc[-self.lookback:]
        recent_obv = obv.iloc[-self.lookback:]

        half = self.lookback // 2
        price_low1 = recent_close.iloc[:half].min()
        price_low2 = recent_close.iloc[half:].min()
        obv_low1 = recent_obv.iloc[:half].min()
        obv_low2 = recent_obv.iloc[half:].min()

        price_high1 = recent_close.iloc[:half].max()
        price_high2 = recent_close.iloc[half:].max()
        obv_high1 = recent_obv.iloc[:half].max()
        obv_high2 = recent_obv.iloc[half:].max()

        bull_div = price_low2 < price_low1 and obv_low2 > obv_low1
        bear_div = price_high2 > price_high1 and obv_high2 < obv_high1

        obv_above_sma = obv.iloc[-1] > obv_sma.iloc[-1] if not np.isnan(obv_sma.iloc[-1]) else False

        indicators = {
            "obv": round(obv.iloc[-1], 0),
            "obv_sma": round(obv_sma.iloc[-1], 0) if not np.isnan(obv_sma.iloc[-1]) else 0,
            "obv_trend": round(obv_trend, 0),
            "price_trend": round(price_trend, 2),
            "bullish_divergence": bull_div,
            "bearish_divergence": bear_div,
        }

        score = 0.0
        if bull_div:
            score += 0.5
        if bear_div:
            score -= 0.5
        if obv_above_sma:
            score += 0.2
        else:
            score -= 0.2
        if obv_trend > 0 and price_trend > 0:
            score += 0.15
        elif obv_trend < 0 and price_trend < 0:
            score -= 0.15

        confidence = min(abs(score), 1.0)
        if score > 0.2:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.2:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
