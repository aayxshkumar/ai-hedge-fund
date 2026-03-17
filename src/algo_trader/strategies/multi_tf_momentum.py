"""Multi-Timeframe Momentum: EMA ribbon + RSI + volume breakout.

A triple-confirmation momentum strategy that requires:
1. EMA ribbon alignment (short > long)
2. RSI in trending range (50-70 for longs, 30-50 for shorts)
3. Volume exceeding its moving average

All three must align for a high-confidence signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class MultiTFMomentumStrategy:
    def __init__(self, ribbon_lengths: list[int] | None = None,
                 rsi_period: int = 14, vol_period: int = 20, vol_mult: float = 1.3):
        self.ribbon_lengths = ribbon_lengths or [8, 13, 21, 34, 55]
        self.rsi_period = rsi_period
        self.vol_period = vol_period
        self.vol_mult = vol_mult

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = max(max(self.ribbon_lengths), self.rsi_period, self.vol_period) + 15
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]
        volume = price_df["volume"] if "volume" in price_df.columns else pd.Series(1, index=close.index)

        emas = {p: close.ewm(span=p, adjust=False).mean() for p in self.ribbon_lengths}
        ribbon_vals = [emas[p].iloc[-1] for p in sorted(self.ribbon_lengths)]
        ribbon_bullish = all(ribbon_vals[i] >= ribbon_vals[i + 1] for i in range(len(ribbon_vals) - 1))
        ribbon_bearish = all(ribbon_vals[i] <= ribbon_vals[i + 1] for i in range(len(ribbon_vals) - 1))

        short_ema = ribbon_vals[0]
        long_ema = ribbon_vals[-1]
        ribbon_spread = (short_ema - long_ema) / long_ema if long_ema else 0
        ribbon_expanding = abs(ribbon_spread) > abs(
            (emas[self.ribbon_lengths[0]].iloc[-2] - emas[self.ribbon_lengths[-1]].iloc[-2]) /
            emas[self.ribbon_lengths[-1]].iloc[-2]
        ) if emas[self.ribbon_lengths[-1]].iloc[-2] else False

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        curr_rsi = rsi.iloc[-1] if not np.isnan(rsi.iloc[-1]) else 50

        avg_vol = volume.rolling(self.vol_period).mean()
        vol_breakout = volume.iloc[-1] > self.vol_mult * avg_vol.iloc[-1] if avg_vol.iloc[-1] > 0 else False

        indicators = {
            "ribbon_bullish": ribbon_bullish,
            "ribbon_bearish": ribbon_bearish,
            "ribbon_expanding": ribbon_expanding,
            "ribbon_spread_pct": round(float(ribbon_spread * 100), 2),
            "rsi": round(float(curr_rsi), 2),
            "volume_breakout": vol_breakout,
        }

        bull_signals = 0
        bear_signals = 0

        if ribbon_bullish:
            bull_signals += 1
        if ribbon_bearish:
            bear_signals += 1
        if ribbon_expanding and ribbon_bullish:
            bull_signals += 0.5
        if ribbon_expanding and ribbon_bearish:
            bear_signals += 0.5

        if 45 < curr_rsi < 75:
            bull_signals += 1
        if 25 < curr_rsi < 55:
            bear_signals += 1
        if curr_rsi > 70:
            bull_signals += 0.3
        if curr_rsi < 30:
            bear_signals += 0.3

        if vol_breakout:
            bull_signals += 1
            bear_signals += 1

        score = 0.0
        if bull_signals >= 3.0 and bull_signals > bear_signals:
            score = min(bull_signals / 3.5, 1.0)
        elif bear_signals >= 3.0 and bear_signals > bull_signals:
            score = -min(bear_signals / 3.5, 1.0)
        elif bull_signals >= 2.0 and bull_signals > bear_signals:
            score = 0.3
        elif bear_signals >= 2.0 and bear_signals > bull_signals:
            score = -0.3

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
