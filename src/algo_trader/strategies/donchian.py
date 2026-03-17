"""Donchian Channel Breakout strategy.

Classic trend-following: buy when price breaks above the N-day high, sell when it
breaks below the N-day low, exit at the midline.  Used by the Turtle Traders.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class DonchianBreakoutStrategy:
    def __init__(self, entry_period: int = 20, exit_period: int = 10):
        self.entry_period = entry_period
        self.exit_period = exit_period

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < self.entry_period + 5:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high = price_df["high"]
        low = price_df["low"]
        close = price_df["close"]

        upper_entry = high.rolling(self.entry_period).max()
        lower_entry = low.rolling(self.entry_period).min()
        mid = (upper_entry + lower_entry) / 2

        upper_exit = high.rolling(self.exit_period).max()
        lower_exit = low.rolling(self.exit_period).min()

        curr = close.iloc[-1]
        prev = close.iloc[-2]

        indicators = {
            "upper_entry": round(upper_entry.iloc[-1], 2),
            "lower_entry": round(lower_entry.iloc[-1], 2),
            "mid": round(mid.iloc[-1], 2),
            "upper_exit": round(upper_exit.iloc[-1], 2),
            "lower_exit": round(lower_exit.iloc[-1], 2),
        }

        channel_width = (upper_entry.iloc[-1] - lower_entry.iloc[-1]) / mid.iloc[-1] if mid.iloc[-1] else 0

        breakout_up = prev < upper_entry.iloc[-2] and curr >= upper_entry.iloc[-1]
        breakout_down = prev > lower_entry.iloc[-2] and curr <= lower_entry.iloc[-1]

        if breakout_up:
            confidence = min(channel_width * 5, 1.0)
            return {"signal": "buy", "confidence": round(max(confidence, 0.5), 3), "indicators": indicators}
        elif breakout_down:
            confidence = min(channel_width * 5, 1.0)
            return {"signal": "sell", "confidence": round(max(confidence, 0.5), 3), "indicators": indicators}
        elif curr > mid.iloc[-1] and curr < upper_entry.iloc[-1]:
            return {"signal": "buy", "confidence": 0.25, "indicators": indicators}
        elif curr < mid.iloc[-1] and curr > lower_entry.iloc[-1]:
            return {"signal": "sell", "confidence": 0.25, "indicators": indicators}

        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
