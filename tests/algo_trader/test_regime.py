"""Regime detection on synthetic series, and the weight tilts it produces."""
import numpy as np, pandas as pd
from src.algo_trader.regime import (detect_regime, regime_multipliers, apply_regime,
                                    realised_daily_vol, TREND_FAMILY, MEANREV_FAMILY)


def _ohlc(close):
    close = pd.Series(close, dtype=float)
    return pd.DataFrame({"close": close, "high": close * 1.004, "low": close * 0.996, "volume": 1000})


def test_too_few_bars_is_unknown():
    assert detect_regime(_ohlc(np.linspace(100, 110, 20))).label == "unknown"


def test_strong_uptrend_is_trend_up():
    rng = np.random.default_rng(0)
    close = 100 * np.cumprod(1 + 0.004 + 0.002 * rng.standard_normal(200))
    r = detect_regime(_ohlc(close))
    assert r.label == "trend_up" and r.trend_dir == 1


def test_vol_shock_is_high_vol():
    rng = np.random.default_rng(1)
    calm = 0.003 * rng.standard_normal(150)
    shock = 0.03 * rng.standard_normal(25)
    close = 100 * np.cumprod(1 + np.concatenate([calm, shock]))
    assert detect_regime(_ohlc(close)).label == "high_vol"


def test_realised_vol_matches_std():
    rng = np.random.default_rng(2)
    rets = 0.01 * rng.standard_normal(100)
    close = 100 * np.cumprod(1 + rets)
    v = realised_daily_vol(_ohlc(close), window=20)
    assert v is not None and abs(v - pd.Series(close).pct_change().iloc[-20:].std()) < 1e-12


def test_tilts_by_family():
    m = regime_multipliers("trend_up")
    assert all(m[s] > 1 for s in TREND_FAMILY) and all(m[s] < 1 for s in MEANREV_FAMILY)
    m = regime_multipliers("range")
    assert all(m[s] < 1 for s in TREND_FAMILY) and all(m[s] > 1 for s in MEANREV_FAMILY)
    assert set(regime_multipliers("unknown").values()) == {1.0}


def test_apply_regime_preserves_keys_and_unknown_sources():
    w = {"momentum": 0.06, "mean_reversion": 0.05, "something_new": 0.1}
    out = apply_regime(w, "trend_up")
    assert set(out) == set(w) and out["something_new"] == 0.1
