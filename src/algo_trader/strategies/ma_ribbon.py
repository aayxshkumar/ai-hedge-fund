"""Moving Average Ribbon strategy.

Uses a fan of 8 EMAs (8, 13, 21, 34, 55, 89, 144, 200) to gauge trend strength
and direction.  When EMAs are stacked in order (short above long) the trend is
strong; compression signals potential reversal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


EMA_PERIODS = [8, 13, 21, 34, 55, 89, 144, 200]


class MARibbonStrategy:
    def __init__(self, periods: list[int] | None = None):
        self.periods = periods or EMA_PERIODS

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = max(self.periods) + 10
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]
        emas = {p: close.ewm(span=p, adjust=False).mean() for p in self.periods}

        curr_emas = [emas[p].iloc[-1] for p in self.periods]
        prev_emas = [emas[p].iloc[-2] for p in self.periods]

        bullish_order = all(curr_emas[i] >= curr_emas[i + 1] for i in range(len(curr_emas) - 1))
        bearish_order = all(curr_emas[i] <= curr_emas[i + 1] for i in range(len(curr_emas) - 1))

        spread = (curr_emas[0] - curr_emas[-1]) / curr_emas[-1] if curr_emas[-1] else 0
        prev_spread = (prev_emas[0] - prev_emas[-1]) / prev_emas[-1] if prev_emas[-1] else 0
        expanding = abs(spread) > abs(prev_spread)

        price_above_all = close.iloc[-1] > max(curr_emas)
        price_below_all = close.iloc[-1] < min(curr_emas)

        indicators = {
            "ema_short": round(curr_emas[0], 2),
            "ema_long": round(curr_emas[-1], 2),
            "spread_pct": round(spread * 100, 3),
            "bullish_order": bullish_order,
            "bearish_order": bearish_order,
            "expanding": expanding,
        }

        score = 0.0
        if bullish_order:
            score += 0.4
        elif bearish_order:
            score -= 0.4

        if expanding:
            score += 0.2 * np.sign(score) if score != 0 else 0

        if price_above_all:
            score += 0.25
        elif price_below_all:
            score -= 0.25

        score += min(abs(spread) * 5, 0.3) * np.sign(spread)

        confidence = min(abs(score), 1.0)
        if score > 0.2:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.2:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
