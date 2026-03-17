"""Cloud Oscillator: Ichimoku Cloud + Stochastic RSI.

Uses Ichimoku Cloud for trend direction and Stochastic RSI for entry timing.
Enters long when price is above the cloud and StochRSI crosses up from oversold,
and vice versa for shorts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class CloudOscillatorStrategy:
    def __init__(self, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52,
                 rsi_period: int = 14, stoch_period: int = 14, k_smooth: int = 3):
        self.tenkan = tenkan
        self.kijun = kijun
        self.senkou_b = senkou_b
        self.rsi_period = rsi_period
        self.stoch_period = stoch_period
        self.k_smooth = k_smooth

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = self.senkou_b + 30
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high, low, close = price_df["high"], price_df["low"], price_df["close"]

        tenkan_sen = (high.rolling(self.tenkan).max() + low.rolling(self.tenkan).min()) / 2
        kijun_sen = (high.rolling(self.kijun).max() + low.rolling(self.kijun).min()) / 2
        senkou_a = (tenkan_sen + kijun_sen) / 2
        senkou_b = (high.rolling(self.senkou_b).max() + low.rolling(self.senkou_b).min()) / 2

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)

        stoch_rsi_raw = (rsi - rsi.rolling(self.stoch_period).min()) / \
                        (rsi.rolling(self.stoch_period).max() - rsi.rolling(self.stoch_period).min()).replace(0, np.nan)
        k_line = stoch_rsi_raw.rolling(self.k_smooth).mean() * 100
        d_line = k_line.rolling(self.k_smooth).mean()

        curr_price = close.iloc[-1]
        cloud_top = max(senkou_a.iloc[-1], senkou_b.iloc[-1])
        cloud_bottom = min(senkou_a.iloc[-1], senkou_b.iloc[-1])
        above_cloud = curr_price > cloud_top
        below_cloud = curr_price < cloud_bottom
        in_cloud = not above_cloud and not below_cloud

        curr_k = k_line.iloc[-1] if not np.isnan(k_line.iloc[-1]) else 50
        curr_d = d_line.iloc[-1] if not np.isnan(d_line.iloc[-1]) else 50
        prev_k = k_line.iloc[-2] if not np.isnan(k_line.iloc[-2]) else 50
        prev_d = d_line.iloc[-2] if not np.isnan(d_line.iloc[-2]) else 50

        indicators = {
            "above_cloud": above_cloud,
            "below_cloud": below_cloud,
            "stoch_k": round(float(curr_k), 2),
            "stoch_d": round(float(curr_d), 2),
            "cloud_top": round(float(cloud_top), 2),
            "cloud_bottom": round(float(cloud_bottom), 2),
        }

        k_cross_up = prev_k <= prev_d and curr_k > curr_d
        k_cross_down = prev_k >= prev_d and curr_k < curr_d
        oversold = curr_k < 20
        overbought = curr_k > 80

        score = 0.0
        if above_cloud and k_cross_up and oversold:
            score = 0.9
        elif above_cloud and k_cross_up:
            score = 0.65
        elif above_cloud and curr_k > curr_d:
            score = 0.3
        elif below_cloud and k_cross_down and overbought:
            score = -0.9
        elif below_cloud and k_cross_down:
            score = -0.65
        elif below_cloud and curr_k < curr_d:
            score = -0.3
        elif in_cloud:
            score = 0.0

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
