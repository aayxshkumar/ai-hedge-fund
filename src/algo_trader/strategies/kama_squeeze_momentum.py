"""KAMA Squeeze Momentum — Enhanced BB/KC squeeze with Kaufman Adaptive Moving Average.

Based on the dynamic momentum squeeze approach popular in 2026 crypto/equity trading:
1. Detect squeeze: Bollinger Bands contract inside Keltner Channels
2. Use KAMA (Kaufman Adaptive MA) crossed with EMA for adaptive trend detection
3. Measure momentum via linear regression of price deviation
4. Require volume confirmation above moving average threshold
5. Align with higher-timeframe trend (50-period SMA)

References:
  - PyQuantLab "Dynamic Momentum Squeeze Strategy" (Feb 2026)
  - LazyBear Squeeze Momentum indicator adapted for Indian equities
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import atr as _atr


def _kama(close: pd.Series, er_period: int = 10, fast_sc: int = 2, slow_sc: int = 30) -> pd.Series:
    """Kaufman Adaptive Moving Average — adjusts speed based on market noise."""
    direction = (close - close.shift(er_period)).abs()
    volatility = close.diff().abs().rolling(er_period).sum()
    er = direction / volatility.replace(0, np.nan)
    er = er.fillna(0)

    fast_alpha = 2.0 / (fast_sc + 1)
    slow_alpha = 2.0 / (slow_sc + 1)
    sc = (er * (fast_alpha - slow_alpha) + slow_alpha) ** 2

    c = close.values
    s = sc.values
    k = np.full(len(c), np.nan)
    first_valid = close.first_valid_index()
    if first_valid is None:
        return pd.Series(k, index=close.index)
    start_idx = close.index.get_loc(first_valid) + er_period
    if start_idx >= len(c):
        return pd.Series(k, index=close.index)
    k[start_idx] = c[start_idx]
    for i in range(start_idx + 1, len(c)):
        prev = k[i - 1]
        k[i] = c[i] if np.isnan(prev) else prev + s[i] * (c[i] - prev)
    return pd.Series(k, index=close.index)


def _linreg_slope(series: pd.Series, period: int) -> pd.Series:
    """Rolling linear regression slope — measures momentum direction and strength."""
    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    def _slope(window):
        if len(window) < period or np.isnan(window).any():
            return 0.0
        y_mean = window.mean()
        return ((x * (window - y_mean)).sum()) / x_var if x_var > 0 else 0.0

    return series.rolling(period).apply(_slope, raw=True)


class KAMASqueezeStrategy:
    """Enhanced squeeze momentum with KAMA adaptive trend + linear regression momentum."""

    def __init__(self, config=None, bb_period: int = 20, bb_mult: float = 2.0,
                 kc_mult: float = 1.5, atr_period: int = 10, kama_er: int = 10,
                 vol_mult: float = 1.3, trend_sma: int = 50, linreg_period: int = 20):
        self.bb_period = bb_period
        self.bb_mult = bb_mult
        self.kc_mult = kc_mult
        self.atr_period = atr_period
        self.kama_er = kama_er
        self.vol_mult = vol_mult
        self.trend_sma = trend_sma
        self.linreg_period = linreg_period

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = max(self.bb_period, self.trend_sma, self.linreg_period) + 20
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        high = price_df["high"]
        low = price_df["low"]
        close = price_df["close"]
        volume = price_df["volume"] if "volume" in price_df.columns else pd.Series(0, index=close.index)

        # Bollinger Bands
        sma = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        bb_upper = sma + self.bb_mult * std
        bb_lower = sma - self.bb_mult * std

        # Keltner Channels
        ema = close.ewm(span=self.bb_period, adjust=False).mean()
        atr = _atr(high, low, close, self.atr_period)
        kc_upper = ema + self.kc_mult * atr
        kc_lower = ema - self.kc_mult * atr

        # Squeeze detection
        squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)
        squeeze_release = squeeze.iloc[-2] and not squeeze.iloc[-1]
        squeeze_firing = not squeeze.iloc[-2] and not squeeze.iloc[-1] and squeeze.iloc[-3] if len(squeeze) > 2 else False

        # KAMA vs EMA crossover
        kama_line = _kama(close, er_period=self.kama_er)
        ema_fast = close.ewm(span=12, adjust=False).mean()
        kama_above_ema = kama_line.iloc[-1] > ema_fast.iloc[-1] if not np.isnan(kama_line.iloc[-1]) else False
        kama_crossed_up = (kama_line.iloc[-1] > ema_fast.iloc[-1]) and (kama_line.iloc[-2] <= ema_fast.iloc[-2]) if len(kama_line) > 1 and not np.isnan(kama_line.iloc[-2]) else False
        kama_crossed_down = (kama_line.iloc[-1] < ema_fast.iloc[-1]) and (kama_line.iloc[-2] >= ema_fast.iloc[-2]) if len(kama_line) > 1 and not np.isnan(kama_line.iloc[-2]) else False

        # Linear regression momentum
        mom_slope = _linreg_slope(close, self.linreg_period)
        slope_val = float(mom_slope.iloc[-1]) if not np.isnan(mom_slope.iloc[-1]) else 0.0
        slope_rising = slope_val > float(mom_slope.iloc[-2]) if len(mom_slope) > 1 and not np.isnan(mom_slope.iloc[-2]) else False

        # Volume confirmation
        avg_vol = volume.rolling(self.bb_period).mean()
        vol_ratio = float(volume.iloc[-1] / avg_vol.iloc[-1]) if avg_vol.iloc[-1] > 0 else 0.0
        vol_confirm = vol_ratio > self.vol_mult

        # Higher-timeframe trend
        trend_sma_val = close.rolling(self.trend_sma).mean()
        trend_bullish = close.iloc[-1] > trend_sma_val.iloc[-1] if not np.isnan(trend_sma_val.iloc[-1]) else True

        indicators = {
            "in_squeeze": bool(squeeze.iloc[-1]),
            "squeeze_release": squeeze_release,
            "squeeze_firing": squeeze_firing,
            "kama_above_ema": kama_above_ema,
            "kama_cross_up": kama_crossed_up,
            "kama_cross_down": kama_crossed_down,
            "momentum_slope": round(slope_val, 4),
            "slope_rising": slope_rising,
            "volume_ratio": round(vol_ratio, 2),
            "trend_bullish": trend_bullish,
        }

        # Scoring logic
        score = 0.0

        # Primary: squeeze release + aligned momentum
        if squeeze_release or squeeze_firing:
            if slope_val > 0 and slope_rising:
                score = 0.65
                if vol_confirm:
                    score += 0.15
                if trend_bullish:
                    score += 0.10
                if kama_above_ema:
                    score += 0.05
            elif slope_val < 0 and not slope_rising:
                score = -0.65
                if vol_confirm:
                    score -= 0.15
                if not trend_bullish:
                    score -= 0.10
                if not kama_above_ema:
                    score -= 0.05

        # Secondary: KAMA crossover without squeeze (trend continuation)
        elif kama_crossed_up and slope_val > 0 and vol_confirm and trend_bullish:
            score = 0.45
        elif kama_crossed_down and slope_val < 0 and vol_confirm and not trend_bullish:
            score = -0.45

        # Mild: inside squeeze but momentum building
        elif squeeze.iloc[-1] and abs(slope_val) > 0 and slope_rising and vol_confirm:
            score = 0.2 if slope_val > 0 else -0.2

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
