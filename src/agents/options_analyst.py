"""Options Flow Analyst — Analyzes options chain data for trading signals.

Examines implied volatility surfaces, put/call ratios, max pain, open interest
concentration, and unusual activity to generate signals. Works with both real
yfinance options data and synthetic chain generation as fallback.

For Indian stocks (.NS suffix), generates synthetic chains using Black-Scholes
since yfinance options data is limited for NSE/BSE.
"""

from __future__ import annotations

import json
import math
import datetime
import logging
from collections import defaultdict

import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.progress import progress

log = logging.getLogger(__name__)


def _to_native(obj):
    """Recursively convert numpy types to Python native for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def options_analyst_agent(state: AgentState, agent_id: str = "options_analyst_agent"):
    """Analyze options chain data for each ticker and produce trading signals."""
    data = state["data"]
    tickers = data["tickers"]
    end_date = data["end_date"]

    options_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching options data")
        try:
            result = _analyze_ticker_options(ticker, end_date)
        except Exception as e:
            log.warning("Options analysis failed for %s: %s", ticker, e)
            result = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": f"Options data unavailable: {str(e)[:80]}",
            }

        options_analysis[ticker] = _to_native(result)
        progress.update_status(agent_id, ticker, "Done", analysis=result.get("reasoning", ""))

    message = HumanMessage(content=json.dumps(options_analysis, default=str), name=agent_id)

    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(options_analysis, agent_id)

    state["data"]["analyst_signals"][agent_id] = options_analysis
    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def _analyze_ticker_options(ticker: str, end_date: str) -> dict:
    """Full options analysis pipeline for a single ticker."""
    is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

    chain_data = _fetch_options_data(ticker, is_indian, end_date)
    if chain_data is None:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": "No options data available for analysis.",
        }

    spot = chain_data["spot_price"]
    calls_df = chain_data["calls"]
    puts_df = chain_data["puts"]

    signals = []
    details = {}

    pcr = _compute_pcr(calls_df, puts_df)
    details["put_call_ratio"] = round(pcr, 3)
    pcr_signal, pcr_conf, pcr_reason = _interpret_pcr(pcr)
    signals.append(("pcr", pcr_signal, pcr_conf, pcr_reason))

    iv_analysis = _analyze_iv_surface(calls_df, puts_df, spot)
    details["iv_analysis"] = iv_analysis
    iv_signal, iv_conf, iv_reason = _interpret_iv(iv_analysis)
    signals.append(("iv", iv_signal, iv_conf, iv_reason))

    max_pain_price = _compute_max_pain(calls_df, puts_df, spot)
    details["max_pain"] = round(max_pain_price, 2)
    details["max_pain_distance_pct"] = round((max_pain_price - spot) / spot * 100, 2) if spot > 0 else 0
    mp_signal, mp_conf, mp_reason = _interpret_max_pain(spot, max_pain_price)
    signals.append(("max_pain", mp_signal, mp_conf, mp_reason))

    oi_analysis = _analyze_oi_concentration(calls_df, puts_df, spot)
    details["oi_analysis"] = oi_analysis
    oi_signal, oi_conf, oi_reason = _interpret_oi(oi_analysis)
    signals.append(("oi", oi_signal, oi_conf, oi_reason))

    unusual = _detect_unusual_activity(calls_df, puts_df)
    details["unusual_activity"] = unusual
    if unusual.get("detected"):
        ua_signal = unusual["direction"]
        ua_conf = min(unusual.get("strength", 40), 80)
        signals.append(("unusual", ua_signal, ua_conf, unusual["summary"]))

    final_signal, final_conf, final_reasoning = _aggregate_options_signals(signals)

    if chain_data.get("source") == "synthetic":
        final_conf = min(final_conf, 30)
        final_reasoning = f"[Synthetic chain — low confidence] {final_reasoning}"

    return {
        "signal": final_signal,
        "confidence": final_conf,
        "reasoning": final_reasoning,
        "details": details,
    }


def _fetch_options_data(ticker: str, is_indian: bool, end_date: str) -> dict | None:
    """Fetch options chain — real data via yfinance or synthetic fallback."""
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="30d")
        if hist.empty:
            return None
        spot = float(hist["Close"].iloc[-1])

        if not is_indian:
            expirations = t.options
            if expirations:
                nearest = expirations[0]
                chain = t.option_chain(nearest)
                calls_df = chain.calls.copy()
                puts_df = chain.puts.copy()

                for df in [calls_df, puts_df]:
                    for col in ["strike", "lastPrice", "volume", "openInterest", "impliedVolatility"]:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

                return {"spot_price": spot, "calls": calls_df, "puts": puts_df, "source": "yfinance"}
    except Exception as e:
        log.debug("yfinance options fetch failed for %s: %s", ticker, e)
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="30d")
            if hist.empty:
                return None
            spot = float(hist["Close"].iloc[-1])
        except Exception:
            return None

    return _generate_synthetic_chain(ticker, spot, hist, end_date)


def _generate_synthetic_chain(ticker: str, spot: float, hist: pd.DataFrame, end_date: str) -> dict | None:
    """Generate synthetic options chain using Black-Scholes for Indian stocks."""
    try:
        from src.algo_trader.options.chain import compute_historical_volatility
        from src.algo_trader.options.pricing import black_scholes, greeks

        close_prices = hist["Close"] if "Close" in hist.columns else hist.get("close")
        if close_prices is None or len(close_prices) < 5:
            return None

        hvol = compute_historical_volatility(close_prices, window=min(20, len(close_prices) - 1))

        if spot > 10000:
            step = 100
        elif spot > 1000:
            step = 50
        elif spot > 200:
            step = 10
        elif spot > 50:
            step = 5
        else:
            step = 1

        num_strikes = 15
        T = 7 / 365.0
        r = 0.07
        base_iv = max(hvol * 1.05, 0.10)
        atm = round(spot / step) * step

        contracts_data = {"calls": [], "puts": []}
        for i in range(-num_strikes, num_strikes + 1):
            strike = atm + i * step
            if strike <= 0:
                continue
            moneyness = spot / strike
            for opt_type in ("call", "put"):
                skew_m = moneyness if opt_type == "call" else 1 / moneyness
                iv = base_iv + 0.0005 * (skew_m - 1.0) ** 2 + (0.02 if opt_type == "put" and skew_m < 0.97 else 0)
                bs = black_scholes(spot, strike, T, r, iv)
                premium = bs.call if opt_type == "call" else bs.put
                g = greeks(spot, strike, T, r, iv, opt_type)
                row = {
                    "strike": strike,
                    "lastPrice": round(premium, 2),
                    "volume": max(10, int(500 * math.exp(-2 * abs(moneyness - 1)))),
                    "openInterest": max(100, int(5000 * math.exp(-2 * abs(moneyness - 1)))),
                    "impliedVolatility": round(iv, 4),
                    "delta": round(g.delta, 4),
                    "gamma": round(g.gamma, 6),
                    "theta": round(g.theta, 4),
                    "vega": round(g.vega, 4),
                }
                contracts_data["calls" if opt_type == "call" else "puts"].append(row)

        calls_df = pd.DataFrame(contracts_data["calls"]) if contracts_data["calls"] else pd.DataFrame()
        puts_df = pd.DataFrame(contracts_data["puts"]) if contracts_data["puts"] else pd.DataFrame()

        return {"spot_price": spot, "calls": calls_df, "puts": puts_df, "source": "synthetic"}

    except Exception as e:
        log.warning("Synthetic chain generation failed for %s: %s", ticker, e)
        return None


def _compute_pcr(calls_df: pd.DataFrame, puts_df: pd.DataFrame) -> float:
    """Put/Call ratio based on open interest."""
    call_oi = calls_df["openInterest"].sum() if "openInterest" in calls_df.columns else 0
    put_oi = puts_df["openInterest"].sum() if "openInterest" in puts_df.columns else 0
    if call_oi == 0:
        return 1.0
    return put_oi / call_oi


def _interpret_pcr(pcr: float) -> tuple[str, int, str]:
    if pcr > 1.5:
        return "bullish", 65, f"High PCR {pcr:.2f} — extreme put buying signals bearish exhaustion (contrarian bullish)"
    elif pcr > 1.2:
        return "bullish", 45, f"Elevated PCR {pcr:.2f} — hedging activity suggests cautious bullish"
    elif pcr < 0.5:
        return "bearish", 65, f"Low PCR {pcr:.2f} — excessive call buying signals complacency (contrarian bearish)"
    elif pcr < 0.7:
        return "bearish", 40, f"Below-average PCR {pcr:.2f} — mild overconfidence"
    else:
        return "neutral", 20, f"Normal PCR {pcr:.2f}"


def _analyze_iv_surface(calls_df: pd.DataFrame, puts_df: pd.DataFrame, spot: float) -> dict:
    """Analyze implied volatility patterns."""
    result = {"atm_iv": 0, "iv_skew": 0, "iv_rank": "N/A", "avg_call_iv": 0, "avg_put_iv": 0}

    if "impliedVolatility" not in calls_df.columns or "strike" not in calls_df.columns:
        return result

    calls_iv = calls_df[calls_df["impliedVolatility"] > 0]
    puts_iv = puts_df[puts_df["impliedVolatility"] > 0] if "impliedVolatility" in puts_df.columns else pd.DataFrame()

    if calls_iv.empty:
        return result

    atm_mask = (calls_iv["strike"] - spot).abs() < spot * 0.03
    atm_calls = calls_iv[atm_mask]
    atm_iv = float(atm_calls["impliedVolatility"].mean()) if not atm_calls.empty else float(calls_iv["impliedVolatility"].median())

    otm_puts = puts_iv[puts_iv["strike"] < spot * 0.95] if not puts_iv.empty else pd.DataFrame()
    otm_calls = calls_iv[calls_iv["strike"] > spot * 1.05]

    put_iv_avg = float(otm_puts["impliedVolatility"].mean()) if not otm_puts.empty else atm_iv
    call_iv_avg = float(otm_calls["impliedVolatility"].mean()) if not otm_calls.empty else atm_iv
    skew = put_iv_avg - call_iv_avg

    return {
        "atm_iv": round(atm_iv, 4),
        "iv_skew": round(skew, 4),
        "avg_call_iv": round(float(calls_iv["impliedVolatility"].mean()), 4),
        "avg_put_iv": round(float(puts_iv["impliedVolatility"].mean()), 4) if not puts_iv.empty else 0,
    }


def _interpret_iv(iv_data: dict) -> tuple[str, int, str]:
    atm_iv = iv_data.get("atm_iv", 0)
    skew = iv_data.get("iv_skew", 0)

    if atm_iv > 0.5:
        base = "bearish"
        conf = 55
        reason = f"Very high ATM IV {atm_iv:.1%} — market expects large move, elevated fear"
    elif atm_iv > 0.35:
        base = "neutral"
        conf = 30
        reason = f"Elevated ATM IV {atm_iv:.1%} — above-average uncertainty"
    elif atm_iv < 0.15:
        base = "neutral"
        conf = 25
        reason = f"Low ATM IV {atm_iv:.1%} — complacency, potential for vol expansion"
    else:
        base = "neutral"
        conf = 15
        reason = f"Normal ATM IV {atm_iv:.1%}"

    if skew > 0.05:
        base = "bearish" if base == "neutral" else base
        conf += 10
        reason += f". Put skew {skew:.3f} — downside protection demand"
    elif skew < -0.03:
        if base == "neutral":
            base = "bullish"
        conf += 10
        reason += f". Call skew {skew:.3f} — upside demand"

    return base, min(conf, 80), reason


def _compute_max_pain(calls_df: pd.DataFrame, puts_df: pd.DataFrame, spot: float) -> float:
    """Max pain = strike where total loss to option holders is maximized."""
    if "strike" not in calls_df.columns or "openInterest" not in calls_df.columns:
        return spot

    all_strikes = sorted(set(
        list(calls_df["strike"].unique()) + list(puts_df["strike"].unique())
    ))

    if not all_strikes:
        return spot

    min_pain = float("inf")
    max_pain_strike = spot

    for strike in all_strikes:
        s = float(strike)
        call_loss = float(calls_df.apply(
            lambda r, s=s: max(0, s - float(r["strike"])) * float(r["openInterest"]), axis=1
        ).sum()) if not calls_df.empty else 0.0

        put_loss = float(puts_df.apply(
            lambda r, s=s: max(0, float(r["strike"]) - s) * float(r["openInterest"]), axis=1
        ).sum()) if not puts_df.empty else 0.0

        total_pain = call_loss + put_loss
        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = s

    return max_pain_strike


def _interpret_max_pain(spot: float, max_pain: float) -> tuple[str, int, str]:
    if spot == 0:
        return "neutral", 0, "No spot price"

    distance_pct = (max_pain - spot) / spot * 100

    if distance_pct > 3:
        return "bullish", 50, f"Max pain ₹{max_pain:,.0f} is {distance_pct:+.1f}% above spot — gravitational pull upward"
    elif distance_pct < -3:
        return "bearish", 50, f"Max pain ₹{max_pain:,.0f} is {distance_pct:+.1f}% below spot — gravitational pull downward"
    else:
        return "neutral", 25, f"Max pain ₹{max_pain:,.0f} near spot ({distance_pct:+.1f}%) — pinning expected"


def _analyze_oi_concentration(calls_df: pd.DataFrame, puts_df: pd.DataFrame, spot: float) -> dict:
    """Find where open interest is concentrated to identify support/resistance."""
    result = {"call_wall": 0, "put_wall": 0, "call_wall_oi": 0, "put_wall_oi": 0}

    if calls_df.empty or "openInterest" not in calls_df.columns:
        return result

    otm_calls = calls_df[calls_df["strike"] > spot]
    otm_puts = puts_df[puts_df["strike"] < spot] if not puts_df.empty else pd.DataFrame()

    if not otm_calls.empty and otm_calls["openInterest"].sum() > 0:
        max_call_idx = otm_calls["openInterest"].idxmax()
        result["call_wall"] = round(float(otm_calls.loc[max_call_idx, "strike"]), 2)
        result["call_wall_oi"] = int(float(otm_calls.loc[max_call_idx, "openInterest"]))

    if not otm_puts.empty and otm_puts["openInterest"].sum() > 0:
        max_put_idx = otm_puts["openInterest"].idxmax()
        result["put_wall"] = round(float(otm_puts.loc[max_put_idx, "strike"]), 2)
        result["put_wall_oi"] = int(float(otm_puts.loc[max_put_idx, "openInterest"]))

    return result


def _interpret_oi(oi_data: dict) -> tuple[str, int, str]:
    call_wall = oi_data.get("call_wall", 0)
    put_wall = oi_data.get("put_wall", 0)
    call_oi = oi_data.get("call_wall_oi", 0)
    put_oi = oi_data.get("put_wall_oi", 0)

    if call_wall == 0 and put_wall == 0:
        return "neutral", 0, "No OI concentration data"

    if put_oi > call_oi * 1.5:
        return "bullish", 45, f"Put wall OI ({put_oi:,}) >> Call wall OI ({call_oi:,}) — strong support at ₹{put_wall:,.0f}"
    elif call_oi > put_oi * 1.5:
        return "bearish", 45, f"Call wall OI ({call_oi:,}) >> Put wall OI ({put_oi:,}) — strong resistance at ₹{call_wall:,.0f}"
    else:
        return "neutral", 20, f"Balanced OI — support ₹{put_wall:,.0f}, resistance ₹{call_wall:,.0f}"


def _detect_unusual_activity(calls_df: pd.DataFrame, puts_df: pd.DataFrame) -> dict:
    """Detect unusual options activity (volume >> open interest)."""
    result = {"detected": False, "direction": "neutral", "strength": 0, "summary": ""}

    for label, df in [("call", calls_df), ("put", puts_df)]:
        if df.empty or "volume" not in df.columns or "openInterest" not in df.columns:
            continue
        active = df[(df["openInterest"] > 0) & (df["volume"] > 0)]
        if active.empty:
            continue

        ratios = active["volume"] / active["openInterest"].clip(lower=1)
        unusual_mask = ratios > 3.0
        unusual_rows = active[unusual_mask]

        if len(unusual_rows) >= 2:
            total_unusual_vol = unusual_rows["volume"].sum()
            result["detected"] = True
            direction = "bullish" if label == "call" else "bearish"
            result["direction"] = direction
            result["strength"] = min(int(len(unusual_rows) * 15), 70)
            result["summary"] = (
                f"Unusual {label} activity: {len(unusual_rows)} strikes with vol/OI > 3x "
                f"(total volume: {total_unusual_vol:,})"
            )
            break

    return result


def _aggregate_options_signals(
    signals: list[tuple[str, str, int, str]],
) -> tuple[str, int, str]:
    """Aggregate multiple options sub-signals into final verdict."""
    if not signals:
        return "neutral", 0, "No options signals available"

    score = 0
    total_weight = 0
    reasons = []

    WEIGHTS = {"pcr": 1.2, "iv": 1.0, "max_pain": 1.3, "oi": 1.1, "unusual": 1.5}
    SIGNAL_MAP = {"bullish": 1, "bearish": -1, "neutral": 0}

    for name, sig, conf, reason in signals:
        w = WEIGHTS.get(name, 1.0)
        s = SIGNAL_MAP.get(sig, 0)
        effective_conf = max(conf, 10) / 100.0
        score += s * w * effective_conf
        total_weight += w * effective_conf
        reasons.append(f"{name.upper()}: {reason}")

    if total_weight == 0:
        return "neutral", 0, "No weighted options signals"

    normalized = score / total_weight
    confidence = int(min(abs(normalized) * 100, 85))

    if normalized > 0.25:
        action = "bullish"
    elif normalized < -0.25:
        action = "bearish"
    else:
        action = "neutral"

    top_reasons = reasons[:3]
    return action, confidence, ". ".join(top_reasons)
