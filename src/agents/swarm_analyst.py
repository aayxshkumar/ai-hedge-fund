"""Swarm Debate Analyst — MiroFish-inspired multi-persona consensus builder.

Instead of simply averaging signals, this agent creates market participant
personas that "debate" the existing analyst signals from their own perspective.
Each persona weighs signals differently, producing a richer consensus than
any single aggregation method.

Inspired by MiroFish's swarm intelligence simulation where emergent behavior
from diverse agent interactions produces more reliable predictions than
individual agents alone.
"""

from __future__ import annotations

import json
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing_extensions import Literal

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress


class SwarmVerdict(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(description="Confidence 0-100")
    reasoning: str = Field(description="Consensus reasoning from the swarm debate")


PERSONAS = [
    {
        "name": "Institutional Fund Manager",
        "bias": "risk-adjusted returns",
        "focus": "fundamentals_analyst_agent, valuation_analyst_agent, growth_analyst_agent, risk metrics",
        "instruction": (
            "You manage a large institutional fund. Prioritize risk-adjusted returns, "
            "macro alignment, and portfolio impact. Weight fundamentals and valuation heavily. "
            "Discard noise from short-term technical signals."
        ),
    },
    {
        "name": "Quant Trader",
        "bias": "statistical edge",
        "focus": "technical_analyst_agent, momentum, mean reversion, volatility",
        "instruction": (
            "You are a quantitative trader. Focus exclusively on technical signals, "
            "momentum scores, and statistical patterns. Ignore subjective opinions from "
            "persona-based analysts unless they align with quantitative evidence."
        ),
    },
    {
        "name": "Contrarian Hedge Fund PM",
        "bias": "disagreement = opportunity",
        "focus": "michael_burry_agent, bill_ackman_agent, sentiment divergence",
        "instruction": (
            "You run a contrarian hedge fund. When the majority of analysts agree, you look "
            "for what they're missing. Pay special attention to Burry and Ackman signals. "
            "If sentiment is extreme (>80% one direction), lean the other way slightly."
        ),
    },
    {
        "name": "India Market Specialist",
        "bias": "domestic growth story",
        "focus": "rakesh_jhunjhunwala_agent, growth_analyst_agent, news_sentiment",
        "instruction": (
            "You specialize in Indian equities. Weight Rakesh Jhunjhunwala and growth "
            "analysts heavily. Consider sector rotation, FII/DII flows, and domestic "
            "consumption trends. Be aware of NSE/BSE-specific dynamics."
        ),
    },
    {
        "name": "Risk Officer",
        "bias": "capital preservation",
        "focus": "risk metrics, max drawdown, volatility, stop-loss levels",
        "instruction": (
            "You are the chief risk officer. Your job is to flag danger. If volatility "
            "is high, if drawdown risk is significant, or if analyst consensus is weak, "
            "lean bearish. Only agree to bullish if risk/reward is clearly favorable."
        ),
    },
]


def swarm_analyst_agent(state: AgentState, agent_id: str = "swarm_analyst_agent"):
    """Run MiroFish-inspired swarm debate across all tickers using 5 market participant personas."""
    data = state["data"]
    tickers = data["tickers"]
    existing_signals = data.get("analyst_signals", {})

    swarm_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Gathering analyst signals for swarm debate")

        ticker_signals = {}
        for agent_name, per_ticker in existing_signals.items():
            if agent_name == agent_id:
                continue
            if isinstance(per_ticker, dict) and ticker in per_ticker:
                raw = per_ticker[ticker]
                if isinstance(raw, dict):
                    ticker_signals[agent_name] = {
                        "signal": raw.get("signal", "neutral"),
                        "confidence": raw.get("confidence", 0),
                        "reasoning": str(raw.get("reasoning", ""))[:150],
                    }

        if not ticker_signals:
            swarm_analysis[ticker] = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": "No prior analyst signals available for swarm debate.",
            }
            progress.update_status(agent_id, ticker, "Done (no signals)")
            continue

        bull = sum(1 for s in ticker_signals.values() if s["signal"] in ("bullish", "buy", "strong_buy", "long"))
        bear = sum(1 for s in ticker_signals.values() if s["signal"] in ("bearish", "sell", "strong_sell", "short"))
        neut = len(ticker_signals) - bull - bear

        signals_summary = json.dumps(ticker_signals, separators=(",", ":"), ensure_ascii=False)
        distribution = f"Distribution: {bull} bullish, {bear} bearish, {neut} neutral out of {len(ticker_signals)} analysts"

        persona_briefs = "\n".join(
            f"- {p['name']} ({p['bias']}): {p['instruction']}"
            for p in PERSONAS
        )

        progress.update_status(agent_id, ticker, "Running swarm debate (5 personas)")

        result = _run_swarm_debate(
            ticker=ticker,
            signals_summary=signals_summary,
            distribution=distribution,
            persona_briefs=persona_briefs,
            state=state,
            agent_id=agent_id,
        )

        swarm_analysis[ticker] = {
            "signal": result.signal,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=result.reasoning)

    message = HumanMessage(content=json.dumps(swarm_analysis), name=agent_id)

    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(swarm_analysis, agent_id)

    state["data"]["analyst_signals"][agent_id] = swarm_analysis
    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def _run_swarm_debate(
    ticker: str,
    signals_summary: str,
    distribution: str,
    persona_briefs: str,
    state: AgentState,
    agent_id: str,
) -> SwarmVerdict:
    template = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a Swarm Intelligence Moderator. You oversee a debate between 5 market "
            "participant personas analyzing {ticker}. Each persona has reviewed the same set of "
            "analyst signals but interprets them through their own lens.\n\n"
            "PERSONAS:\n{persona_briefs}\n\n"
            "Your task:\n"
            "1. Consider how each persona would interpret the analyst signals\n"
            "2. Identify where they agree (strong signal) and disagree (uncertainty)\n"
            "3. Weigh the contrarian view — if 4/5 personas agree, the contrarian case matters\n"
            "4. Produce a single consensus verdict that accounts for all perspectives\n\n"
            "Signal rules:\n"
            "- Bullish: 3+ personas lean bullish, risk officer not strongly opposed\n"
            "- Bearish: 3+ personas lean bearish, or risk officer raises major red flags\n"
            "- Neutral: split opinions, or strong disagreement across personas\n\n"
            "Confidence reflects consensus strength (100 = all 5 agree, 50 = split, <30 = chaos)\n"
            "Keep reasoning under 200 characters. Return JSON only."
        ),
        (
            "human",
            "Ticker: {ticker}\n"
            "{distribution}\n\n"
            "Analyst signals:\n{signals_summary}\n\n"
            "Run the debate across all 5 personas and return the consensus:\n"
            "{{\n"
            '  "signal": "bullish" | "bearish" | "neutral",\n'
            '  "confidence": int,\n'
            '  "reasoning": "consensus summary"\n'
            "}}"
        ),
    ])

    prompt = template.invoke({
        "ticker": ticker,
        "persona_briefs": persona_briefs,
        "distribution": distribution,
        "signals_summary": signals_summary,
    })

    def default_factory():
        return SwarmVerdict(signal="neutral", confidence=30, reasoning="Swarm debate inconclusive")

    return call_llm(
        prompt=prompt,
        pydantic_model=SwarmVerdict,
        agent_name=agent_id,
        state=state,
        default_factory=default_factory,
    )
