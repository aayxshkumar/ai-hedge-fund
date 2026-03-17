"""VWAP Crossover strategy.

Generates buy signals when price crosses above the Volume-Weighted Average Price
and sell signals when it crosses below.  VWAP acts as a dynamic support/resistance
level that incorporates volume, making it more meaningful than a simple moving average.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class VWAPStrategy:
    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < self.lookback + 5:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]
        high = price_df["high"]
        low = price_df["low"]
        volume = price_df["volume"].replace(0, np.nan).ffill().fillna(1)

        typical_price = (high + low + close) / 3
        cum_tp_vol = (typical_price * volume).rolling(self.lookback).sum()
        cum_vol = volume.rolling(self.lookback).sum()
        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)

        curr_price = close.iloc[-1]
        curr_vwap = vwap.iloc[-1]
        prev_price = close.iloc[-2]
        prev_vwap = vwap.iloc[-2]

        if np.isnan(curr_vwap) or np.isnan(prev_vwap):
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        pct_from_vwap = (curr_price - curr_vwap) / curr_vwap
        cross_up = prev_price <= prev_vwap and curr_price > curr_vwap
        cross_down = prev_price >= prev_vwap and curr_price < curr_vwap

        indicators = {
            "vwap": round(curr_vwap, 2),
            "price": round(curr_price, 2),
            "pct_from_vwap": round(pct_from_vwap * 100, 3),
        }

        if cross_up:
            confidence = min(abs(pct_from_vwap) * 10, 1.0)
            return {"signal": "buy", "confidence": round(max(confidence, 0.4), 3), "indicators": indicators}
        elif cross_down:
            confidence = min(abs(pct_from_vwap) * 10, 1.0)
            return {"signal": "sell", "confidence": round(max(confidence, 0.4), 3), "indicators": indicators}
        elif curr_price > curr_vwap and pct_from_vwap > 0.02:
            return {"signal": "buy", "confidence": round(min(pct_from_vwap * 5, 0.6), 3), "indicators": indicators}
        elif curr_price < curr_vwap and pct_from_vwap < -0.02:
            return {"signal": "sell", "confidence": round(min(abs(pct_from_vwap) * 5, 0.6), 3), "indicators": indicators}

        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
