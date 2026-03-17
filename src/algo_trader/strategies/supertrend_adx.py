"""Trend Momentum Fusion: Supertrend + ADX.

Combines Supertrend direction flips with ADX trend strength confirmation.
Only takes signals when ADX indicates a strong trend (>25), avoiding whipsaws
in ranging markets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import atr as _atr, adx as _adx


class SupertrendADXStrategy:
    def __init__(self, st_period: int = 10, st_mult: float = 3.0, adx_period: int = 14, adx_threshold: float = 25.0):
        self.st_period = st_period
        self.st_mult = st_mult
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = max(self.st_period, self.adx_period) + 20
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high, low, close = price_df["high"], price_df["low"], price_df["close"]

        atr = _atr(high, low, close, self.st_period)
        hl2 = (high + low) / 2
        upper_band = hl2 + self.st_mult * atr
        lower_band = hl2 - self.st_mult * atr

        direction = pd.Series(1, index=close.index)
        supertrend = pd.Series(np.nan, index=close.index)

        for i in range(self.st_period, len(close)):
            if close.iloc[i] > upper_band.iloc[i - 1]:
                direction.iloc[i] = 1
            elif close.iloc[i] < lower_band.iloc[i - 1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]

            if direction.iloc[i] == 1:
                prev_st = supertrend.iloc[i - 1] if not np.isnan(supertrend.iloc[i - 1]) and direction.iloc[i - 1] == 1 else lower_band.iloc[i]
                supertrend.iloc[i] = max(lower_band.iloc[i], prev_st)
            else:
                prev_st = supertrend.iloc[i - 1] if not np.isnan(supertrend.iloc[i - 1]) and direction.iloc[i - 1] == -1 else upper_band.iloc[i]
                supertrend.iloc[i] = min(upper_band.iloc[i], prev_st)

        adx, plus_di, minus_di = _adx(high, low, close, self.adx_period)

        curr_dir = direction.iloc[-1]
        prev_dir = direction.iloc[-2]
        curr_adx = adx.iloc[-1] if not np.isnan(adx.iloc[-1]) else 0
        curr_plus_di = plus_di.iloc[-1] if not np.isnan(plus_di.iloc[-1]) else 0
        curr_minus_di = minus_di.iloc[-1] if not np.isnan(minus_di.iloc[-1]) else 0

        indicators = {
            "supertrend_dir": int(curr_dir),
            "adx": round(curr_adx, 2),
            "plus_di": round(curr_plus_di, 2),
            "minus_di": round(curr_minus_di, 2),
        }

        flip_bull = prev_dir == -1 and curr_dir == 1
        flip_bear = prev_dir == 1 and curr_dir == -1
        strong_trend = curr_adx >= self.adx_threshold
        di_confirm_bull = curr_plus_di > curr_minus_di
        di_confirm_bear = curr_minus_di > curr_plus_di

        score = 0.0
        if flip_bull and strong_trend and di_confirm_bull:
            score = 0.9
        elif flip_bull and strong_trend:
            score = 0.7
        elif flip_bull:
            score = 0.4
        elif flip_bear and strong_trend and di_confirm_bear:
            score = -0.9
        elif flip_bear and strong_trend:
            score = -0.7
        elif flip_bear:
            score = -0.4
        elif curr_dir == 1 and strong_trend and di_confirm_bull:
            score = 0.35
        elif curr_dir == -1 and strong_trend and di_confirm_bear:
            score = -0.35

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
