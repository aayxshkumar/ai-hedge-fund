"""Mean-reversion strategy using Bollinger Bands + RSI.

Identifies stocks that have deviated significantly from their moving average and
are likely to revert.  Works best in range-bound / sideways markets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig


class MeanReversionStrategy:
    """Bollinger-Band based mean reversion signals."""

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()

    def analyse(self, price_df: pd.DataFrame) -> dict:
        if price_df is None or len(price_df) < self.cfg.mean_rev_bb_period + 10:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]

        sma = close.rolling(window=self.cfg.mean_rev_bb_period).mean()
        std = close.rolling(window=self.cfg.mean_rev_bb_period).std()
        upper_band = sma + self.cfg.mean_rev_bb_std * std
        lower_band = sma - self.cfg.mean_rev_bb_std * std

        # Z-score: how many std devs away from the mean
        zscore = (close - sma) / std.replace(0, np.nan)

        # RSI for confirmation
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=self.cfg.mean_rev_rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=self.cfg.mean_rev_rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_val = 100 - (100 / (1 + rs))

        curr_price = close.iloc[-1]
        curr_zscore = zscore.iloc[-1]
        curr_rsi = rsi_val.iloc[-1]
        curr_upper = upper_band.iloc[-1]
        curr_lower = lower_band.iloc[-1]
        curr_sma = sma.iloc[-1]

        indicators = {
            "bb_upper": round(curr_upper, 2),
            "bb_lower": round(curr_lower, 2),
            "bb_sma": round(curr_sma, 2),
            "zscore": round(curr_zscore, 3) if not np.isnan(curr_zscore) else 0,
            "rsi": round(curr_rsi, 2) if not np.isnan(curr_rsi) else 50,
        }

        score = 0.0

        if curr_zscore < -self.cfg.mean_rev_bb_std:
            score += 0.5  # below lower band = oversold
        elif curr_zscore < -1.0:
            score += 0.25

        if curr_zscore > self.cfg.mean_rev_bb_std:
            score -= 0.5  # above upper band = overbought
        elif curr_zscore > 1.0:
            score -= 0.25

        # RSI confirmation
        if curr_rsi < 30:
            score += 0.3
        elif curr_rsi > 70:
            score -= 0.3

        # Price relative to SMA
        pct_from_mean = (curr_price - curr_sma) / curr_sma if curr_sma > 0 else 0
        if abs(pct_from_mean) > 0.05:
            score += -np.sign(pct_from_mean) * 0.2

        confidence = min(abs(score), 1.0)

        if score > 0.2:
            signal = "buy"
        elif score < -0.2:
            signal = "sell"
        else:
            signal = "hold"

        return {"signal": signal, "confidence": round(confidence, 3), "indicators": indicators}
