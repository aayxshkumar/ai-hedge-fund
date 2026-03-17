"""Futures trading strategies for Nifty and Bank Nifty."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FuturesSignal:
    action: str  # "long", "short", "close", "hold"
    confidence: float
    reason: str


class BaseFuturesStrategy(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def analyse(self, price_df: pd.DataFrame, has_position: bool, position_side: str | None = None) -> FuturesSignal:
        ...

    def _hold(self, reason: str = "") -> FuturesSignal:
        return FuturesSignal(action="hold", confidence=0.0, reason=reason)


class TrendFollowingFutures(BaseFuturesStrategy):
    """Supertrend + EMA crossover for trend following on futures."""
    name = "futures_trend"
    description = "Supertrend + EMA trend following on index futures"

    def analyse(self, price_df: pd.DataFrame, has_position: bool, position_side: str | None = None) -> FuturesSignal:
        if len(price_df) < 60:
            return self._hold("Insufficient data")

        close = price_df["close"]
        high = price_df["high"]
        low = price_df["low"]

        ema_fast = close.ewm(span=9).mean().iloc[-1]
        ema_slow = close.ewm(span=21).mean().iloc[-1]
        ema_trend = close.ewm(span=50).mean().iloc[-1]

        atr = (high - low).rolling(14).mean().iloc[-1]
        spot = close.iloc[-1]

        upper = (high + low) / 2 + 2 * (high - low).rolling(14).mean()
        lower = (high + low) / 2 - 2 * (high - low).rolling(14).mean()
        trend_up = spot > lower.iloc[-1]
        trend_down = spot < upper.iloc[-1]

        if has_position:
            if position_side == "long" and (ema_fast < ema_slow or spot < ema_trend):
                return FuturesSignal(action="close", confidence=0.6, reason="Trend reversal — close long")
            if position_side == "short" and (ema_fast > ema_slow or spot > ema_trend):
                return FuturesSignal(action="close", confidence=0.6, reason="Trend reversal — close short")
            return self._hold("Trend intact")

        if ema_fast > ema_slow and spot > ema_trend and trend_up:
            conf = min(0.85, 0.5 + (ema_fast - ema_slow) / atr * 0.1)
            return FuturesSignal(action="long", confidence=conf, reason="Bullish trend confirmed")

        if ema_fast < ema_slow and spot < ema_trend and trend_down:
            conf = min(0.85, 0.5 + (ema_slow - ema_fast) / atr * 0.1)
            return FuturesSignal(action="short", confidence=conf, reason="Bearish trend confirmed")

        return self._hold("No clear trend")


class MeanReversionFutures(BaseFuturesStrategy):
    """Bollinger Bands + RSI mean reversion on futures."""
    name = "futures_mean_revert"
    description = "Bollinger Bands + RSI mean reversion on index futures"

    def analyse(self, price_df: pd.DataFrame, has_position: bool, position_side: str | None = None) -> FuturesSignal:
        if len(price_df) < 30:
            return self._hold("Insufficient data")

        close = price_df["close"]
        spot = close.iloc[-1]

        sma20 = close.rolling(20).mean().iloc[-1]
        std20 = close.rolling(20).std().iloc[-1]
        upper_bb = sma20 + 2 * std20
        lower_bb = sma20 - 2 * std20

        deltas = close.diff().dropna()
        gains = deltas.clip(lower=0).rolling(14).mean().iloc[-1]
        losses = (-deltas.clip(upper=0)).rolling(14).mean().iloc[-1]
        rsi = 100 - (100 / (1 + gains / losses)) if losses > 0 else 100

        if has_position:
            if position_side == "long" and (spot > sma20 or rsi > 60):
                return FuturesSignal(action="close", confidence=0.6, reason="Reverted to mean")
            if position_side == "short" and (spot < sma20 or rsi < 40):
                return FuturesSignal(action="close", confidence=0.6, reason="Reverted to mean")
            return self._hold("Waiting for mean reversion")

        if spot < lower_bb and rsi < 30:
            conf = min(0.8, 0.4 + (lower_bb - spot) / std20 * 0.15 + (30 - rsi) / 100)
            return FuturesSignal(action="long", confidence=conf, reason=f"Oversold RSI {rsi:.0f}")

        if spot > upper_bb and rsi > 70:
            conf = min(0.8, 0.4 + (spot - upper_bb) / std20 * 0.15 + (rsi - 70) / 100)
            return FuturesSignal(action="short", confidence=conf, reason=f"Overbought RSI {rsi:.0f}")

        return self._hold("Price within bands")


class BreakoutMomentumFutures(BaseFuturesStrategy):
    """Donchian channel breakout + volume confirmation on futures."""
    name = "futures_breakout"
    description = "Donchian breakout + volume momentum on index futures"

    def analyse(self, price_df: pd.DataFrame, has_position: bool, position_side: str | None = None) -> FuturesSignal:
        if len(price_df) < 30:
            return self._hold("Insufficient data")

        close = price_df["close"]
        high = price_df["high"]
        low = price_df["low"]
        volume = price_df["volume"]

        spot = close.iloc[-1]
        high_20 = high.rolling(20).max().iloc[-2]
        low_20 = low.rolling(20).min().iloc[-2]

        vol_avg = volume.rolling(20).mean().iloc[-1]
        vol_now = volume.iloc[-1]
        vol_surge = vol_now > vol_avg * 1.5

        atr = (high - low).rolling(14).mean().iloc[-1]

        if has_position:
            if position_side == "long" and spot < close.iloc[-2] - 2 * atr:
                return FuturesSignal(action="close", confidence=0.7, reason="ATR stop hit")
            if position_side == "short" and spot > close.iloc[-2] + 2 * atr:
                return FuturesSignal(action="close", confidence=0.7, reason="ATR stop hit")
            return self._hold("In position, trailing")

        if spot > high_20 and vol_surge:
            conf = min(0.85, 0.5 + (spot - high_20) / atr * 0.1)
            return FuturesSignal(action="long", confidence=conf, reason="Upside breakout + volume")

        if spot < low_20 and vol_surge:
            conf = min(0.85, 0.5 + (low_20 - spot) / atr * 0.1)
            return FuturesSignal(action="short", confidence=conf, reason="Downside breakout + volume")

        return self._hold("No breakout")


class VWAPReversionFutures(BaseFuturesStrategy):
    """VWAP-based intraday-style reversion on futures."""
    name = "futures_vwap"
    description = "VWAP deviation reversion strategy for futures"

    def analyse(self, price_df: pd.DataFrame, has_position: bool, position_side: str | None = None) -> FuturesSignal:
        if len(price_df) < 20:
            return self._hold("Insufficient data")

        close = price_df["close"]
        volume = price_df["volume"]

        cumvol = volume.rolling(20).sum()
        vwap = (close * volume).rolling(20).sum() / cumvol
        spot = close.iloc[-1]
        vwap_val = vwap.iloc[-1]

        if vwap_val <= 0:
            return self._hold("VWAP calculation error")

        deviation = (spot - vwap_val) / vwap_val

        if has_position:
            if position_side == "long" and deviation > -0.002:
                return FuturesSignal(action="close", confidence=0.6, reason="Reverted to VWAP")
            if position_side == "short" and deviation < 0.002:
                return FuturesSignal(action="close", confidence=0.6, reason="Reverted to VWAP")
            return self._hold("Waiting for VWAP convergence")

        if deviation < -0.015:
            conf = min(0.75, 0.4 + abs(deviation) * 10)
            return FuturesSignal(action="long", confidence=conf, reason=f"Below VWAP by {deviation:.2%}")

        if deviation > 0.015:
            conf = min(0.75, 0.4 + abs(deviation) * 10)
            return FuturesSignal(action="short", confidence=conf, reason=f"Above VWAP by {deviation:.2%}")

        return self._hold("Near VWAP")


FUTURES_STRATEGY_REGISTRY: dict[str, tuple[type, str]] = {
    "futures_trend": (TrendFollowingFutures, "Supertrend + EMA trend following"),
    "futures_mean_revert": (MeanReversionFutures, "Bollinger + RSI mean reversion"),
    "futures_breakout": (BreakoutMomentumFutures, "Donchian breakout + volume momentum"),
    "futures_vwap": (VWAPReversionFutures, "VWAP deviation reversion"),
}
