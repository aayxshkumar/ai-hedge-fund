"""Supertrend strategy.

Uses ATR-based dynamic bands to determine trend direction.  A flip from down-trend
to up-trend generates a buy signal and vice-versa.  Widely used on Indian markets
for intraday and positional trading.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import atr as _atr


class SupertrendStrategy:
    def __init__(self, period: int = 10, multiplier: float = 3.0):
        self.period = period
        self.multiplier = multiplier

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < self.period + 10:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high = price_df["high"]
        low = price_df["low"]
        close = price_df["close"]

        atr = _atr(high, low, close, self.period)
        hl2 = (high + low) / 2
        upper_band = hl2 + self.multiplier * atr
        lower_band = hl2 - self.multiplier * atr

        n = len(close)
        c = close.values
        ub = upper_band.values
        lb = lower_band.values
        st = np.full(n, np.nan)
        d = np.ones(n, dtype=np.int8)

        for i in range(self.period, n):
            if c[i] > ub[i - 1]:
                d[i] = 1
            elif c[i] < lb[i - 1]:
                d[i] = -1
            else:
                d[i] = d[i - 1]

            if d[i] == 1:
                prev_st = st[i - 1] if d[i - 1] == 1 and not np.isnan(st[i - 1]) else lb[i]
                st[i] = max(lb[i], prev_st)
            else:
                prev_st = st[i - 1] if d[i - 1] == -1 and not np.isnan(st[i - 1]) else ub[i]
                st[i] = min(ub[i], prev_st)

        curr_dir = int(d[-1])
        prev_dir = int(d[-2])
        curr_st = float(st[-1])

        indicators = {
            "supertrend": round(curr_st, 2) if not np.isnan(curr_st) else 0,
            "direction": int(curr_dir),
            "atr": round(atr.iloc[-1], 2) if not np.isnan(atr.iloc[-1]) else 0,
        }

        flip_bull = prev_dir == -1 and curr_dir == 1
        flip_bear = prev_dir == 1 and curr_dir == -1
        pct_from_st = (close.iloc[-1] - curr_st) / curr_st if curr_st and not np.isnan(curr_st) else 0

        if flip_bull:
            return {"signal": "buy", "confidence": round(min(abs(pct_from_st) * 8, 1.0), 3), "indicators": indicators}
        elif flip_bear:
            return {"signal": "sell", "confidence": round(min(abs(pct_from_st) * 8, 1.0), 3), "indicators": indicators}
        elif curr_dir == 1:
            return {"signal": "buy", "confidence": round(min(abs(pct_from_st) * 3, 0.5), 3), "indicators": indicators}
        elif curr_dir == -1:
            return {"signal": "sell", "confidence": round(min(abs(pct_from_st) * 3, 0.5), 3), "indicators": indicators}

        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
