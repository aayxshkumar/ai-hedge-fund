"""Momentum / trend-following strategy.

Uses EMA crossover (MACD-style) + RSI to identify stocks with strong directional
trends.  Signals are generated at the ticker level with a confidence score [0, 1].
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


class MomentumStrategy:
    """Generate momentum signals for a list of tickers using price history."""

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()

    def analyse(self, price_df: pd.DataFrame) -> dict:
        """Analyse a single ticker's OHLCV DataFrame.

        Expected columns: close, volume (at minimum).
        Returns: {"signal": "buy"|"sell"|"hold", "confidence": float, "indicators": dict}
        """
        if price_df is None or len(price_df) < self.cfg.momentum_slow_ema + 10:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]

        fast = ema(close, self.cfg.momentum_fast_ema)
        slow = ema(close, self.cfg.momentum_slow_ema)
        macd_line = fast - slow
        signal_line = ema(macd_line, self.cfg.momentum_signal_ema)
        macd_hist = macd_line - signal_line

        rsi_values = rsi(close, self.cfg.momentum_rsi_period)

        curr_macd = macd_hist.iloc[-1]
        prev_macd = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0
        curr_rsi = rsi_values.iloc[-1]

        macd_crossover_bull = prev_macd <= 0 < curr_macd
        macd_crossover_bear = prev_macd >= 0 > curr_macd
        macd_trend_strength = abs(curr_macd) / close.iloc[-1] * 100

        indicators = {
            "ema_fast": round(fast.iloc[-1], 2),
            "ema_slow": round(slow.iloc[-1], 2),
            "macd": round(curr_macd, 4),
            "macd_signal": round(signal_line.iloc[-1], 4),
            "rsi": round(curr_rsi, 2),
        }

        # Scoring: combine MACD direction + RSI zones
        score = 0.0
        if macd_crossover_bull:
            score += 0.4
        elif curr_macd > 0:
            score += 0.2
        if macd_crossover_bear:
            score -= 0.4
        elif curr_macd < 0:
            score -= 0.2

        if curr_rsi < self.cfg.momentum_rsi_oversold:
            score += 0.3  # oversold = potential bounce
        elif curr_rsi > self.cfg.momentum_rsi_overbought:
            score -= 0.3  # overbought = potential pullback

        # Trend strength adds conviction
        score += min(macd_trend_strength, 0.3) * np.sign(score) if score != 0 else 0

        confidence = min(abs(score), 1.0)

        if score > 0.2:
            signal = "buy"
        elif score < -0.2:
            signal = "sell"
        else:
            signal = "hold"

        return {"signal": signal, "confidence": round(confidence, 3), "indicators": indicators}
