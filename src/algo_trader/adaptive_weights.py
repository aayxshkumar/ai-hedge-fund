"""Adaptive signal weighting from tracked strategy performance.

The decision engine fuses many signal sources with a fixed weight table. The
StrategyTracker already records how each strategy has actually performed -
backtest Sharpe/expectancy and, once trades are attributed, live wins/losses -
but nothing fed that evidence back into the weights. This module turns the
tracked record into a per-source multiplier that scales the base weights.

Design rules, so the change is safe to deploy:

* **Behaviour-preserving by default.** With no tracked data every multiplier
  is exactly 1.0, so the engine behaves as before until evidence accrues.
* **Shrinkage, not overreaction.** Live win-rate is a Bayesian estimate with a
  Beta prior centred on 50 %; its influence grows with the number of trades
  (``n / (n + PRIOR_TRADES)``), so a 3-trade hot streak barely moves anything.
* **Bounded.** Multipliers live in ``[MIN_MULT, MAX_MULT]``; no source can be
  silenced or made dominant by a run of luck.
* **Composes.** It multiplies whatever base weights the engine already chose
  (defaults or a Hermes SessionPlan) rather than replacing them.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

PRIOR_TRADES = 20          # pseudo-trades before live evidence outweighs the prior
BETA_PRIOR = 10.0          # Beta(10, 10): win-rate prior centred on 0.5
MIN_MULT = 0.5
MAX_MULT = 1.6
SHARPE_APPROVAL = 0.3      # mirrors StrategyTracker.record_backtest's approval bar
CACHE_TTL_SECONDS = 300


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class SourceStats:
    strategy_name: str
    live_trades: int = 0
    live_wins: int = 0
    live_pnl: float = 0.0
    backtest_sharpe: float | None = None
    backtest_expectancy: float | None = None
    backtest_trades: int = 0
    approved: bool | None = None


def performance_multiplier(stats: SourceStats) -> float:
    """Map one source's tracked record to a weight multiplier.

    Two independent factors are combined:

    live    Bayesian win-rate: (wins + a) / (trades + a + b) with a = b = 10,
            mapped so 50 % -> 1.0, 75 % -> 1.5, 25 % -> 0.5, then pulled toward
            1.0 by the evidence weight n / (n + PRIOR_TRADES). A losing record
            with positive expectancy is not punished further: the win-rate
            already carries it.
    backtest Sharpe relative to the approval bar: 1 + 0.2 * (sharpe - 0.3),
            clipped to [0.7, 1.3]; an explicitly unapproved strategy is capped
            at 0.8 regardless of its Sharpe.
    """
    n = max(stats.live_trades, 0)
    wins = max(min(stats.live_wins, n), 0)
    post_wr = (wins + BETA_PRIOR) / (n + 2 * BETA_PRIOR)
    live_factor = 1.0 + (post_wr - 0.5) * 2.0
    evidence = n / (n + PRIOR_TRADES) if n else 0.0
    live_mult = 1.0 + (live_factor - 1.0) * evidence

    bt_mult = 1.0
    if stats.backtest_sharpe is not None and stats.backtest_trades > 0:
        bt_mult = _clip(1.0 + 0.2 * (stats.backtest_sharpe - SHARPE_APPROVAL), 0.7, 1.3)
        if stats.approved is False:
            bt_mult = min(bt_mult, 0.8)

    return _clip(live_mult * bt_mult, MIN_MULT, MAX_MULT)


class AdaptiveWeights:
    """Per-source weight multipliers derived from a StrategyTracker.

    ``tracker`` may be None (multipliers are all 1.0). Results are cached for
    ``ttl`` seconds because the tracker is SQLite and the engine fuses many
    tickers per cycle.
    """

    def __init__(self, tracker=None, ttl: float = CACHE_TTL_SECONDS):
        self.tracker = tracker
        self.ttl = ttl
        self._cache: dict[str, float] | None = None
        self._cached_at = 0.0

    def stats(self) -> dict[str, SourceStats]:
        out: dict[str, SourceStats] = {}
        if self.tracker is None:
            return out
        try:
            for row in self.tracker.get_all_performance():
                s = out.setdefault(row["strategy_name"], SourceStats(row["strategy_name"]))
                s.backtest_sharpe = float(row.get("sharpe") or 0.0)
                s.backtest_expectancy = float(row.get("expectancy") or 0.0)
                s.backtest_trades = int(row.get("total_trades") or 0)
                s.approved = bool(row.get("approved"))
            for name, live in self.tracker.get_live_stats().items():
                s = out.setdefault(name, SourceStats(name))
                s.live_trades = int(live.get("trades") or 0)
                s.live_wins = int(live.get("wins") or 0)
                s.live_pnl = float(live.get("pnl") or 0.0)
        except Exception as e:  # never let bookkeeping break trading
            log.warning("adaptive weights: tracker read failed, using neutral weights: %s", e)
            return {}
        return out

    def multipliers(self) -> dict[str, float]:
        now = time.time()
        if self._cache is not None and now - self._cached_at < self.ttl:
            return self._cache
        self._cache = {name: performance_multiplier(s) for name, s in self.stats().items()}
        self._cached_at = now
        return self._cache

    def apply(self, base_weights: dict[str, float]) -> dict[str, float]:
        """Scale ``base_weights`` by the tracked multipliers (1.0 where unknown)."""
        mult = self.multipliers()
        return {k: w * mult.get(k, 1.0) for k, w in base_weights.items()}

    def invalidate(self):
        self._cache = None
