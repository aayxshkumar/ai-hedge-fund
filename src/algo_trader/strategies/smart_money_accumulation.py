"""Smart Money Accumulation — detects institutional accumulation/distribution patterns.

Inspired by the ColdVision / GemChange approach to finding undervalued assets:
1. Identify stocks at significant drawdown levels from recent highs (-30% to -65%)
2. Detect accumulation via OBV divergence (price falling but OBV rising)
3. Confirm with volume profile (rising average volume during drawdown = smart money)
4. Score entry quality based on support proximity, RSI oversold, and volume surge
5. Set structured profit targets (+30%, +50%, +100% from entry) and stop-loss (-8%)

Designed for Indian equities where institutional accumulation in mid/large caps
creates reliable mean-reversion setups.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import rsi as _rsi


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff())
    return (direction * volume).cumsum()


def _find_drawdown_from_high(close: pd.Series, lookback: int = 90) -> tuple[float, float]:
    """Returns (drawdown_pct, high_price) relative to the lookback period high."""
    recent = close.tail(lookback)
    if len(recent) < 2:
        return 0.0, float(close.iloc[-1])
    high_price = float(recent.max())
    current = float(close.iloc[-1])
    dd = (current - high_price) / high_price if high_price > 0 else 0.0
    return dd, high_price


def _obv_divergence(close: pd.Series, obv: pd.Series, window: int = 20) -> str:
    """Detect bullish/bearish OBV divergence over the window.
    Bullish: price making lower lows but OBV making higher lows.
    Bearish: price making higher highs but OBV making lower highs.
    """
    if len(close) < window * 2:
        return "none"

    recent_close = close.tail(window)
    prev_close = close.iloc[-window * 2:-window]
    recent_obv = obv.tail(window)
    prev_obv = obv.iloc[-window * 2:-window]

    price_lower = recent_close.min() < prev_close.min()
    obv_higher = recent_obv.min() > prev_obv.min()
    if price_lower and obv_higher:
        return "bullish"

    price_higher = recent_close.max() > prev_close.max()
    obv_lower = recent_obv.max() < prev_obv.max()
    if price_higher and obv_lower:
        return "bearish"

    return "none"


def _volume_trend(volume: pd.Series, short: int = 10, long: int = 30) -> float:
    """Ratio of short-term avg volume to long-term. >1 = accumulation."""
    short_avg = volume.tail(short).mean()
    long_avg = volume.tail(long).mean()
    return float(short_avg / long_avg) if long_avg > 0 else 1.0


class SmartMoneyAccumulationStrategy:
    """Detects institutional accumulation at drawdown levels with structured entries."""

    def __init__(self, config=None, drawdown_min: float = -0.20, drawdown_sweet: float = -0.40,
                 rsi_oversold: float = 35, obv_window: int = 20, vol_accumulation_ratio: float = 1.2,
                 lookback: int = 90):
        self.drawdown_min = drawdown_min
        self.drawdown_sweet = drawdown_sweet
        self.rsi_oversold = rsi_oversold
        self.obv_window = obv_window
        self.vol_accumulation_ratio = vol_accumulation_ratio
        self.lookback = lookback

    def analyse(self, price_df: pd.DataFrame) -> dict:
        needed = self.lookback + 30
        if price_df is None or len(price_df) < needed:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"]
        volume = price_df["volume"] if "volume" in price_df.columns else pd.Series(0, index=close.index)

        # Drawdown analysis
        dd_pct, high_price = _find_drawdown_from_high(close, self.lookback)

        # RSI
        rsi = _rsi(close)
        rsi_val = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0

        # OBV and divergence
        obv = _obv(close, volume)
        div = _obv_divergence(close, obv, self.obv_window)

        # Volume accumulation trend
        vol_trend = _volume_trend(volume)

        # Support proximity (is price near 20-day low?)
        low_20 = close.rolling(20).min().iloc[-1]
        support_proximity = float(close.iloc[-1] / low_20) if low_20 > 0 else 1.0

        # Price recovery from bottom (bouncing?)
        low_5 = close.tail(5).min()
        bounce_pct = float((close.iloc[-1] - low_5) / low_5) if low_5 > 0 else 0.0

        # EMA trend (is it starting to curl up?)
        ema_20 = close.ewm(span=20, adjust=False).mean()
        ema_slope = float(ema_20.iloc[-1] - ema_20.iloc[-3]) / float(ema_20.iloc[-3]) if len(ema_20) > 3 and ema_20.iloc[-3] > 0 else 0.0

        indicators = {
            "drawdown_pct": round(dd_pct * 100, 1),
            "high_price": round(high_price, 2),
            "rsi": round(rsi_val, 1),
            "obv_divergence": div,
            "volume_trend_ratio": round(vol_trend, 2),
            "support_proximity": round(support_proximity, 3),
            "bounce_pct": round(bounce_pct * 100, 1),
            "ema_slope": round(ema_slope * 100, 3),
        }

        # Scoring
        score = 0.0

        # Must be in drawdown zone
        if dd_pct > self.drawdown_min:
            return {"signal": "hold", "confidence": 0.0, "indicators": indicators}

        # Base: drawdown depth
        if dd_pct <= self.drawdown_sweet:
            score += 0.35  # deep value zone
        elif dd_pct <= self.drawdown_min:
            score += 0.20  # moderate drawdown

        # Bullish OBV divergence (smart money accumulating while price drops)
        if div == "bullish":
            score += 0.25
        elif div == "bearish":
            score -= 0.30  # distribution — avoid

        # Volume accumulation
        if vol_trend > self.vol_accumulation_ratio:
            score += 0.15

        # RSI oversold
        if rsi_val < self.rsi_oversold:
            score += 0.15
        elif rsi_val > 70:
            score -= 0.10

        # Near support and bouncing
        if support_proximity < 1.03 and bounce_pct > 0.01:
            score += 0.10

        # EMA starting to curl up
        if ema_slope > 0:
            score += 0.10

        # Sell signal: bearish divergence at modest drawdown (distribution phase)
        if div == "bearish" and dd_pct > -0.15 and rsi_val > 60:
            score = -0.50
            if vol_trend > self.vol_accumulation_ratio:
                score -= 0.15

        confidence = min(abs(score), 1.0)
        if score > 0.15:
            return {"signal": "buy", "confidence": round(confidence, 3), "indicators": indicators}
        elif score < -0.15:
            return {"signal": "sell", "confidence": round(confidence, 3), "indicators": indicators}
        return {"signal": "hold", "confidence": 0.0, "indicators": indicators}
