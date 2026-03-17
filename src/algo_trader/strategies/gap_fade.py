"""Gap-fade strategy — fades overnight gaps with volume confirmation.

Logic: large gap-up → often retraces → sell (fade).  Large gap-down → often
bounces → buy (fade).  Only fires when volume is above average (liquidity).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig


class GapFadeStrategy:

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()
        self.min_gap_pct = 1.5    # minimum gap size to trigger
        self.vol_mult = 1.3       # volume must exceed this multiple of 20d avg

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < 22:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        open_col = price_df["open"] if "open" in price_df.columns else price_df["Open"]
        close = price_df["close"] if "close" in price_df.columns else price_df["Close"]
        vol = price_df["volume"] if "volume" in price_df.columns else price_df.get("Volume")

        prev_close = float(close.iloc[-2])
        today_open = float(open_col.iloc[-1])
        today_close = float(close.iloc[-1])

        if prev_close == 0:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        gap_pct = ((today_open - prev_close) / prev_close) * 100

        vol_ok = True
        if vol is not None and len(vol) >= 21:
            avg_vol = float(vol.iloc[-21:-1].mean())
            vol_ok = float(vol.iloc[-1]) > avg_vol * self.vol_mult

        gap_filling = False
        if gap_pct > 0:
            gap_filling = today_close < today_open
        elif gap_pct < 0:
            gap_filling = today_close > today_open

        indicators = {
            "gap_pct": round(gap_pct, 2),
            "gap_filling": gap_filling,
            "volume_ok": vol_ok,
        }

        if abs(gap_pct) < self.min_gap_pct or not vol_ok:
            return {"signal": "hold", "confidence": 0.0, "indicators": indicators}

        strength = min(abs(gap_pct) / 5.0, 1.0)

        if gap_pct > self.min_gap_pct:
            conf = strength * (0.7 if gap_filling else 0.4)
            return {"signal": "sell", "confidence": round(conf, 3), "indicators": indicators}
        elif gap_pct < -self.min_gap_pct:
            conf = strength * (0.7 if gap_filling else 0.4)
            return {"signal": "buy", "confidence": round(conf, 3), "indicators": indicators}

        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
