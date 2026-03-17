"""VWAP Momentum: VWAP crossover + MACD histogram.

Combines VWAP position (institutional fair value) with MACD histogram direction
for momentum confirmation. Entries occur when price crosses VWAP and MACD
histogram aligns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class VWAPMomentumStrategy:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = self.slow + self.signal + 5
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high, low, close = price_df["high"], price_df["low"], price_df["close"]
        volume = price_df["volume"] if "volume" in price_df.columns else pd.Series(1, index=close.index)

        typical = (high + low + close) / 3
        cum_tp_vol = (typical * volume).cumsum()
        cum_vol = volume.cumsum()
        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)

        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()
        histogram = macd_line - signal_line

        curr_price = close.iloc[-1]
        curr_vwap = vwap.iloc[-1] if not np.isnan(vwap.iloc[-1]) else curr_price
        prev_price = close.iloc[-2]
        prev_vwap = vwap.iloc[-2] if not np.isnan(vwap.iloc[-2]) else prev_price
        curr_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2]

        indicators = {
            "vwap": round(float(curr_vwap), 2),
            "macd_histogram": round(float(curr_hist), 4),
            "price_vs_vwap": round(float((curr_price - curr_vwap) / curr_vwap * 100), 2) if curr_vwap else 0,
        }

        vwap_cross_up = prev_price <= prev_vwap and curr_price > curr_vwap
        vwap_cross_down = prev_price >= prev_vwap and curr_price < curr_vwap
        hist_rising = curr_hist > prev_hist
        hist_positive = curr_hist > 0
        hist_negative = curr_hist < 0

        score = 0.0
        if vwap_cross_up and hist_positive and hist_rising:
            score = 0.85
        elif vwap_cross_up and hist_rising:
            score = 0.6
        elif vwap_cross_down and hist_negative and not hist_rising:
            score = -0.85
        elif vwap_cross_down and not hist_rising:
            score = -0.6
        elif curr_price > curr_vwap and hist_positive:
            score = 0.3
        elif curr_price < curr_vwap and hist_negative:
            score = -0.3

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
