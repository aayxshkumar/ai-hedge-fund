"""Opening Range Breakout (ORB) strategy.

Identifies the first N bars' high/low as the opening range, then generates
signals when price breaks above (buy) or below (sell) that range with volume
confirmation.  Adapted for daily OHLC — uses the first bar's range.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig


class OpeningRangeBreakoutStrategy:

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()
        self.range_bars = 1   # first bar defines the range
        self.atr_period = 14

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < max(self.atr_period + 5, self.range_bars + 1):
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high = price_df["high"] if "high" in price_df.columns else price_df["High"]
        low = price_df["low"] if "low" in price_df.columns else price_df["Low"]
        close = price_df["close"] if "close" in price_df.columns else price_df["Close"]
        vol = price_df["volume"] if "volume" in price_df.columns else price_df.get("Volume")

        # ATR for normalization
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self.atr_period).mean()

        range_high = float(high.iloc[:self.range_bars].max())
        range_low = float(low.iloc[:self.range_bars].min())
        last_close = float(close.iloc[-1])
        current_atr = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 1.0

        breakout_up = last_close > range_high
        breakout_down = last_close < range_low
        distance = abs(last_close - (range_high if breakout_up else range_low))
        norm_distance = distance / current_atr if current_atr > 0 else 0

        vol_ok = True
        if vol is not None and len(vol) >= 21:
            avg_vol = float(vol.iloc[-21:-1].mean())
            vol_ok = float(vol.iloc[-1]) > avg_vol * 1.2

        if breakout_up and vol_ok:
            conf = min(norm_distance * 0.4 + 0.3, 0.9)
            return {
                "signal": "buy",
                "confidence": round(conf, 3),
                "indicators": {"range_high": range_high, "range_low": range_low, "atr": round(current_atr, 2), "breakout": "up"},
            }
        elif breakout_down and vol_ok:
            conf = min(norm_distance * 0.4 + 0.3, 0.9)
            return {
                "signal": "sell",
                "confidence": round(conf, 3),
                "indicators": {"range_high": range_high, "range_low": range_low, "atr": round(current_atr, 2), "breakout": "down"},
            }

        return {"signal": "hold", "confidence": 0.0, "indicators": {"range_high": range_high, "range_low": range_low}}
