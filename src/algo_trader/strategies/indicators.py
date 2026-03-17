"""Shared technical indicators for strategy modules.

Extracted from duplicated implementations across strategy files.
All functions use vectorized pandas/numpy operations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """Average True Range (simple moving average of TR)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (RMA) — exponential-style with alpha = 1/period."""
    result = series.copy().astype(float)
    result.iloc[:period] = np.nan
    if len(series) > period:
        result.iloc[period] = series.iloc[1: period + 1].sum()
    for i in range(period + 1, len(series)):
        result.iloc[i] = result.iloc[i - 1] - result.iloc[i - 1] / period + series.iloc[i]
    return result


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Average Directional Index. Returns (adx, plus_di, minus_di)."""
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    mask = plus_dm < minus_dm
    plus_dm = plus_dm.where(~mask, 0)
    minus_dm = minus_dm.where(mask, 0)

    atr_vals = atr(high, low, close, period).replace(0, np.nan)
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr_vals)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr_vals)
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx_vals = dx.rolling(period).mean()
    return adx_vals, plus_di, minus_di


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume (vectorized)."""
    direction = np.sign(close.diff())
    return (direction * volume).cumsum()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(period).mean()


def bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands. Returns (upper, middle, lower)."""
    middle = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Volume-Weighted Average Price (cumulative)."""
    typical_price = (high + low + close) / 3
    return (typical_price * volume).cumsum() / volume.cumsum()
