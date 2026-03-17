"""Decision engine — aggregates signals from hedge fund agents + technical strategies.

Combines the AI hedge fund's fundamental/sentiment analysis with quantitative
strategy signals (expanded ensemble) to produce final trading decisions.
Uses parallel data fetching and a price cache for low latency.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

import pandas as pd

from src.main import run_hedge_fund
from src.tools.api import get_price_data
from src.algo_trader.config import AlgoTraderConfig
from src.algo_trader.strategies.momentum import MomentumStrategy
from src.algo_trader.strategies.mean_reversion import MeanReversionStrategy
from src.algo_trader.strategies.supertrend import SupertrendStrategy
from src.algo_trader.strategies.vwap import VWAPStrategy
from src.algo_trader.strategies.adx_trend import ADXTrendStrategy
from src.algo_trader.strategies.volume_breakout import VolumeBreakoutStrategy
from src.algo_trader.strategies.squeeze_breakout import SqueezeBreakoutStrategy
from src.algo_trader.strategies.kama_squeeze_momentum import KAMASqueezeStrategy
from src.algo_trader.strategies.smart_money_accumulation import SmartMoneyAccumulationStrategy
from src.algo_trader.strategies.candle_patterns import detect_patterns

log = logging.getLogger(__name__)

SIGNAL_WEIGHTS = {
    "meta_analyst": 0.35,
    "hedge_fund": 0.15,
    "candle_patterns": 0.06,
    "momentum": 0.06,
    "mean_reversion": 0.05,
    "supertrend": 0.05,
    "vwap": 0.04,
    "adx_trend": 0.04,
    "volume_breakout": 0.05,
    "squeeze_breakout": 0.04,
    "kama_squeeze": 0.06,
    "smart_money": 0.05,
}

REVIEW_FILE = Path(__file__).resolve().parent.parent.parent / "outputs" / "portfolio_review.json"

# ── Price cache with TTL ─────────────────────────────────────────────

_price_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_cache_lock = Lock()
CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_cached_price(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Fetch price data, using cache when fresh enough."""
    key = f"{ticker}|{start}|{end}"
    with _cache_lock:
        if key in _price_cache:
            ts, df = _price_cache[key]
            if time.time() - ts < CACHE_TTL_SECONDS:
                return df

    try:
        df = get_price_data(ticker, start, end)
    except Exception:
        df = None

    if df is not None and not df.empty:
        with _cache_lock:
            _price_cache[key] = (time.time(), df)
    return df


@dataclass
class TradingSignal:
    ticker: str
    action: str             # "buy", "sell", "hold", "close"
    confidence: float       # 0.0 to 1.0
    source_signals: dict    # breakdown by source
    reasoning: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    instrument_type: str = "equity"           # "equity", "options", "futures"
    options_strategy: str | None = None       # e.g. "iron_condor"
    options_legs: list[dict] | None = None    # [{strike, opt_type, side, lots, premium}]
    futures_side: str | None = None           # "long", "short"
    futures_lots: int | None = None
    strategy_name: str = ""                   # which strategy produced this


def _signal_to_score(signal: str) -> float:
    return {"buy": 1.0, "bullish": 1.0, "sell": -1.0, "bearish": -1.0, "short": -1.0}.get(signal.lower(), 0.0)


class DecisionEngine:
    """Fuses multiple signal sources into actionable trading decisions."""

    def __init__(self, config: AlgoTraderConfig):
        self.config = config
        self.session_plan = None
        self.momentum = MomentumStrategy(config.strategy)
        self.mean_rev = MeanReversionStrategy(config.strategy)
        self.supertrend = SupertrendStrategy(config.strategy)
        self.vwap = VWAPStrategy(config.strategy)
        self.adx_trend = ADXTrendStrategy(config.strategy)
        self.vol_breakout = VolumeBreakoutStrategy(config.strategy)
        self.squeeze = SqueezeBreakoutStrategy(config.strategy)
        self.kama_squeeze = KAMASqueezeStrategy()
        self.smart_money = SmartMoneyAccumulationStrategy()

    def set_session_plan(self, plan):
        """Set the current Hermes SessionPlan for dynamic strategy weighting."""
        self.session_plan = plan

    def _get_weights(self) -> dict[str, float]:
        """Return strategy weights — from SessionPlan if available, else defaults."""
        if self.session_plan and self.session_plan.strategy_weights:
            return self.session_plan.strategy_weights
        return SIGNAL_WEIGHTS

    def analyse_universe(self, tickers: list[str]) -> list[TradingSignal]:
        """Run full analysis pipeline with parallel data fetching.

        If F&O is enabled and the session plan allocates capital to options/futures,
        generates F&O signals alongside equity signals.
        """
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        log.info("Loading latest Meta Analyst verdicts from review cache...")
        meta_verdicts = self._load_meta_verdicts()
        if meta_verdicts:
            log.info("Found Meta Analyst verdicts for %d stocks (swarm+options+21 agents)", len(meta_verdicts))
        else:
            log.info("No cached Meta Analyst verdicts — will rely on live hedge fund run")

        log.info("Running AI hedge fund analysis on %d tickers...", len(tickers))
        hedge_fund_result = self._run_hedge_fund(tickers, start_date, end_date)

        log.info("Running expanded quant strategies (parallel)...")
        quant_signals = self._run_quant_strategies_parallel(tickers, start_date, end_date)

        signals: list[TradingSignal] = []
        for ticker in tickers:
            signal = self._fuse_signals(ticker, hedge_fund_result, quant_signals, meta_verdicts)
            signals.append(signal)

        if self.config.enable_fno:
            fno_signals = self._generate_fno_signals(tickers, quant_signals, meta_verdicts, start_date, end_date)
            signals.extend(fno_signals)

        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals

    @staticmethod
    def _load_meta_verdicts() -> dict:
        """Load the latest Meta Analyst verdicts from the review cache file.

        Returns a dict keyed by ticker with action, confidence, score,
        signal_breakdown, and per-agent signals.  Returns {} if no
        recent review exists or the file is stale (>24h).
        """
        try:
            if not REVIEW_FILE.exists():
                return {}
            data = json.loads(REVIEW_FILE.read_text())
            review_time = data.get("review_time", "")
            if review_time:
                rt = datetime.fromisoformat(review_time.replace("Z", "+00:00"))
                age_hours = (datetime.now(rt.tzinfo) - rt).total_seconds() / 3600
                if age_hours > 24:
                    log.info("Meta verdicts are %.1f hours old — treating as stale", age_hours)
                    return {}
            return data.get("verdicts", {})
        except Exception as e:
            log.warning("Could not load meta verdicts: %s", e)
            return {}

    def _run_hedge_fund(self, tickers: list[str], start_date: str, end_date: str) -> dict:
        portfolio = {
            "cash": 1_000_000,
            "margin_requirement": 0.0,
            "margin_used": 0.0,
            "positions": {t: {"long": 0, "short": 0, "long_cost_basis": 0.0, "short_cost_basis": 0.0, "short_margin_used": 0.0} for t in tickers},
            "realized_gains": {t: {"long": 0.0, "short": 0.0} for t in tickers},
        }
        try:
            result = run_hedge_fund(
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                portfolio=portfolio,
                show_reasoning=False,
                selected_analysts=self.config.selected_analysts if self.config.selected_analysts else [],
                model_name=self.config.model_name,
                model_provider=self.config.model_provider,
            )
            return result or {}
        except Exception as e:
            log.error("Hedge fund analysis failed: %s", e)
            return {}

    def _analyse_single_ticker(self, ticker: str, start: str, end: str) -> dict:
        """Fetch data once and run all quant strategies on a single ticker."""
        empty = {
            "momentum": None, "mean_reversion": None, "supertrend": None,
            "vwap": None, "adx_trend": None, "volume_breakout": None,
            "squeeze_breakout": None, "kama_squeeze": None, "smart_money": None,
            "candle_patterns": None,
        }
        try:
            df = _get_cached_price(ticker, start, end)
            if df is None or df.empty:
                return empty

            candle = detect_patterns(df, lookback=5)
            candle_sig = {
                "signal": "buy" if candle.bias == "bullish" else ("sell" if candle.bias == "bearish" else "hold"),
                "confidence": candle.strength,
                "indicators": {"patterns": candle.patterns, "bias": candle.bias},
            }

            return {
                "momentum": self._safe_analyse(self.momentum, df),
                "mean_reversion": self._safe_analyse(self.mean_rev, df),
                "supertrend": self._safe_analyse(self.supertrend, df),
                "vwap": self._safe_analyse(self.vwap, df),
                "adx_trend": self._safe_analyse(self.adx_trend, df),
                "volume_breakout": self._safe_analyse(self.vol_breakout, df),
                "squeeze_breakout": self._safe_analyse(self.squeeze, df),
                "kama_squeeze": self._safe_analyse(self.kama_squeeze, df),
                "smart_money": self._safe_analyse(self.smart_money, df),
                "candle_patterns": candle_sig,
            }
        except Exception as e:
            log.warning("Analysis failed for %s: %s", ticker, e)
            return empty

    @staticmethod
    def _safe_analyse(strategy, df: pd.DataFrame) -> dict | None:
        try:
            return strategy.analyse(df)
        except Exception:
            return None

    def _run_quant_strategies_parallel(self, tickers: list[str], start: str, end: str) -> dict[str, dict]:
        """Run all quant strategies on all tickers using thread pool."""
        results: dict[str, dict] = {}
        max_workers = min(len(tickers), 8)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._analyse_single_ticker, t, start, end): t for t in tickers}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    results[ticker] = future.result()
                except Exception as e:
                    log.warning("Thread failed for %s: %s", ticker, e)
                    results[ticker] = {}

        return results

    def _fuse_signals(
        self,
        ticker: str,
        hedge_fund_result: dict,
        quant_signals: dict[str, dict],
        meta_verdicts: dict | None = None,
    ) -> TradingSignal:
        """Combine all signal sources using weighted scoring.

        When Meta Analyst verdicts are available they carry the highest
        weight (0.35) since they already represent the consensus of 21
        agents including swarm intelligence and options flow.
        """
        sources = {}
        weighted_score = 0.0
        total_weight = 0.0

        weights = self._get_weights()

        # --- Meta Analyst verdict (21-agent consensus) ---
        meta_v = (meta_verdicts or {}).get(ticker)
        if meta_v:
            meta_action = meta_v.get("action", "hold").lower()
            meta_conf = float(meta_v.get("confidence", 0))
            if meta_conf > 1:
                meta_conf /= 100.0
            sources["meta_analyst"] = {
                "action": meta_action,
                "confidence": meta_conf,
                "score": meta_v.get("score", 0),
                "signal_breakdown": meta_v.get("signal_breakdown", {}),
            }
            meta_score = _signal_to_score(meta_action) * meta_conf
            w = weights.get("meta_analyst", 0.35)
            weighted_score += meta_score * w
            total_weight += w

        # --- Live hedge fund signal ---
        hf_signal = self._extract_hedge_fund_signal(ticker, hedge_fund_result)
        if hf_signal:
            sources["hedge_fund"] = hf_signal
            hf_score = _signal_to_score(hf_signal["action"]) * hf_signal["confidence"]
            w = weights.get("hedge_fund", 0.15)
            weighted_score += hf_score * w
            total_weight += w

        # --- Quant strategy signals ---
        ticker_quant = quant_signals.get(ticker, {})
        for strategy_name in [
            "candle_patterns", "momentum", "mean_reversion", "supertrend",
            "vwap", "adx_trend", "volume_breakout", "squeeze_breakout",
            "kama_squeeze", "smart_money",
        ]:
            sig = ticker_quant.get(strategy_name)
            if sig and sig.get("signal"):
                sources[strategy_name] = sig
                score = _signal_to_score(sig["signal"]) * sig.get("confidence", 0.5)
                weight = weights.get(strategy_name, 0.05)
                weighted_score += score * weight
                total_weight += weight

        if total_weight > 0:
            final_score = weighted_score / total_weight
        else:
            final_score = 0.0

        confidence = min(abs(final_score), 1.0)
        if final_score > 0.15:
            action = "buy"
        elif final_score < -0.15:
            action = "sell"
        else:
            action = "hold"

        reasoning_parts = []
        for src_name, src_data in sources.items():
            sig = src_data.get("signal", src_data.get("action", "?"))
            conf = src_data.get("confidence", 0)
            reasoning_parts.append(f"{src_name}: {sig} ({conf:.0%})")

        return TradingSignal(
            ticker=ticker,
            action=action,
            confidence=round(confidence, 3),
            source_signals=sources,
            reasoning=" | ".join(reasoning_parts) if reasoning_parts else "Insufficient data",
        )

    def _generate_fno_signals(
        self,
        tickers: list[str],
        quant_signals: dict[str, dict],
        meta_verdicts: dict | None,
        start_date: str,
        end_date: str,
    ) -> list[TradingSignal]:
        """Generate options and futures signals for index/stock F&O.

        Uses the existing options and futures strategy modules when available,
        and falls back to deriving F&O signals from equity signal strength.
        """
        fno_signals: list[TradingSignal] = []
        alloc = {"options": 0.4, "futures": 0.2}
        if self.session_plan:
            alloc = self.session_plan.asset_allocation

        fno_underlyings = ["NIFTY", "BANKNIFTY"]
        index_tickers = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}

        for underlying in fno_underlyings:
            index_ticker = index_tickers.get(underlying)
            if not index_ticker:
                continue
            try:
                df = _get_cached_price(index_ticker, start_date, end_date)
                if df is None or df.empty:
                    continue
            except Exception:
                continue

            # Futures signals from quant strategies applied to index data
            if alloc.get("futures", 0) > 0.05:
                try:
                    mom = self._safe_analyse(self.momentum, df)
                    st = self._safe_analyse(self.supertrend, df)
                    adx = self._safe_analyse(self.adx_trend, df)

                    fut_score = 0.0
                    n = 0
                    for sig in [mom, st, adx]:
                        if sig and sig.get("signal"):
                            fut_score += _signal_to_score(sig["signal"]) * sig.get("confidence", 0.5)
                            n += 1
                    if n > 0:
                        fut_score /= n

                    if abs(fut_score) > 0.2:
                        fno_signals.append(TradingSignal(
                            ticker=f"{underlying}.NS",
                            action="buy" if fut_score > 0 else "sell",
                            confidence=min(abs(fut_score), 1.0),
                            source_signals={"momentum": mom, "supertrend": st, "adx_trend": adx},
                            reasoning=f"Futures {underlying}: trend score {fut_score:+.2f}",
                            instrument_type="futures",
                            futures_side="long" if fut_score > 0 else "short",
                            futures_lots=1,
                            strategy_name="trend_following_futures",
                        ))
                except Exception as e:
                    log.warning("Futures signal generation failed for %s: %s", underlying, e)

            # Options signals — high volatility favors straddles/strangles,
            # directional signals favor spreads
            if alloc.get("options", 0) > 0.05:
                try:
                    mr = self._safe_analyse(self.mean_rev, df)
                    sq = self._safe_analyse(self.squeeze, df)

                    is_squeeze = sq and sq.get("signal") in ("buy", "sell")
                    is_mean_rev = mr and mr.get("signal") in ("buy", "sell")

                    if is_squeeze:
                        fno_signals.append(TradingSignal(
                            ticker=f"{underlying}.NS",
                            action="buy",
                            confidence=sq.get("confidence", 0.5) if sq else 0.5,
                            source_signals={"squeeze_breakout": sq},
                            reasoning=f"Options {underlying}: squeeze detected — long straddle",
                            instrument_type="options",
                            options_strategy="long_straddle",
                            options_legs=[
                                {"strike": 0, "opt_type": "CE", "side": "BUY", "lots": 1, "premium": 0},
                                {"strike": 0, "opt_type": "PE", "side": "BUY", "lots": 1, "premium": 0},
                            ],
                            strategy_name="long_straddle",
                        ))
                    elif is_mean_rev:
                        direction = mr.get("signal", "hold") if mr else "hold"
                        if direction == "buy":
                            fno_signals.append(TradingSignal(
                                ticker=f"{underlying}.NS",
                                action="buy",
                                confidence=mr.get("confidence", 0.5) if mr else 0.5,
                                source_signals={"mean_reversion": mr},
                                reasoning=f"Options {underlying}: bullish reversion — bull call spread",
                                instrument_type="options",
                                options_strategy="bull_call_spread",
                                options_legs=[
                                    {"strike": 0, "opt_type": "CE", "side": "BUY", "lots": 1, "premium": 0},
                                    {"strike": 0, "opt_type": "CE", "side": "SELL", "lots": 1, "premium": 0},
                                ],
                                strategy_name="bull_call_spread",
                            ))
                        elif direction == "sell":
                            fno_signals.append(TradingSignal(
                                ticker=f"{underlying}.NS",
                                action="sell",
                                confidence=mr.get("confidence", 0.5) if mr else 0.5,
                                source_signals={"mean_reversion": mr},
                                reasoning=f"Options {underlying}: bearish reversion — bear put spread",
                                instrument_type="options",
                                options_strategy="bear_put_spread",
                                options_legs=[
                                    {"strike": 0, "opt_type": "PE", "side": "BUY", "lots": 1, "premium": 0},
                                    {"strike": 0, "opt_type": "PE", "side": "SELL", "lots": 1, "premium": 0},
                                ],
                                strategy_name="bear_put_spread",
                            ))
                except Exception as e:
                    log.warning("Options signal generation failed for %s: %s", underlying, e)

        return fno_signals

    @staticmethod
    def _extract_hedge_fund_signal(ticker: str, result: dict) -> dict | None:
        decisions = result.get("decisions")
        if not decisions:
            return None

        clean_ticker = ticker.upper().replace(".NS", "").replace(".BO", "")

        # PortfolioManagerOutput.decisions is dict[str, PortfolioDecision]
        if isinstance(decisions, dict):
            for dec_ticker, decision in decisions.items():
                dec_clean = dec_ticker.upper().replace(".NS", "").replace(".BO", "")
                if dec_clean == clean_ticker:
                    if isinstance(decision, dict):
                        action = decision.get("action", "hold").lower()
                        conf = float(decision.get("confidence", 0))
                    else:
                        action = getattr(decision, "action", "hold").lower()
                        conf = float(getattr(decision, "confidence", 0))
                    if conf > 1:
                        conf /= 100.0
                    return {"action": action, "confidence": conf}
        elif isinstance(decisions, list):
            for decision in decisions:
                if not isinstance(decision, dict):
                    continue
                dec_ticker = decision.get("ticker", decision.get("symbol", ""))
                dec_clean = dec_ticker.upper().replace(".NS", "").replace(".BO", "")
                if dec_clean == clean_ticker:
                    action = decision.get("action", "hold").lower()
                    conf = float(decision.get("confidence", 0))
                    if conf > 1:
                        conf /= 100.0
                    return {"action": action, "confidence": conf}

        # Fallback: aggregate raw analyst signals
        analyst_signals = result.get("analyst_signals", {})
        buys = sells = holds = 0
        for _agent, signals in analyst_signals.items():
            if isinstance(signals, dict):
                ticker_signal = signals.get(ticker, {})
                if isinstance(ticker_signal, dict):
                    sig = ticker_signal.get("signal", "").lower()
                    if sig in ("buy", "bullish", "long"):
                        buys += 1
                    elif sig in ("sell", "bearish", "short"):
                        sells += 1
                    else:
                        holds += 1

        total_votes = buys + sells + holds
        if total_votes == 0:
            return None

        if buys > sells:
            return {"action": "buy", "confidence": buys / total_votes}
        elif sells > buys:
            return {"action": "sell", "confidence": sells / total_votes}
        return {"action": "hold", "confidence": holds / total_votes}
