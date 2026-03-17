"""Daily stock screener — filters the Indian stock universe for tradable candidates.

Runs pre-market (or on demand) to select the best stocks for auto-trading based
on volume, volatility, trend strength (ADX), liquidity, and optionally sentiment.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class ScreenerResult:
    ticker: str
    score: float
    avg_volume_20d: float
    relative_volume: float
    volatility_20d: float
    adx: float
    liquidity_ratio: float
    sentiment_score: float
    trend: str
    last_close: float


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """Compute ADX (Average Directional Index)."""
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.rolling(period).mean()

    val = adx.iloc[-1]
    return float(val) if not np.isnan(val) else 0.0


def _quick_sentiment(ticker: str) -> float:
    """Fast keyword-based sentiment from yfinance news (no LLM cost)."""
    try:
        import yfinance as yf
        news = yf.Ticker(ticker).news or []
    except Exception:
        return 0.0

    if not news:
        return 0.0

    bullish = {"surge", "jump", "gain", "rally", "beat", "upgrade", "buy", "profit", "growth", "bull", "soar", "record", "outperform", "breakout", "strong"}
    bearish = {"drop", "fall", "loss", "crash", "decline", "downgrade", "sell", "miss", "warning", "bear", "plunge", "weak", "risk", "fraud", "scam"}

    b = s = 0
    for article in news[:10]:
        title = (article.get("title") or "").lower()
        b += sum(1 for kw in bullish if kw in title)
        s += sum(1 for kw in bearish if kw in title)

    total = b + s
    return (b - s) / total if total > 0 else 0.0


def _screen_single(ticker: str) -> ScreenerResult | None:
    """Fetch data and compute screening metrics for a single ticker."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period="60d")
        if df is None or len(df) < 25:
            return None

        df.columns = [str(c).strip().capitalize() for c in df.columns]
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        volume = df["Volume"]

        avg_vol_20 = float(volume.iloc[-21:-1].mean())
        if avg_vol_20 < 100_000:
            return None

        last_vol = float(volume.iloc[-1])
        rel_vol = last_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

        returns = close.pct_change().dropna()
        vol_20d = float(returns.iloc[-20:].std() * np.sqrt(252))
        if vol_20d < 0.10 or vol_20d > 0.90:
            return None

        adx = _compute_adx(high, low, close)
        if adx < 15:
            return None

        daily_range = (high - low) / close
        liquidity_ratio = float(daily_range.iloc[-20:].mean())
        if liquidity_ratio > 0.06:
            return None

        last_close = float(close.iloc[-1])
        ema20 = float(close.ewm(span=20).mean().iloc[-1])
        trend = "up" if last_close > ema20 else "down"

        sentiment = _quick_sentiment(ticker)

        score = (
            min(rel_vol, 3.0) * 20
            + min(adx, 60) * 1.0
            + min(vol_20d * 100, 50) * 0.5
            + abs(sentiment) * 15
            + (10 if trend == "up" else 0)
        )

        return ScreenerResult(
            ticker=ticker,
            score=round(score, 2),
            avg_volume_20d=round(avg_vol_20),
            relative_volume=round(rel_vol, 2),
            volatility_20d=round(vol_20d, 4),
            adx=round(adx, 1),
            liquidity_ratio=round(liquidity_ratio, 4),
            sentiment_score=round(sentiment, 3),
            trend=trend,
            last_close=round(last_close, 2),
        )

    except Exception as e:
        log.debug("Screener failed for %s: %s", ticker, e)
        return None


def screen_stocks(
    tickers: list[str],
    top_n: int = 15,
    max_workers: int = 10,
) -> list[ScreenerResult]:
    """Screen a list of tickers in parallel and return the top N candidates."""
    results: list[ScreenerResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_screen_single, t): t for t in tickers}
        for future in as_completed(futures, timeout=120):
            try:
                r = future.result(timeout=30)
                if r is not None:
                    results.append(r)
            except Exception:
                pass

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]
