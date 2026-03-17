"""ADX Trend-Following strategy.

Uses the Average Directional Index to gauge trend strength and the +DI/-DI
crossover for direction.  Only trades when ADX > 25 (strong trend present).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import wilder_smooth as _wilder_smooth


class ADXTrendStrategy:
    def __init__(self, period: int = 14, adx_threshold: float = 25.0):
        self.period = period
        self.adx_threshold = adx_threshold

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < self.period * 3:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high = price_df["high"].values
        low = price_df["low"].values
        close = price_df["close"].values
        n = len(close)

        up_move = np.diff(high, prepend=high[0])
        down_move = np.diff(-low, prepend=-low[0])
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))

        plus_dm_s = pd.Series(plus_dm)
        minus_dm_s = pd.Series(minus_dm)
        tr_s = pd.Series(tr)

        atr = _wilder_smooth(tr_s, self.period)
        plus_di_raw = _wilder_smooth(plus_dm_s, self.period)
        minus_di_raw = _wilder_smooth(minus_dm_s, self.period)

        plus_di = 100 * plus_di_raw / atr.replace(0, np.nan)
        minus_di = 100 * minus_di_raw / atr.replace(0, np.nan)

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.rolling(self.period).mean()

        curr_adx = adx.iloc[-1]
        curr_plus = plus_di.iloc[-1]
        curr_minus = minus_di.iloc[-1]
        prev_plus = plus_di.iloc[-2]
        prev_minus = minus_di.iloc[-2]

        if np.isnan(curr_adx):
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        indicators = {
            "adx": round(curr_adx, 2),
            "plus_di": round(curr_plus, 2),
            "minus_di": round(curr_minus, 2),
        }

        cross_up = prev_plus <= prev_minus and curr_plus > curr_minus
        cross_down = prev_plus >= prev_minus and curr_plus < curr_minus
        strong_trend = curr_adx >= self.adx_threshold

        if not strong_trend:
            return {"signal": "hold", "confidence": 0.0, "indicators": indicators}

        trend_strength = min((curr_adx - self.adx_threshold) / 25, 1.0)

        if cross_up:
            return {"signal": "buy", "confidence": round(min(0.5 + trend_strength * 0.5, 1.0), 3), "indicators": indicators}
        elif cross_down:
            return {"signal": "sell", "confidence": round(min(0.5 + trend_strength * 0.5, 1.0), 3), "indicators": indicators}
        elif curr_plus > curr_minus:
            return {"signal": "buy", "confidence": round(trend_strength * 0.5, 3), "indicators": indicators}
        elif curr_minus > curr_plus:
            return {"signal": "sell", "confidence": round(trend_strength * 0.5, 3), "indicators": indicators}

        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
