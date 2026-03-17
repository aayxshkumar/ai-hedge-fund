"""Sentiment-momentum strategy — combines news sentiment with RSI momentum.

Uses yfinance news data to derive a simple sentiment score and blends it
with RSI-based momentum for directional signals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.algo_trader.config import StrategyConfig
from src.algo_trader.strategies.indicators import rsi as _rsi


def _fetch_news_sentiment(ticker: str) -> float:
    """Fetch news for ticker and return a sentiment score in [-1, 1].

    Positive titles → bullish, negative → bearish.  Simple keyword approach
    avoids LLM cost during fast screening.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        news = t.news or []
    except Exception:
        return 0.0

    if not news:
        return 0.0

    bullish_kw = {"surge", "jump", "gain", "rally", "beat", "upgrade", "buy", "profit", "growth", "bull", "soar", "record", "outperform"}
    bearish_kw = {"drop", "fall", "loss", "crash", "decline", "downgrade", "sell", "miss", "warning", "bear", "plunge", "weak", "risk"}

    bull = bear = 0
    for article in news[:15]:
        title = (article.get("title") or "").lower()
        bull += sum(1 for kw in bullish_kw if kw in title)
        bear += sum(1 for kw in bearish_kw if kw in title)

    total = bull + bear
    if total == 0:
        return 0.0
    return (bull - bear) / total


class SentimentMomentumStrategy:

    def __init__(self, config: StrategyConfig | None = None):
        self.cfg = config or StrategyConfig()

    def analyse(self, price_df: pd.DataFrame, ticker: str = "") -> dict:
        if price_df is None or len(price_df) < 20:
            return {"signal": "hold", "confidence": 0.0, "indicators": {}}

        close = price_df["close"] if "close" in price_df.columns else price_df["Close"]
        rsi_vals = _rsi(close, 14)
        curr_rsi = float(rsi_vals.iloc[-1])

        sentiment = _fetch_news_sentiment(ticker) if ticker else 0.0

        rsi_score = 0.0
        if curr_rsi < 35:
            rsi_score = 0.4
        elif curr_rsi > 65:
            rsi_score = -0.4
        else:
            rsi_score = (50 - curr_rsi) / 100

        score = 0.6 * sentiment + 0.4 * rsi_score
        confidence = min(abs(score), 1.0)

        if score > 0.15:
            signal = "buy"
        elif score < -0.15:
            signal = "sell"
        else:
            signal = "hold"

        return {
            "signal": signal,
            "confidence": round(confidence, 3),
            "indicators": {
                "sentiment_score": round(sentiment, 3),
                "rsi": round(curr_rsi, 2),
                "combined_score": round(score, 3),
            },
        }
