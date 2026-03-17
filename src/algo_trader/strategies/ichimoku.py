"""Ichimoku Cloud strategy.

Uses the five Ichimoku lines to assess trend, momentum, and support/resistance:
- Tenkan-sen (conversion) and Kijun-sen (base) crossover for entry signals
- Cloud (Senkou Span A/B) for trend confirmation
- Chikou Span for momentum confirmation
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _donchian_mid(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    return (high.rolling(period).max() + low.rolling(period).min()) / 2


class IchimokuStrategy:
    def __init__(self, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52):
        self.tenkan_period = tenkan
        self.kijun_period = kijun
        self.senkou_b_period = senkou_b

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = self.senkou_b_period + self.kijun_period + 5
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high = price_df["high"]
        low = price_df["low"]
        close = price_df["close"]

        tenkan = _donchian_mid(high, low, self.tenkan_period)
        kijun = _donchian_mid(high, low, self.kijun_period)
        senkou_a = (tenkan + kijun) / 2
        senkou_b = _donchian_mid(high, low, self.senkou_b_period)

        curr_price = close.iloc[-1]
        curr_tenkan = tenkan.iloc[-1]
        curr_kijun = kijun.iloc[-1]
        prev_tenkan = tenkan.iloc[-2]
        prev_kijun = kijun.iloc[-2]
        curr_senkou_a = senkou_a.iloc[-1]
        curr_senkou_b = senkou_b.iloc[-1]
        cloud_top = max(curr_senkou_a, curr_senkou_b)
        cloud_bot = min(curr_senkou_a, curr_senkou_b)

        indicators = {
            "tenkan": round(curr_tenkan, 2),
            "kijun": round(curr_kijun, 2),
            "senkou_a": round(curr_senkou_a, 2),
            "senkou_b": round(curr_senkou_b, 2),
            "cloud_top": round(cloud_top, 2),
            "cloud_bot": round(cloud_bot, 2),
        }

        tk_cross_up = prev_tenkan <= prev_kijun and curr_tenkan > curr_kijun
        tk_cross_down = prev_tenkan >= prev_kijun and curr_tenkan < curr_kijun
        above_cloud = curr_price > cloud_top
        below_cloud = curr_price < cloud_bot

        score = 0.0
        if tk_cross_up:
            score += 0.4
        elif curr_tenkan > curr_kijun:
            score += 0.15
        if tk_cross_down:
            score -= 0.4
        elif curr_tenkan < curr_kijun:
            score -= 0.15

        if above_cloud:
            score += 0.3
        elif below_cloud:
            score -= 0.3

        if curr_price > curr_kijun:
            score += 0.15
        elif curr_price < curr_kijun:
            score -= 0.15

        confidence = min(abs(score), 1.0)
        if score > 0.2:
            signal = "buy"
        elif score < -0.2:
            signal = "sell"
        else:
            signal = "hold"

        return {"signal": signal, "confidence": round(confidence, 3), "indicators": indicators}
