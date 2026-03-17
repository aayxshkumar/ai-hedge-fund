"""Statistical arbitrage pairs trading.

Identifies cointegrated stock pairs (e.g. HDFCBANK-ICICIBANK) and trades the
spread when it deviates beyond a z-score threshold, expecting mean reversion.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig

# Pre-defined Indian market pairs with historically high correlation
DEFAULT_PAIRS = [
    ("HDFCBANK.NS", "ICICIBANK.NS"),
    ("TCS.NS", "INFY.NS"),
    ("RELIANCE.NS", "ONGC.NS"),
    ("SBIN.NS", "AXISBANK.NS"),
    ("MARUTI.NS", "TATAMOTORS.NS"),
    ("HINDUNILVR.NS", "ITC.NS"),
    ("BHARTIARTL.NS", "IDEA.NS"),
    ("LT.NS", "SIEMENS.NS"),
]


class PairsTradingStrategy:
    """Generates pair-relative signals based on spread z-score."""

    def __init__(self, config: StrategyConfig | None = None, pairs: list[tuple[str, str]] | None = None):
        self.cfg = config or StrategyConfig()
        self.pairs = pairs or DEFAULT_PAIRS

    def analyse_pair(self, prices_a: pd.Series, prices_b: pd.Series) -> dict:
        """Analyse a single pair of price series.

        Returns signal relative to leg A:
        - "buy" = buy A, sell B  (spread is compressed, expect expansion)
        - "sell" = sell A, buy B (spread is expanded, expect compression)
        """
        if prices_a is None or prices_b is None:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        min_len = min(len(prices_a), len(prices_b))
        if min_len < self.cfg.pairs_lookback_days:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        a = prices_a.iloc[-min_len:].values
        b = prices_b.iloc[-min_len:].values

        # Correlation check
        corr = np.corrcoef(a, b)[0, 1]
        if abs(corr) < self.cfg.pairs_min_correlation:
            return {
                "signal": "hold",
                "confidence": 0.0,
                "indicators": {"correlation": round(corr, 3), "reason": "low_correlation"},
            }

        # OLS hedge ratio: A = beta * B + alpha + epsilon
        beta = np.cov(a, b)[0, 1] / np.var(b)
        spread = a - beta * b

        # Z-score of the spread
        lookback = min(self.cfg.pairs_lookback_days, len(spread))
        recent_spread = spread[-lookback:]
        mean_spread = np.mean(recent_spread)
        std_spread = np.std(recent_spread)

        if std_spread == 0:
            return {"signal": "hold", "confidence": 0.0, "indicators": {"reason": "zero_std"}}

        zscore = (spread[-1] - mean_spread) / std_spread

        indicators = {
            "correlation": round(corr, 3),
            "hedge_ratio": round(beta, 4),
            "spread_zscore": round(zscore, 3),
            "spread_mean": round(mean_spread, 2),
            "spread_std": round(std_spread, 2),
        }

        if zscore > self.cfg.pairs_zscore_entry:
            return {"signal": "sell", "confidence": round(min(abs(zscore) / 3, 1.0), 3), "indicators": indicators}
        elif zscore < -self.cfg.pairs_zscore_entry:
            return {"signal": "buy", "confidence": round(min(abs(zscore) / 3, 1.0), 3), "indicators": indicators}
        elif abs(zscore) < self.cfg.pairs_zscore_exit:
            return {"signal": "close", "confidence": 0.8, "indicators": indicators}
        else:
            return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
