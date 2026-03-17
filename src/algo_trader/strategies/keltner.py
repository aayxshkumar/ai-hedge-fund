"""Keltner Channel strategy.

EMA-centered channel with ATR-based bands.  Particularly powerful when combined
with a Bollinger Band squeeze detection: when BB contracts inside Keltner it
signals an imminent volatility expansion.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import atr as _atr


class KeltnerChannelStrategy:
    def __init__(self, ema_period: int = 20, atr_period: int = 10, atr_mult: float = 1.5):
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.atr_mult = atr_mult

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = max(self.ema_period, self.atr_period) + 10
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high = price_df["high"]
        low = price_df["low"]
        close = price_df["close"]

        ema = close.ewm(span=self.ema_period, adjust=False).mean()
        atr = _atr(high, low, close, self.atr_period)
        upper = ema + self.atr_mult * atr
        lower = ema - self.atr_mult * atr

        # Bollinger Band squeeze detection
        bb_std = close.rolling(self.ema_period).std()
        bb_upper = close.rolling(self.ema_period).mean() + 2 * bb_std
        bb_lower = close.rolling(self.ema_period).mean() - 2 * bb_std

        curr_price = close.iloc[-1]
        curr_upper = upper.iloc[-1]
        curr_lower = lower.iloc[-1]
        curr_ema = ema.iloc[-1]

        squeeze = bb_upper.iloc[-1] < curr_upper and bb_lower.iloc[-1] > curr_lower
        prev_squeeze = bb_upper.iloc[-2] < upper.iloc[-2] and bb_lower.iloc[-2] > lower.iloc[-2]
        squeeze_release = prev_squeeze and not squeeze

        indicators = {
            "keltner_upper": round(curr_upper, 2),
            "keltner_lower": round(curr_lower, 2),
            "keltner_mid": round(curr_ema, 2),
            "atr": round(atr.iloc[-1], 2) if not np.isnan(atr.iloc[-1]) else 0,
            "squeeze": squeeze,
            "squeeze_release": squeeze_release,
        }

        pct_pos = (curr_price - curr_lower) / (curr_upper - curr_lower) if (curr_upper - curr_lower) > 0 else 0.5

        score = 0.0
        if squeeze_release:
            direction = 1.0 if curr_price > curr_ema else -1.0
            score += direction * 0.5

        if curr_price > curr_upper:
            score += 0.4
        elif curr_price < curr_lower:
            score -= 0.4
        elif curr_price > curr_ema:
            score += 0.15
        elif curr_price < curr_ema:
            score -= 0.15

        confidence = min(abs(score), 1.0)
        if score > 0.2:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.2:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
