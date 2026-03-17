"""Candlestick pattern detection — pure pandas, no external deps.

Detects 12 classic candle formations on OHLC data and returns a
directional bias with strength score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class CandleResult:
    patterns: list[str]
    bias: str          # "bullish" | "bearish" | "neutral"
    strength: float    # 0.0 – 1.0
    details: dict


def _body(o: float, c: float) -> float:
    return abs(c - o)


def _upper_shadow(h: float, o: float, c: float) -> float:
    return h - max(o, c)


def _lower_shadow(o: float, c: float, l: float) -> float:
    return min(o, c) - l


def _is_bullish(o: float, c: float) -> bool:
    return c > o


def _is_bearish(o: float, c: float) -> bool:
    return o > c


def detect_patterns(df: pd.DataFrame, lookback: int = 5) -> CandleResult:
    """Scan the last ``lookback`` bars for candle patterns.

    Expects columns: open, high, low, close (case-insensitive).
    """
    cols = {c.lower(): c for c in df.columns}
    o_col, h_col, l_col, c_col = cols["open"], cols["high"], cols["low"], cols["close"]

    if len(df) < max(lookback, 3):
        return CandleResult([], "neutral", 0.0, {})

    tail = df.iloc[-lookback:].reset_index(drop=True)
    O = tail[o_col].values.astype(float)
    H = tail[h_col].values.astype(float)
    L = tail[l_col].values.astype(float)
    C = tail[c_col].values.astype(float)

    avg_body = np.mean([_body(O[i], C[i]) for i in range(len(O))])
    if avg_body == 0:
        avg_body = 1e-9

    found: list[str] = []
    bullish_pts = 0.0
    bearish_pts = 0.0

    last = len(O) - 1
    prev = last - 1
    prev2 = last - 2

    body_last = _body(O[last], C[last])
    upper_last = _upper_shadow(H[last], O[last], C[last])
    lower_last = _lower_shadow(O[last], C[last], L[last])

    # ── Hammer (bullish) ─────────────────────────────────────────────
    if (_is_bullish(O[last], C[last])
            and lower_last >= 2 * body_last
            and upper_last <= body_last * 0.3
            and body_last > 0):
        found.append("Hammer")
        bullish_pts += 1.0

    # ── Shooting Star (bearish) ──────────────────────────────────────
    if (_is_bearish(O[last], C[last])
            and upper_last >= 2 * body_last
            and lower_last <= body_last * 0.3
            and body_last > 0):
        found.append("Shooting Star")
        bearish_pts += 1.0

    # ── Dragonfly Doji (bullish) ─────────────────────────────────────
    if (body_last <= avg_body * 0.1
            and lower_last >= avg_body * 1.5
            and upper_last <= avg_body * 0.1):
        found.append("Dragonfly Doji")
        bullish_pts += 0.8

    # ── Gravestone Doji (bearish) ────────────────────────────────────
    if (body_last <= avg_body * 0.1
            and upper_last >= avg_body * 1.5
            and lower_last <= avg_body * 0.1):
        found.append("Gravestone Doji")
        bearish_pts += 0.8

    # ── Bullish Engulfing ────────────────────────────────────────────
    if prev >= 0:
        if (_is_bearish(O[prev], C[prev])
                and _is_bullish(O[last], C[last])
                and O[last] <= C[prev]
                and C[last] >= O[prev]):
            found.append("Bullish Engulfing")
            bullish_pts += 1.2

    # ── Bearish Engulfing ────────────────────────────────────────────
    if prev >= 0:
        if (_is_bullish(O[prev], C[prev])
                and _is_bearish(O[last], C[last])
                and O[last] >= C[prev]
                and C[last] <= O[prev]):
            found.append("Bearish Engulfing")
            bearish_pts += 1.2

    # ── Piercing Line (bullish) ──────────────────────────────────────
    if prev >= 0:
        mid_prev = (O[prev] + C[prev]) / 2
        if (_is_bearish(O[prev], C[prev])
                and _is_bullish(O[last], C[last])
                and O[last] < C[prev]
                and C[last] > mid_prev
                and C[last] < O[prev]):
            found.append("Piercing Line")
            bullish_pts += 0.9

    # ── Dark Cloud Cover (bearish) ───────────────────────────────────
    if prev >= 0:
        mid_prev = (O[prev] + C[prev]) / 2
        if (_is_bullish(O[prev], C[prev])
                and _is_bearish(O[last], C[last])
                and O[last] > C[prev]
                and C[last] < mid_prev
                and C[last] > O[prev]):
            found.append("Dark Cloud Cover")
            bearish_pts += 0.9

    # ── Morning Star (bullish, 3-bar) ────────────────────────────────
    if prev2 >= 0:
        body_mid = _body(O[prev], C[prev])
        if (_is_bearish(O[prev2], C[prev2])
                and body_mid <= avg_body * 0.4
                and _is_bullish(O[last], C[last])
                and C[last] > (O[prev2] + C[prev2]) / 2):
            found.append("Morning Star")
            bullish_pts += 1.3

    # ── Evening Star (bearish, 3-bar) ────────────────────────────────
    if prev2 >= 0:
        body_mid = _body(O[prev], C[prev])
        if (_is_bullish(O[prev2], C[prev2])
                and body_mid <= avg_body * 0.4
                and _is_bearish(O[last], C[last])
                and C[last] < (O[prev2] + C[prev2]) / 2):
            found.append("Evening Star")
            bearish_pts += 1.3

    # ── Three White Soldiers (bullish, 3-bar) ────────────────────────
    if prev2 >= 0:
        if all(_is_bullish(O[i], C[i]) for i in [prev2, prev, last]):
            bodies = [_body(O[i], C[i]) for i in [prev2, prev, last]]
            if all(b >= avg_body * 0.6 for b in bodies):
                if C[prev] > C[prev2] and C[last] > C[prev]:
                    found.append("Three White Soldiers")
                    bullish_pts += 1.5

    # ── Three Black Crows (bearish, 3-bar) ───────────────────────────
    if prev2 >= 0:
        if all(_is_bearish(O[i], C[i]) for i in [prev2, prev, last]):
            bodies = [_body(O[i], C[i]) for i in [prev2, prev, last]]
            if all(b >= avg_body * 0.6 for b in bodies):
                if C[prev] < C[prev2] and C[last] < C[prev]:
                    found.append("Three Black Crows")
                    bearish_pts += 1.5

    # ── Aggregate ────────────────────────────────────────────────────
    total = bullish_pts + bearish_pts
    if total == 0:
        bias = "neutral"
        strength = 0.0
    elif bullish_pts > bearish_pts:
        bias = "bullish"
        strength = min(bullish_pts / max(total, 1), 1.0)
    else:
        bias = "bearish"
        strength = min(bearish_pts / max(total, 1), 1.0)

    return CandleResult(
        patterns=found,
        bias=bias,
        strength=round(strength, 3),
        details={"bullish_score": round(bullish_pts, 2), "bearish_score": round(bearish_pts, 2)},
    )
