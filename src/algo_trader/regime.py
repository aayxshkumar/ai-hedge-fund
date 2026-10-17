"""Market regime detection shared by the decision engine.

The engine fuses trend-following strategies, mean-reversion strategies, candle
patterns and slow fundamental/consensus signals with one fixed weight table.
That is wrong in a knowable way: trend-following edges evaporate in a range and
mean-reversion gets run over in a trend, while in a high-volatility shock the
fast technical signals are mostly noise and the slower fundamental view should
carry more. This module classifies the regime from the price history already
in hand and returns per-source multipliers for the fusion weights.

Regime labels
    trend_up / trend_down   ADX >= TREND_ADX with the directional index agreeing
    range                   ADX < RANGE_ADX
    high_vol                recent realised vol in the top VOL_SHOCK_PCT of its
                            own history (checked first - it overrides trend)
    transition              anything in between (multipliers stay at 1.0)
    unknown                 not enough bars (multipliers stay at 1.0)

Multipliers are deliberately moderate (0.7-1.3) so the regime tilts the mix
rather than switching families off; the adaptive-performance layer handles
whether a given strategy has actually been earning its weight.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from src.algo_trader.strategies.indicators import adx as _adx

TREND_ADX = 25.0
RANGE_ADX = 20.0
VOL_SHOCK_PCT = 0.85
MIN_BARS = 40

TREND_FAMILY = {"momentum", "supertrend", "adx_trend", "kama_squeeze",
                "volume_breakout", "squeeze_breakout", "smart_money"}
MEANREV_FAMILY = {"mean_reversion", "vwap"}
PATTERN_FAMILY = {"candle_patterns"}
FUNDAMENTAL_FAMILY = {"meta_analyst", "hedge_fund"}

# family -> multiplier, per regime
REGIME_TILTS: dict[str, dict[str, float]] = {
    "trend_up":   {"trend": 1.25, "meanrev": 0.70, "pattern": 1.00, "fundamental": 1.00},
    "trend_down": {"trend": 1.25, "meanrev": 0.70, "pattern": 1.00, "fundamental": 1.00},
    "range":      {"trend": 0.70, "meanrev": 1.30, "pattern": 1.10, "fundamental": 1.00},
    "high_vol":   {"trend": 0.85, "meanrev": 0.80, "pattern": 0.80, "fundamental": 1.15},
    "transition": {"trend": 1.00, "meanrev": 1.00, "pattern": 1.00, "fundamental": 1.00},
    "unknown":    {"trend": 1.00, "meanrev": 1.00, "pattern": 1.00, "fundamental": 1.00},
}


@dataclass
class Regime:
    label: str = "unknown"
    adx: float | None = None
    trend_dir: int = 0            # +1 up, -1 down, 0 none
    daily_vol: float | None = None  # realised daily return std (fraction)
    vol_percentile: float | None = None
    bars: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _family(source: str) -> str:
    if source in TREND_FAMILY:
        return "trend"
    if source in MEANREV_FAMILY:
        return "meanrev"
    if source in PATTERN_FAMILY:
        return "pattern"
    if source in FUNDAMENTAL_FAMILY:
        return "fundamental"
    return "other"


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    return out


def realised_daily_vol(df: pd.DataFrame, window: int = 20) -> float | None:
    """Std of daily returns over ``window`` bars, as a fraction (0.02 = 2 %)."""
    d = _normalise(df)
    if "close" not in d or len(d) < window + 1:
        return None
    rets = d["close"].pct_change().dropna()
    if len(rets) < window:
        return None
    v = float(rets.iloc[-window:].std())
    return v if np.isfinite(v) and v > 0 else None


def detect_regime(df: pd.DataFrame, adx_period: int = 14, vol_window: int = 20,
                  vol_history: int = 120) -> Regime:
    """Classify the regime from OHLC history (needs high/low/close; close alone
    still gives the volatility regime)."""
    if df is None or df.empty:
        return Regime()
    d = _normalise(df)
    n = len(d)
    if "close" not in d or n < MIN_BARS:
        return Regime(bars=n)

    rets = d["close"].pct_change().dropna()
    roll = rets.rolling(vol_window).std().dropna()
    daily_vol = float(roll.iloc[-1]) if len(roll) else None
    vol_pct = None
    if len(roll) >= 2:
        hist = roll.iloc[-vol_history:]
        vol_pct = float((hist <= hist.iloc[-1]).mean())

    adx_val, trend_dir = None, 0
    if {"high", "low"} <= set(d.columns) and n >= adx_period * 3:
        try:
            a, plus, minus = _adx(d["high"], d["low"], d["close"], adx_period)
            if len(a.dropna()):
                adx_val = float(a.dropna().iloc[-1])
                p, m = float(plus.dropna().iloc[-1]), float(minus.dropna().iloc[-1])
                trend_dir = 1 if p > m else (-1 if m > p else 0)
        except Exception:
            adx_val, trend_dir = None, 0

    if vol_pct is not None and vol_pct >= VOL_SHOCK_PCT:
        label = "high_vol"
    elif adx_val is not None and adx_val >= TREND_ADX and trend_dir != 0:
        label = "trend_up" if trend_dir > 0 else "trend_down"
    elif adx_val is not None and adx_val < RANGE_ADX:
        label = "range"
    elif adx_val is None and vol_pct is not None:
        label = "transition"   # vol known, no trend info: don't tilt families
    else:
        label = "transition"

    return Regime(label=label, adx=adx_val, trend_dir=trend_dir,
                  daily_vol=daily_vol, vol_percentile=vol_pct, bars=n)


def regime_multipliers(regime: Regime | str, sources: list[str] | None = None) -> dict[str, float]:
    """Per-source multipliers for the given regime (1.0 for unknown sources)."""
    label = regime.label if isinstance(regime, Regime) else str(regime)
    tilt = REGIME_TILTS.get(label, REGIME_TILTS["unknown"])
    names = sources if sources is not None else sorted(
        TREND_FAMILY | MEANREV_FAMILY | PATTERN_FAMILY | FUNDAMENTAL_FAMILY)
    return {s: tilt.get(_family(s), 1.0) for s in names}


def apply_regime(weights: dict[str, float], regime: Regime | str) -> dict[str, float]:
    """Scale a weight table by the regime tilt (composes with other layers)."""
    mult = regime_multipliers(regime, list(weights.keys()))
    return {k: w * mult.get(k, 1.0) for k, w in weights.items()}
