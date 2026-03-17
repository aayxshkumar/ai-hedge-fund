"""Squeeze Breakout: Bollinger Bands inside Keltner Channel.

When Bollinger Bands contract inside the Keltner Channel, volatility is compressed.
The release of the squeeze, confirmed by above-average volume, signals an imminent
directional move.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import atr as _atr


class SqueezeBreakoutStrategy:
    def __init__(self, period: int = 20, bb_mult: float = 2.0, kc_mult: float = 1.5,
                 atr_period: int = 10, vol_mult: float = 1.5):
        self.period = period
        self.bb_mult = bb_mult
        self.kc_mult = kc_mult
        self.atr_period = atr_period
        self.vol_mult = vol_mult

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = self.period + 15
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high, low, close = price_df["high"], price_df["low"], price_df["close"]
        volume = price_df["volume"] if "volume" in price_df.columns else pd.Series(0, index=close.index)

        sma = close.rolling(self.period).mean()
        std = close.rolling(self.period).std()
        bb_upper = sma + self.bb_mult * std
        bb_lower = sma - self.bb_mult * std

        ema = close.ewm(span=self.period, adjust=False).mean()
        atr = _atr(high, low, close, self.atr_period)
        kc_upper = ema + self.kc_mult * atr
        kc_lower = ema - self.kc_mult * atr

        squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)
        momentum = close - close.rolling(self.period).mean()
        avg_vol = volume.rolling(self.period).mean()

        indicators = {
            "in_squeeze": bool(squeeze.iloc[-1]),
            "prev_squeeze": bool(squeeze.iloc[-2]),
            "momentum": round(float(momentum.iloc[-1]), 2),
            "volume_ratio": round(float(volume.iloc[-1] / avg_vol.iloc[-1]), 2) if avg_vol.iloc[-1] > 0 else 0,
        }

        squeeze_release = squeeze.iloc[-2] and not squeeze.iloc[-1]
        vol_confirm = volume.iloc[-1] > self.vol_mult * avg_vol.iloc[-1] if avg_vol.iloc[-1] > 0 else False
        mom_val = momentum.iloc[-1]
        mom_rising = momentum.iloc[-1] > momentum.iloc[-2]

        score = 0.0
        if squeeze_release and mom_val > 0 and mom_rising:
            score = 0.6 + (0.3 if vol_confirm else 0.0)
        elif squeeze_release and mom_val < 0 and not mom_rising:
            score = -(0.6 + (0.3 if vol_confirm else 0.0))
        elif squeeze.iloc[-1]:
            score = 0.0
        elif mom_val > 0 and vol_confirm:
            score = 0.3
        elif mom_val < 0 and vol_confirm:
            score = -0.3

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
