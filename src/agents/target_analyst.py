"""Target Analyst Agent — Produces price targets, stop-losses, and time horizons.

For each ticker the agent:
1. Fetches 90-day OHLCV from yfinance (fallback: Financial Datasets API).
2. Computes technical levels: support/resistance via pivot points, ATR bands,
   Fibonacci retracement, 52-week range, and key EMAs.
3. Gathers analyst consensus targets from yfinance when available.
4. Asks the LLM to synthesise a TargetSignal with target_price, stop_loss,
   time_horizon, risk/reward ratio, and directional signal.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress

log = logging.getLogger(__name__)


class TargetSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    target_price: float
    stop_loss: float
    time_horizon: Literal["intraday", "swing_1w", "short_1m", "medium_3m", "long_6m+"]
    risk_reward_ratio: float
    reasoning: str


def _fetch_price_data(ticker: str) -> pd.DataFrame | None:
    """Fetch 180-day OHLCV data via yfinance (thread-safe)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period="180d")
        if df is None or len(df) < 30:
            return None
        df.columns = [str(c).strip().lower() for c in df.columns]
        return df
    except Exception as e:
        log.debug("yfinance fetch failed for %s: %s", ticker, e)
        return None


def _compute_levels(df: pd.DataFrame) -> dict:
    """Compute support/resistance, Fibonacci, ATR, and key EMAs."""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    last_close = float(close.iloc[-1])
    high_52w = float(high.tail(252).max()) if len(high) > 20 else float(high.max())
    low_52w = float(low.tail(252).min()) if len(low) > 20 else float(low.min())

    # Pivot points (classic)
    h = float(high.iloc[-1])
    l = float(low.iloc[-1])
    pivot = (h + l + last_close) / 3
    r1 = 2 * pivot - l
    s1 = 2 * pivot - h
    r2 = pivot + (h - l)
    s2 = pivot - (h - l)

    # ATR (14-period)
    tr = pd.concat([
        (high - low).rename("tr1"),
        (high - close.shift(1)).abs().rename("tr2"),
        (low - close.shift(1)).abs().rename("tr3"),
    ], axis=1).max(axis=1)
    atr_14_raw = tr.rolling(14).mean().iloc[-1]
    atr_14 = float(atr_14_raw) if not np.isnan(atr_14_raw) else float(last_close * 0.03)

    # Fibonacci retracements from recent swing
    swing_high = float(high.tail(30).max())
    swing_low = float(low.tail(30).min())
    fib_range = swing_high - swing_low
    fib_382 = swing_high - fib_range * 0.382
    fib_500 = swing_high - fib_range * 0.5
    fib_618 = swing_high - fib_range * 0.618

    # EMAs
    ema_20 = float(close.ewm(span=20).mean().iloc[-1])
    ema_50 = float(close.ewm(span=50).mean().iloc[-1])
    ema_200 = float(close.ewm(span=200).mean().iloc[-1]) if len(close) >= 200 else None

    # RSI (Wilder's EMA)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, min_periods=14).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_raw = (100 - (100 / (1 + rs))).iloc[-1]
    rsi = float(rsi_raw) if not np.isnan(rsi_raw) else 50.0

    # Momentum (5d, 20d)
    mom_5d = float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if len(close) > 5 else 0
    mom_20d = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if len(close) > 20 else 0

    return {
        "last_close": round(last_close, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "pivot": round(pivot, 2),
        "resistance_1": round(r1, 2),
        "resistance_2": round(r2, 2),
        "support_1": round(s1, 2),
        "support_2": round(s2, 2),
        "atr_14": round(atr_14, 2),
        "atr_upper": round(last_close + 2 * atr_14, 2),
        "atr_lower": round(last_close - 1.5 * atr_14, 2),
        "fib_382": round(fib_382, 2),
        "fib_500": round(fib_500, 2),
        "fib_618": round(fib_618, 2),
        "swing_high_30d": round(swing_high, 2),
        "swing_low_30d": round(swing_low, 2),
        "ema_20": round(ema_20, 2),
        "ema_50": round(ema_50, 2),
        "ema_200": round(ema_200, 2) if ema_200 else None,
        "rsi": round(rsi, 1),
        "momentum_5d": round(mom_5d, 2),
        "momentum_20d": round(mom_20d, 2),
    }


def _fetch_analyst_targets(ticker: str) -> dict | None:
    """Fetch yfinance analyst consensus targets."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        if target_mean:
            return {
                "consensus_target": target_mean,
                "target_high": target_high,
                "target_low": target_low,
                "recommendation": info.get("recommendationKey", ""),
                "num_analysts": info.get("numberOfAnalystOpinions", 0),
            }
    except Exception:
        pass
    return None


def _generate_target_signal(
    ticker: str,
    levels: dict,
    analyst_targets: dict | None,
    state: AgentState,
    agent_id: str,
) -> TargetSignal:
    """Use LLM to produce a TargetSignal from computed levels."""
    context_parts = [f"Technical Levels:\n{json.dumps(levels, indent=2)}"]
    if analyst_targets:
        context_parts.append(f"Wall Street / Analyst Consensus:\n{json.dumps(analyst_targets, indent=2)}")

    template = ChatPromptTemplate.from_messages([
        ("system", """You are a Target Price Analyst. Your job is to set precise, actionable price targets, stop-losses, and time horizons for stocks.

Use the technical levels (support, resistance, Fibonacci, ATR bands, EMAs, pivot points) and analyst consensus (if available) to determine:

1. **target_price** — the realistic upside target if bullish, or downside target if bearish
2. **stop_loss** — a logical invalidation level (below support for longs, above resistance for shorts)
3. **time_horizon** — one of: intraday, swing_1w (1 week swing), short_1m (1 month), medium_3m (3 months), long_6m+ (6+ months)
4. **risk_reward_ratio** — target profit / potential loss

Rules:
- For bullish: target_price > current price, stop_loss < current price
- For bearish: target_price < current price, stop_loss > current price
- For neutral: set target near resistance and stop loss near support
- Time horizon should match the move size: small moves = shorter horizon, large moves = longer
- Target must be between support_2 and resistance_2 (or analyst targets) — don't overshoot
- Stop loss should be near a support level (for long) or resistance (for short), typically 1-1.5 ATR away
- Risk/reward ratio should be >= 1.5 for buy signals, otherwise signal should be neutral

Return JSON exactly in this format:
{{
  "signal": "bullish" or "bearish" or "neutral",
  "confidence": float (0-100),
  "target_price": float,
  "stop_loss": float,
  "time_horizon": "intraday" or "swing_1w" or "short_1m" or "medium_3m" or "long_6m+",
  "risk_reward_ratio": float,
  "reasoning": "string"
}}"""),
        ("human", """Analyze {ticker} (current price: {price}) and produce target/stop-loss/time-horizon:

{context}

Return the JSON signal now."""),
    ])

    prompt = template.invoke({
        "ticker": ticker,
        "price": levels["last_close"],
        "context": "\n\n".join(context_parts),
    })

    def default_factory():
        return TargetSignal(
            signal="neutral", confidence=0, target_price=levels["last_close"],
            stop_loss=levels.get("support_1", levels["last_close"] * 0.95),
            time_horizon="short_1m", risk_reward_ratio=1.0,
            reasoning="Unable to generate target analysis; defaulting to neutral.",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=TargetSignal,
        agent_name=agent_id,
        state=state,
        default_factory=default_factory,
    )


def target_analyst_agent(state: AgentState, agent_id: str = "target_analyst_agent"):
    """Produces price targets, stop-losses, and time horizons for each ticker."""
    data = state["data"]
    tickers = data["tickers"]

    target_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching price data")
        df = _fetch_price_data(ticker)
        if df is None or df.empty:
            progress.update_status(agent_id, ticker, "No data — skipping")
            target_analysis[ticker] = {
                "signal": "neutral", "confidence": 0,
                "target_price": 0, "stop_loss": 0,
                "time_horizon": "short_1m", "risk_reward_ratio": 0,
                "reasoning": "Insufficient price data.",
            }
            continue

        progress.update_status(agent_id, ticker, "Computing technical levels")
        levels = _compute_levels(df)

        progress.update_status(agent_id, ticker, "Fetching analyst targets")
        analyst_targets = _fetch_analyst_targets(ticker)

        progress.update_status(agent_id, ticker, "Generating target signal")
        signal = _generate_target_signal(ticker, levels, analyst_targets, state, agent_id)

        # Validate and clamp LLM-generated targets to physical bounds
        price = levels["last_close"]
        if signal.signal == "bullish":
            if signal.target_price <= price:
                signal.target_price = levels.get("resistance_1", price * 1.05)
            if signal.stop_loss >= price:
                signal.stop_loss = levels.get("support_1", price * 0.95)
        elif signal.signal == "bearish":
            if signal.target_price >= price:
                signal.target_price = levels.get("support_1", price * 0.95)
            if signal.stop_loss <= price:
                signal.stop_loss = levels.get("resistance_1", price * 1.05)

        signal.target_price = max(signal.target_price, price * 0.3)
        signal.target_price = min(signal.target_price, price * 3.0)
        signal.stop_loss = max(signal.stop_loss, price * 0.3)
        signal.stop_loss = min(signal.stop_loss, price * 3.0)

        target_analysis[ticker] = {
            "signal": signal.signal,
            "confidence": signal.confidence,
            "target_price": signal.target_price,
            "stop_loss": signal.stop_loss,
            "time_horizon": signal.time_horizon,
            "risk_reward_ratio": signal.risk_reward_ratio,
            "reasoning": signal.reasoning,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=signal.reasoning)

    message = HumanMessage(content=json.dumps(target_analysis), name=agent_id)

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(target_analysis, "Target Analyst Agent")

    state["data"]["analyst_signals"][agent_id] = target_analysis
    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}
