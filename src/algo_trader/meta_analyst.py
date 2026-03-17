"""Meta Analyst — Aggregates all individual analyst signals into a final verdict per stock.

Uses weighted voting: each analyst's signal contributes a score proportional to
its confidence. The final action is determined by the aggregate score and the
distribution of bullish vs bearish signals.
"""

from __future__ import annotations
from typing import Any

AGENT_WEIGHTS: dict[str, float] = {
    "technical_analyst_agent": 1.2,
    "fundamentals_analyst_agent": 1.3,
    "sentiment_analyst_agent": 1.0,
    "valuation_analyst_agent": 1.2,
    "growth_analyst_agent": 1.0,
    "warren_buffett_agent": 1.1,
    "charlie_munger_agent": 1.1,
    "cathie_wood_agent": 0.9,
    "ben_graham_agent": 1.1,
    "peter_lynch_agent": 1.0,
    "phil_fisher_agent": 1.0,
    "stanley_druckenmiller_agent": 1.0,
    "michael_burry_agent": 0.9,
    "bill_ackman_agent": 0.9,
    "aswath_damodaran_agent": 1.1,
    "rakesh_jhunjhunwala_agent": 1.0,
    "options_analyst_agent": 1.3,
    "target_analyst_agent": 1.2,
    "swarm_analyst_agent": 1.5,
}

SIGNAL_MAP = {
    "bullish": 1, "strong_buy": 1.5, "buy": 1, "long": 1,
    "bearish": -1, "strong_sell": -1.5, "sell": -1, "short": -1,
    "neutral": 0, "hold": 0,
}


def _parse_signal(raw: Any) -> tuple[str, float, str]:
    """Extract (signal_str, confidence, reasoning) from an analyst's raw output."""
    if isinstance(raw, dict):
        sig = str(raw.get("signal", raw.get("action", "neutral"))).lower().strip()
        conf = raw.get("confidence", 0)
        if isinstance(conf, (int, float)):
            conf = float(conf)
            if conf > 1.0:
                conf /= 100.0
            conf = max(0.0, min(1.0, conf))
        else:
            conf = 0
        reasoning_raw = raw.get("reasoning", "")
        if isinstance(reasoning_raw, dict):
            reasoning = "; ".join(f"{k}: {v}" for k, v in reasoning_raw.items() if isinstance(v, (str, dict)))[:300]
        else:
            reasoning = str(reasoning_raw)[:300]
        return sig, float(conf), reasoning
    elif isinstance(raw, str):
        return raw.lower().strip(), 0.5, ""
    return "neutral", 0, ""


def aggregate_signals(
    analyst_signals: dict[str, dict[str, Any]],
    ticker: str,
) -> dict:
    """Aggregate all analyst signals for a single ticker into a final verdict.

    Returns dict with: action, confidence, reasoning, signal_breakdown, score
    """
    votes: list[dict] = []
    total_weight = 0
    weighted_score = 0

    for agent_name, per_ticker_signals in analyst_signals.items():
        if not isinstance(per_ticker_signals, dict):
            continue
        raw = per_ticker_signals.get(ticker)
        if raw is None:
            continue

        sig_str, conf, reasoning = _parse_signal(raw)
        score = SIGNAL_MAP.get(sig_str, 0)
        weight = AGENT_WEIGHTS.get(agent_name, 1.0)

        effective_weight = weight * max(conf, 0.1)
        weighted_score += score * effective_weight
        total_weight += effective_weight

        votes.append({
            "agent": agent_name,
            "signal": sig_str,
            "score": score,
            "confidence": round(conf, 2),
            "weight": round(effective_weight, 2),
            "reasoning": reasoning,
        })

    if total_weight == 0 or len(votes) == 0:
        return {
            "action": "hold",
            "confidence": 0,
            "reasoning": "No analyst signals available for this ticker.",
            "signal_breakdown": {},
            "score": 0,
        }

    normalized_score = weighted_score / total_weight

    bullish_count = sum(1 for v in votes if v["score"] > 0)
    bearish_count = sum(1 for v in votes if v["score"] < 0)
    neutral_count = sum(1 for v in votes if v["score"] == 0)
    total_votes = len(votes)
    bullish_pct = bullish_count / total_votes
    bearish_pct = bearish_count / total_votes

    if normalized_score > 0.5 and bullish_pct >= 0.5:
        action = "strong buy"
    elif normalized_score > 0.2:
        action = "buy"
    elif normalized_score < -0.5 and bearish_pct >= 0.5:
        action = "strong sell"
    elif normalized_score < -0.2:
        action = "sell"
    else:
        action = "hold"

    conf_magnitude = min(abs(normalized_score), 1.0)
    consensus_bonus = 0
    if bullish_pct >= 0.7 or bearish_pct >= 0.7:
        consensus_bonus = 0.15
    elif bullish_pct >= 0.5 or bearish_pct >= 0.5:
        consensus_bonus = 0.05
    confidence = min(conf_magnitude + consensus_bonus, 1.0)

    top_bull = sorted([v for v in votes if v["score"] > 0], key=lambda x: -x["weight"])[:3]
    top_bear = sorted([v for v in votes if v["score"] < 0], key=lambda x: -x["weight"])[:3]

    reasons = []
    if action in ("buy", "strong buy"):
        reasons.append(f"{bullish_count}/{total_votes} analysts bullish")
        for v in top_bull:
            name = v["agent"].replace("_agent", "").replace("_", " ").title()
            reasons.append(f"{name}: {v['signal']} ({v['confidence']:.0%})")
        if bearish_count > 0:
            reasons.append(f"Caution: {bearish_count} analysts bearish")
    elif action in ("sell", "strong sell"):
        reasons.append(f"{bearish_count}/{total_votes} analysts bearish")
        for v in top_bear:
            name = v["agent"].replace("_agent", "").replace("_", " ").title()
            reasons.append(f"{name}: {v['signal']} ({v['confidence']:.0%})")
        if bullish_count > 0:
            reasons.append(f"Note: {bullish_count} analysts still bullish")
    else:
        reasons.append(f"Mixed signals: {bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral")
        if top_bull:
            reasons.append(f"Bull case: {top_bull[0]['agent'].replace('_agent','').replace('_',' ').title()}")
        if top_bear:
            reasons.append(f"Bear case: {top_bear[0]['agent'].replace('_agent','').replace('_',' ').title()}")

    return {
        "action": action,
        "confidence": round(confidence, 3),
        "reasoning": ". ".join(reasons),
        "score": round(normalized_score, 4),
        "signal_breakdown": {
            "bullish": bullish_count,
            "bearish": bearish_count,
            "neutral": neutral_count,
            "total": total_votes,
            "bullish_pct": round(bullish_pct * 100, 1),
            "bearish_pct": round(bearish_pct * 100, 1),
        },
    }


def run_meta_analysis(
    analyst_signals: dict[str, dict[str, Any]],
    tickers: list[str],
) -> dict[str, dict]:
    """Run meta-analysis on all tickers. Returns {ticker: verdict_dict}."""
    verdicts = {}
    for ticker in tickers:
        verdict = aggregate_signals(analyst_signals, ticker)
        verdicts[ticker] = verdict
    return verdicts
