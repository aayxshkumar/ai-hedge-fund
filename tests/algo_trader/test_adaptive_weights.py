"""Adaptive weights must be neutral without evidence, move with it, and stay bounded."""
import os, tempfile
import pytest
from src.algo_trader.strategy_tracker import StrategyTracker
from src.algo_trader.adaptive_weights import AdaptiveWeights, performance_multiplier, SourceStats, MIN_MULT, MAX_MULT


@pytest.fixture
def tracker():
    return StrategyTracker(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_neutral_without_data(tracker):
    aw = AdaptiveWeights(tracker, ttl=0)
    base = {"momentum": 0.06, "meta_analyst": 0.35}
    assert aw.apply(base) == base


def test_neutral_without_tracker():
    base = {"momentum": 0.06}
    assert AdaptiveWeights(None).apply(base) == base


def test_short_streak_barely_moves(tracker):
    for _ in range(3):
        tracker.record_live_trade("momentum", pnl=100, confidence=.7, won=True)
    m = AdaptiveWeights(tracker, ttl=0).multipliers()["momentum"]
    assert 1.0 < m < 1.05


def test_evidence_boosts_and_damps(tracker):
    for i in range(40):
        tracker.record_live_trade("good", pnl=1, confidence=.6, won=(i % 10 < 7))
        tracker.record_live_trade("bad", pnl=-1, confidence=.6, won=(i % 10 < 3))
    m = AdaptiveWeights(tracker, ttl=0).multipliers()
    assert m["good"] > 1.1 and m["bad"] < 0.9


def test_unapproved_backtest_is_capped(tracker):
    tracker.record_backtest("mom", "equity", sharpe=-0.5, win_rate=.4, max_drawdown=.2,
                            expectancy=-10, total_return=-.05, total_trades=50)
    assert AdaptiveWeights(tracker, ttl=0).multipliers()["mom"] <= 0.8


def test_bounds():
    assert performance_multiplier(SourceStats("x", live_trades=10_000, live_wins=10_000)) == MAX_MULT
    assert performance_multiplier(SourceStats("y", live_trades=10_000, live_wins=0)) == MIN_MULT


def test_get_live_stats_aggregates(tracker):
    tracker.record_live_trade("s", pnl=5, won=True)
    tracker.record_live_trade("s", pnl=-2, won=False)
    assert tracker.get_live_stats()["s"] == {"trades": 2, "wins": 1, "pnl": 3.0}
