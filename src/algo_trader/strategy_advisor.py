"""Strategy Advisor — Hermes-powered session planning via LLM.

Before each trading session, builds context from the tradebook and memory,
then asks the LLM to produce a SessionPlan with strategy weights, risk
overrides, and asset allocation.  After each session, feeds results back
so the system learns and adapts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

from src.algo_trader.hermes_bridge import build_session_context, write_session_review

log = logging.getLogger(__name__)

AVAILABLE_STRATEGIES = {
    "equity": [
        "momentum", "mean_reversion", "supertrend", "vwap", "adx_trend",
        "volume_breakout", "squeeze_breakout", "kama_squeeze", "smart_money",
        "candle_patterns", "donchian", "ichimoku", "stoch_rsi", "obv_divergence",
        "ma_ribbon", "keltner", "sentiment_momentum", "regime_switch",
        "opening_range_breakout", "gap_fade", "relative_strength",
    ],
    "options": [
        "long_straddle", "short_straddle", "long_strangle", "iron_condor",
        "bull_call_spread", "bear_put_spread", "iron_butterfly",
    ],
    "futures": [
        "trend_following_futures", "mean_reversion_futures",
        "breakout_momentum_futures", "vwap_reversion_futures",
    ],
}


@dataclass
class SessionPlan:
    strategy_weights: dict[str, float] = field(default_factory=dict)
    risk_overrides: dict[str, float] = field(default_factory=dict)
    asset_allocation: dict[str, float] = field(default_factory=lambda: {
        "equity": 0.40, "options": 0.40, "futures": 0.20,
    })
    focus_tickers: list[str] = field(default_factory=list)
    reasoning: str = ""
    avoid_patterns: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SessionPlan:
        return cls(
            strategy_weights=d.get("strategy_weights", {}),
            risk_overrides=d.get("risk_overrides", {}),
            asset_allocation=d.get("asset_allocation", {"equity": 0.4, "options": 0.4, "futures": 0.2}),
            focus_tickers=d.get("focus_tickers", []),
            reasoning=d.get("reasoning", ""),
            avoid_patterns=d.get("avoid_patterns", []),
            timestamp=d.get("timestamp", ""),
        )

    @classmethod
    def default(cls) -> SessionPlan:
        """Sensible defaults when LLM is unavailable."""
        weights = {}
        for s in AVAILABLE_STRATEGIES["equity"][:10]:
            weights[s] = 0.06
        for s in AVAILABLE_STRATEGIES["options"][:3]:
            weights[s] = 0.08
        for s in AVAILABLE_STRATEGIES["futures"][:2]:
            weights[s] = 0.06
        weights["meta_analyst"] = 0.20
        return cls(
            strategy_weights=weights,
            asset_allocation={"equity": 0.40, "options": 0.40, "futures": 0.20},
            reasoning="Default session plan — LLM unavailable",
        )


SESSION_PLAN_PROMPT = """You are the Hermes Strategy Advisor for an AI-powered trading system on Indian markets (NSE/BSE/NFO).

Your job: analyze the trading history, market conditions, and past performance to produce an optimal SESSION PLAN for the next trading session.

## Context
{context}

## Available Strategies
Equity: {equity_strategies}
Options (NFO): {options_strategies}
Futures (NFO): {futures_strategies}

## Rules
1. PREFER TECHNICAL over fundamental analysis — this system trades on technicals primarily
2. PREFER OPTIONS AND FUTURES over plain equity — F&O offers leverage and hedging
3. Learn from past mistakes — if a strategy consistently loses, reduce its weight
4. Adapt to market regime — trending markets favor momentum/trend; sideways favors mean-reversion/options-selling
5. No restriction on holding period — long-term bets are fine if the signal is strong
6. Be specific about risk overrides if the market is volatile (tighter stops) or calm (wider stops)
7. Focus tickers should be the ones with the clearest signals from recent analysis
8. Avoid patterns you've seen fail repeatedly

## Output Format
Return ONLY valid JSON (no markdown, no explanation outside JSON):
{{
  "strategy_weights": {{"strategy_name": weight_float, ...}},
  "risk_overrides": {{"max_position_pct": float, "stop_loss_pct": float, ...}},
  "asset_allocation": {{"equity": float, "options": float, "futures": float}},
  "focus_tickers": ["TICKER1.NS", "TICKER2.NS"],
  "reasoning": "1-2 sentence explanation of your choices",
  "avoid_patterns": ["pattern description"]
}}

Weights should sum to roughly 1.0. Asset allocation must sum to 1.0.
"""


def generate_session_plan(tradebook=None, model_name: str = "claude-sonnet-4-20250514") -> SessionPlan:
    """Generate a SessionPlan by calling the LLM with full trading context."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    context = build_session_context(tradebook=tradebook)

    prompt_text = SESSION_PLAN_PROMPT.format(
        context=context,
        equity_strategies=", ".join(AVAILABLE_STRATEGIES["equity"]),
        options_strategies=", ".join(AVAILABLE_STRATEGIES["options"]),
        futures_strategies=", ".join(AVAILABLE_STRATEGIES["futures"]),
    )

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage

        llm = ChatAnthropic(model=model_name, temperature=0.3, max_tokens=2000)
        response = llm.invoke([HumanMessage(content=prompt_text)])
        raw = response.content if hasattr(response, "content") else str(response)

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]

        plan_data = json.loads(raw)
        plan = SessionPlan.from_dict(plan_data)
        plan.timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()

        _normalize_weights(plan)
        log.info("[hermes] Session plan generated: %d strategies, allocation=%s",
                 len(plan.strategy_weights), plan.asset_allocation)
        return plan

    except Exception as e:
        log.warning("[hermes] Session plan generation failed (%s), using defaults", e)
        plan = SessionPlan.default()
        plan.timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
        return plan


def _normalize_weights(plan: SessionPlan):
    """Ensure strategy weights and asset allocation sum to ~1.0."""
    total = sum(plan.strategy_weights.values())
    if total > 0 and abs(total - 1.0) > 0.05:
        for k in plan.strategy_weights:
            plan.strategy_weights[k] /= total

    alloc_total = sum(plan.asset_allocation.values())
    if alloc_total > 0 and abs(alloc_total - 1.0) > 0.05:
        for k in plan.asset_allocation:
            plan.asset_allocation[k] /= alloc_total


def complete_session(session_stats: dict):
    """Post-session: write review and lessons via Hermes."""
    write_session_review(session_stats)
