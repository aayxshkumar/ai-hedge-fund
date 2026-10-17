"""Signal fusion: agreement-aware confidence, attribution, regime/vol pass-through."""
import pytest
from src.algo_trader.config import AlgoTraderConfig
from src.algo_trader.decision_engine import DecisionEngine


@pytest.fixture
def engine():
    eng = DecisionEngine(AlgoTraderConfig())
    eng.adaptive = None            # isolate fusion from the tracker
    eng.session_plan = None
    return eng


def _quant(signal, conf, regime="unknown", vol=None):
    names = ["candle_patterns", "momentum", "mean_reversion", "supertrend", "vwap",
             "adx_trend", "volume_breakout", "squeeze_breakout", "kama_squeeze", "smart_money"]
    q = {n: {"signal": signal, "confidence": conf, "indicators": {}} for n in names}
    q["_regime"] = {"label": regime}
    q["_daily_vol"] = vol
    return q


def test_unanimous_buy(engine):
    sig = engine._fuse_signals("X", {}, {"X": _quant("buy", 0.8, "trend_up", 0.012)}, None)
    assert sig.action == "buy" and sig.agreement == 1.0 and sig.confidence == pytest.approx(0.8, abs=1e-6)
    assert sig.strategy_name in sig.source_signals
    assert sig.regime == "trend_up" and sig.daily_vol == 0.012


def test_conflict_cuts_confidence(engine):
    q = _quant("buy", 0.8)
    for n in ["momentum", "mean_reversion", "supertrend", "vwap", "adx_trend"]:
        q[n] = {"signal": "sell", "confidence": 0.8, "indicators": {}}
    sig = engine._fuse_signals("X", {}, {"X": q}, None)
    uni = engine._fuse_signals("X", {}, {"X": _quant("buy", 0.8)}, None)
    assert sig.agreement < 0.8 and sig.confidence < uni.confidence


def test_all_hold_is_hold_with_no_attribution(engine):
    sig = engine._fuse_signals("X", {}, {"X": _quant("hold", 0.0)}, None)
    assert sig.action == "hold" and sig.strategy_name == ""


def test_regime_tilt_changes_outcome_direction_weighting(engine):
    # trend family says buy, mean-reversion family says sell, equal confidence:
    # a trend regime should lean buy, a range regime should lean sell.
    def q(regime):
        d = _quant("buy", 0.7, regime)
        for n in ["mean_reversion", "vwap", "candle_patterns"]:
            d[n] = {"signal": "sell", "confidence": 0.7, "indicators": {}}
        return d
    trend = engine._fuse_signals("X", {}, {"X": q("trend_up")}, None)
    rng = engine._fuse_signals("X", {}, {"X": q("range")}, None)
    score = lambda s: (1 if s.action == "buy" else -1 if s.action == "sell" else 0) * s.confidence
    assert score(trend) > score(rng)
