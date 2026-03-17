"""Donchian Trailing: Donchian breakout + ATR trailing stop.

Enters on N-day high/low breakout (Turtle Traders style) and manages the
position with an ATR-based trailing stop. This hybrid approach captures
large trend moves while protecting against reversals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import atr as _atr


class DonchianTrailingStrategy:
    def __init__(self, entry_period: int = 20, exit_period: int = 10,
                 atr_period: int = 14, atr_mult: float = 2.0):
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.atr_period = atr_period
        self.atr_mult = atr_mult

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = max(self.entry_period, self.atr_period) + 15
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high, low, close = price_df["high"], price_df["low"], price_df["close"]

        entry_high = high.rolling(self.entry_period).max()
        entry_low = low.rolling(self.entry_period).min()
        exit_high = high.rolling(self.exit_period).max()
        exit_low = low.rolling(self.exit_period).min()
        atr = _atr(high, low, close, self.atr_period)

        curr_price = close.iloc[-1]
        prev_price = close.iloc[-2]
        curr_entry_high = entry_high.iloc[-2]
        curr_entry_low = entry_low.iloc[-2]
        curr_exit_low = exit_low.iloc[-2]
        curr_exit_high = exit_high.iloc[-2]
        curr_atr = atr.iloc[-1] if not np.isnan(atr.iloc[-1]) else 0

        trailing_stop_long = curr_price - self.atr_mult * curr_atr
        trailing_stop_short = curr_price + self.atr_mult * curr_atr

        breakout_up = curr_price > curr_entry_high and prev_price <= entry_high.iloc[-3]
        breakout_down = curr_price < curr_entry_low and prev_price >= entry_low.iloc[-3]

        channel_width = (curr_entry_high - curr_entry_low)
        pct_in_channel = (curr_price - curr_entry_low) / channel_width if channel_width > 0 else 0.5

        indicators = {
            "entry_high": round(float(curr_entry_high), 2),
            "entry_low": round(float(curr_entry_low), 2),
            "trailing_stop_long": round(float(trailing_stop_long), 2),
            "trailing_stop_short": round(float(trailing_stop_short), 2),
            "atr": round(float(curr_atr), 2),
            "breakout_up": breakout_up,
            "breakout_down": breakout_down,
        }

        score = 0.0
        if breakout_up:
            atr_pct = curr_atr / curr_price if curr_price else 0
            score = 0.7 + min(atr_pct * 10, 0.3)
        elif breakout_down:
            atr_pct = curr_atr / curr_price if curr_price else 0
            score = -(0.7 + min(atr_pct * 10, 0.3))
        elif pct_in_channel > 0.8:
            score = 0.3
        elif pct_in_channel < 0.2:
            score = -0.3
        elif curr_price < curr_exit_low:
            score = -0.5
        elif curr_price > curr_exit_high:
            score = 0.5

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
