"""Volatility-targeted sizing: backward compatible, vol-aware, always capped."""
import src.algo_trader.risk_engine as re_mod
from src.algo_trader.risk_engine import RiskEngine
from src.algo_trader.config import AlgoTraderConfig

OrderSide = re_mod.OrderSide


def _engine(target=0.01):
    cfg = AlgoTraderConfig()
    cfg.risk.target_risk_per_trade_pct = target
    return RiskEngine(cfg), cfg


def test_no_vol_matches_legacy_formula():
    eng, cfg = _engine()
    pv, px, conf = 1_000_000, 100.0, 0.8
    legacy = int(min(pv * cfg.risk.max_position_pct * conf, cfg.risk.max_single_order_value) / px)
    assert eng.calculate_position_size("X", OrderSide.BUY, pv, px, conf) == legacy


def test_higher_vol_gets_fewer_shares():
    eng, _ = _engine()
    # vol cap = pv * 1% / vol: 0.05 -> 2 lakh (above the 1 lakh order cap, no
    # effect), 0.20 -> 50k (binds). Shock-level vol halves the order.
    lo = eng.calculate_position_size("X", OrderSide.BUY, 1_000_000, 100.0, 0.8, daily_vol=0.05)
    hi = eng.calculate_position_size("X", OrderSide.BUY, 1_000_000, 100.0, 0.8, daily_vol=0.20)
    assert lo == 800 and hi == 500


def test_vol_cap_formula_and_hard_caps_hold():
    eng, cfg = _engine()
    pv, px, vol = 1_000_000, 50.0, 0.02
    shares = eng.calculate_position_size("X", OrderSide.BUY, pv, px, 1.0, daily_vol=vol)
    assert shares * px <= pv * 0.01 / vol + px          # vol cap respected
    assert shares * px <= cfg.risk.max_single_order_value + px
    assert shares * px <= pv * cfg.risk.max_position_pct + px


def test_targeting_disabled_restores_legacy():
    eng, cfg = _engine(target=None)
    a = eng.calculate_position_size("X", OrderSide.BUY, 1_000_000, 100.0, 0.8, daily_vol=0.05)
    b = eng.calculate_position_size("X", OrderSide.BUY, 1_000_000, 100.0, 0.8)
    assert a == b
