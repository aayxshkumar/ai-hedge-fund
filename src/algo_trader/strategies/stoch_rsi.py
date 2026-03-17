"""Stochastic RSI strategy.

Applies the Stochastic oscillator to RSI values, producing a more sensitive
overbought/oversold indicator.  K/D crossovers in extreme zones trigger signals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import rsi as _rsi


class StochRSIStrategy:
    def __init__(self, rsi_period: int = 14, stoch_period: int = 14, k_smooth: int = 3, d_smooth: int = 3):
        self.rsi_period = rsi_period
        self.stoch_period = stoch_period
        self.k_smooth = k_smooth
        self.d_smooth = d_smooth

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = self.rsi_period + self.stoch_period + self.d_smooth + 10
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]
        rsi_vals = _rsi(close, self.rsi_period)

        rsi_min = rsi_vals.rolling(self.stoch_period).min()
        rsi_max = rsi_vals.rolling(self.stoch_period).max()
        rsi_range = (rsi_max - rsi_min).replace(0, np.nan)
        stoch_rsi = (rsi_vals - rsi_min) / rsi_range

        k_line = stoch_rsi.rolling(self.k_smooth).mean() * 100
        d_line = k_line.rolling(self.d_smooth).mean()

        curr_k = k_line.iloc[-1]
        curr_d = d_line.iloc[-1]
        prev_k = k_line.iloc[-2]
        prev_d = d_line.iloc[-2]

        if any(np.isnan(v) for v in [curr_k, curr_d, prev_k, prev_d]):
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        indicators = {
            "stoch_rsi_k": round(curr_k, 2),
            "stoch_rsi_d": round(curr_d, 2),
            "rsi": round(rsi_vals.iloc[-1], 2) if not np.isnan(rsi_vals.iloc[-1]) else 50,
        }

        cross_up = prev_k <= prev_d and curr_k > curr_d
        cross_down = prev_k >= prev_d and curr_k < curr_d
        oversold = curr_k < 20
        overbought = curr_k > 80

        if cross_up and oversold:
            return {"signal": "buy", "confidence": round(min((20 - curr_k) / 20 * 0.5 + 0.5, 1.0), 3), "indicators": indicators}
        elif cross_down and overbought:
            return {"signal": "sell", "confidence": round(min((curr_k - 80) / 20 * 0.5 + 0.5, 1.0), 3), "indicators": indicators}
        elif cross_up and curr_k < 50:
            return {"signal": "buy", "confidence": 0.35, "indicators": indicators}
        elif cross_down and curr_k > 50:
            return {"signal": "sell", "confidence": 0.35, "indicators": indicators}

        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
