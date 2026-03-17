"""Volume Divergence Trend: OBV divergence + MA Ribbon direction.

Detects divergence between On-Balance Volume and price, then confirms with
the direction of the 8-EMA ribbon. When OBV diverges bullishly (price makes
lower low but OBV makes higher low) and the ribbon expands upward, a strong
buy is generated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class VolumeTrendStrategy:
    def __init__(self, lookback: int = 20, ribbon_lengths: list[int] | None = None):
        self.lookback = lookback
        self.ribbon_lengths = ribbon_lengths or [8, 13, 21, 34, 55, 89, 144, 200]

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = max(self.ribbon_lengths) + self.lookback
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]
        volume = price_df["volume"] if "volume" in price_df.columns else pd.Series(1, index=close.index)

        obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()

        emas = {p: close.ewm(span=p, adjust=False).mean() for p in self.ribbon_lengths}

        price_ll = close.iloc[-1] < close.iloc[-self.lookback:].min() * 1.01
        obv_hl = obv.iloc[-1] > obv.iloc[-self.lookback:].min()
        bull_divergence = price_ll and obv_hl

        price_hh = close.iloc[-1] > close.iloc[-self.lookback:].max() * 0.99
        obv_lh = obv.iloc[-1] < obv.iloc[-self.lookback:].max()
        bear_divergence = price_hh and obv_lh

        ribbon_vals = [emas[p].iloc[-1] for p in sorted(self.ribbon_lengths)]
        ribbon_ordered_up = all(ribbon_vals[i] >= ribbon_vals[i + 1] for i in range(len(ribbon_vals) - 1))
        ribbon_ordered_down = all(ribbon_vals[i] <= ribbon_vals[i + 1] for i in range(len(ribbon_vals) - 1))

        short_ema = emas[self.ribbon_lengths[0]].iloc[-1]
        long_ema = emas[self.ribbon_lengths[-1]].iloc[-1]
        ribbon_spread = (short_ema - long_ema) / long_ema if long_ema else 0
        ribbon_bullish = ribbon_spread > 0.005
        ribbon_bearish = ribbon_spread < -0.005

        indicators = {
            "obv": round(float(obv.iloc[-1]), 0),
            "bull_divergence": bull_divergence,
            "bear_divergence": bear_divergence,
            "ribbon_spread_pct": round(float(ribbon_spread * 100), 2),
            "ribbon_ordered_up": ribbon_ordered_up,
        }

        score = 0.0
        if bull_divergence and ribbon_bullish:
            score = 0.85
        elif bull_divergence and ribbon_ordered_up:
            score = 0.7
        elif bull_divergence:
            score = 0.4
        elif bear_divergence and ribbon_bearish:
            score = -0.85
        elif bear_divergence and ribbon_ordered_down:
            score = -0.7
        elif bear_divergence:
            score = -0.4
        elif ribbon_bullish:
            score = 0.2
        elif ribbon_bearish:
            score = -0.2

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
