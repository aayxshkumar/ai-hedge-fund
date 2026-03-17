"""Volume Breakout strategy.

Identifies price breakouts confirmed by unusual volume (>2x 20-day average).
High-volume breakouts have a much higher probability of continuation than
low-volume ones.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class VolumeBreakoutStrategy:
    def __init__(self, price_lookback: int = 20, volume_mult: float = 2.0, breakout_pct: float = 0.02):
        self.price_lookback = price_lookback
        self.volume_mult = volume_mult
        self.breakout_pct = breakout_pct

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < self.price_lookback + 5:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]
        high = price_df["high"]
        low = price_df["low"]
        volume = price_df["volume"].fillna(0)

        avg_volume = volume.rolling(self.price_lookback).mean()
        resistance = high.rolling(self.price_lookback).max()
        support = low.rolling(self.price_lookback).min()

        curr_price = close.iloc[-1]
        curr_volume = volume.iloc[-1]
        curr_avg_vol = avg_volume.iloc[-1]
        curr_resistance = resistance.iloc[-2]  # Previous period's high (not including today)
        curr_support = support.iloc[-2]

        if np.isnan(curr_avg_vol) or curr_avg_vol == 0:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        vol_ratio = curr_volume / curr_avg_vol
        high_volume = vol_ratio >= self.volume_mult

        breakout_up = curr_price > curr_resistance * (1 + self.breakout_pct)
        breakout_down = curr_price < curr_support * (1 - self.breakout_pct)

        price_range = curr_resistance - curr_support
        position_in_range = (curr_price - curr_support) / price_range if price_range > 0 else 0.5

        indicators = {
            "volume_ratio": round(vol_ratio, 2),
            "resistance": round(curr_resistance, 2),
            "support": round(curr_support, 2),
            "high_volume": high_volume,
            "breakout_up": breakout_up,
            "breakout_down": breakout_down,
        }

        if breakout_up and high_volume:
            vol_confidence = min(vol_ratio / 4, 0.5)
            return {"signal": "buy", "confidence": round(0.5 + vol_confidence, 3), "indicators": indicators}
        elif breakout_down and high_volume:
            vol_confidence = min(vol_ratio / 4, 0.5)
            return {"signal": "sell", "confidence": round(0.5 + vol_confidence, 3), "indicators": indicators}
        elif breakout_up:
            return {"signal": "buy", "confidence": 0.3, "indicators": indicators}
        elif breakout_down:
            return {"signal": "sell", "confidence": 0.3, "indicators": indicators}
        elif high_volume and position_in_range > 0.8:
            return {"signal": "buy", "confidence": round(min(vol_ratio / 5, 0.4), 3), "indicators": indicators}
        elif high_volume and position_in_range < 0.2:
            return {"signal": "sell", "confidence": round(min(vol_ratio / 5, 0.4), 3), "indicators": indicators}

        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
