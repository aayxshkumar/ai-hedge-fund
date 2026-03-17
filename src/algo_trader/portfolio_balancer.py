"""Portfolio Balancer — Analyses market-cap distribution and recommends rebalancing.

Classifies holdings by market cap, computes allocation %, recommends an ideal
ratio, and uses the LLM to suggest 5 short-term additions and stocks to trim.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
REBALANCE_FILE = Path(__file__).resolve().parent.parent.parent / "outputs" / "rebalance_analysis.json"

CAP_THRESHOLDS = {
    "large": 50_000,   # > ₹50K Cr
    "mid": 10_000,     # ₹10K-50K Cr
    "small": 0,        # < ₹10K Cr
}

PROFILE_RATIOS = {
    "conservative": {"large": 60, "mid": 30, "small": 10},
    "balanced":     {"large": 50, "mid": 30, "small": 20},
    "aggressive":   {"large": 30, "mid": 30, "small": 40},
}


def _fetch_market_cap(ticker: str) -> tuple[str, float | None]:
    """Return (ticker, market_cap_in_crores) or None.

    yfinance reports marketCap in the stock's trading currency.
    For .NS/.BO tickers the value is already INR; for US tickers
    we apply a rough USD→INR factor so cap classification stays valid.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        mc = info.get("marketCap")
        if mc and mc > 0:
            currency = (info.get("currency") or "INR").upper()
            if currency != "INR":
                mc = mc * 83  # approximate USD/EUR→INR conversion
            return ticker, mc / 1e7  # Convert to crores
        return ticker, None
    except Exception as exc:
        log.debug("Market cap fetch failed for %s: %s", ticker, exc)
        return ticker, None


def classify_cap(market_cap_cr: float) -> str:
    if market_cap_cr >= CAP_THRESHOLDS["large"]:
        return "large"
    elif market_cap_cr >= CAP_THRESHOLDS["mid"]:
        return "mid"
    return "small"


def analyse_portfolio_balance(
    holdings: list[dict],
    review_verdicts: dict | None = None,
    penny_picks: list[dict] | None = None,
) -> dict:
    """Analyse current portfolio market-cap distribution and produce rebalance suggestions.

    Parameters
    ----------
    holdings : list[dict]
        Each dict has at least ``ticker``, ``quantity``, ``last_price``.
    review_verdicts : dict | None
        Meta Analyst verdicts keyed by ticker (from portfolio review).
    penny_picks : list[dict] | None
        Top penny scanner results for short-term addition candidates.

    Returns
    -------
    dict with current_allocation, recommended, suggestions, short_term_picks
    """
    if not holdings:
        return {
            "timestamp": _now_ist(),
            "current_allocation": {},
            "recommended_profile": "balanced",
            "recommended_allocation": PROFILE_RATIOS["balanced"],
            "holdings_detail": [],
            "suggestions": [],
            "short_term_picks": [],
            "portfolio_value": 0,
        }

    # Fetch market caps in parallel
    tickers = [h.get("ticker", h.get("tradingsymbol", "")) for h in holdings]
    market_caps: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_market_cap, t): t for t in tickers}
        for f in as_completed(futures):
            t, mc = f.result()
            market_caps[t] = mc

    # Classify and compute allocation
    detail = []
    total_value = 0.0
    cap_values = {"large": 0.0, "mid": 0.0, "small": 0.0}

    for h in holdings:
        ticker = h.get("ticker", h.get("tradingsymbol", ""))
        qty = h.get("quantity", 0)
        price = h.get("last_price", h.get("ltp", 0))
        value = qty * price
        total_value += value

        mc = market_caps.get(ticker)
        cap_cat = classify_cap(mc) if mc else "small"
        cap_values[cap_cat] += value

        verdict = (review_verdicts or {}).get(ticker, {})

        detail.append({
            "ticker": ticker,
            "quantity": qty,
            "price": round(price, 2),
            "value": round(value, 2),
            "market_cap_cr": round(mc, 0) if mc else None,
            "cap_category": cap_cat,
            "verdict_action": verdict.get("action", ""),
            "verdict_score": verdict.get("score", 0),
        })

    current_alloc = {}
    for cat in ("large", "mid", "small"):
        pct = (cap_values[cat] / total_value * 100) if total_value > 0 else 0
        current_alloc[cat] = round(pct, 1)

    # Determine best profile
    best_profile = _recommend_profile(current_alloc)
    recommended = PROFILE_RATIOS[best_profile]

    # Generate suggestions
    suggestions = _generate_suggestions(detail, current_alloc, recommended, review_verdicts)

    # Short-term picks (from penny scanner + high-conviction buys)
    short_term_picks = _pick_short_term(penny_picks, review_verdicts, detail)

    result = {
        "timestamp": _now_ist(),
        "portfolio_value": round(total_value, 2),
        "current_allocation": current_alloc,
        "cap_values": {k: round(v, 2) for k, v in cap_values.items()},
        "recommended_profile": best_profile,
        "recommended_allocation": recommended,
        "holdings_detail": sorted(detail, key=lambda x: -(x["value"])),
        "suggestions": suggestions,
        "short_term_picks": short_term_picks,
    }

    # Persist (atomic write)
    import os as _os
    REBALANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REBALANCE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(result, f, indent=2, default=str)
    _os.replace(str(tmp), str(REBALANCE_FILE))

    return result


def _now_ist() -> str:
    return datetime.now(IST).isoformat()


def _recommend_profile(current: dict) -> str:
    """Pick the profile whose allocation is closest to current (least disruption)."""
    best_score = float("inf")
    best = "balanced"
    for name, target in PROFILE_RATIOS.items():
        diff = sum(abs(current.get(k, 0) - target[k]) for k in target)
        if diff < best_score:
            best_score = diff
            best = name
    return best


def _generate_suggestions(
    detail: list[dict],
    current: dict,
    target: dict,
    verdicts: dict | None,
) -> list[dict]:
    """Generate rebalancing action items."""
    suggestions = []

    for cat in ("large", "mid", "small"):
        diff = current.get(cat, 0) - target[cat]
        if abs(diff) < 3:
            continue
        if diff > 0:
            # Overweight — find candidates to trim
            cat_stocks = [d for d in detail if d["cap_category"] == cat]
            cat_stocks.sort(key=lambda x: x.get("verdict_score", 0))
            for s in cat_stocks[:2]:
                v = (verdicts or {}).get(s["ticker"], {})
                if v.get("action", "").lower() in ("sell", "strong sell", "hold"):
                    suggestions.append({
                        "action": "trim",
                        "ticker": s["ticker"],
                        "reason": f"{cat.title()}-cap overweight by {diff:.0f}%. Verdict: {v.get('action', 'hold')}",
                        "category": cat,
                    })
        else:
            suggestions.append({
                "action": "add",
                "ticker": "",
                "reason": f"{cat.title()}-cap underweight by {abs(diff):.0f}%. Consider adding {cat}-cap stocks.",
                "category": cat,
            })

    return suggestions


def _pick_short_term(
    penny_picks: list[dict] | None,
    verdicts: dict | None,
    detail: list[dict],
) -> list[dict]:
    """Select 5 stocks for short-term addition to the portfolio."""
    picks: list[dict] = []
    existing_tickers = {d["ticker"] for d in detail}

    # From penny scanner — top momentum picks not already held
    for p in (penny_picks or [])[:5]:
        ticker = p.get("ticker", "")
        if ticker and ticker not in existing_tickers:
            picks.append({
                "ticker": ticker,
                "price": p.get("last_close", 0),
                "target_price": p.get("target_price", 0),
                "stop_loss": p.get("stop_loss", 0),
                "time_horizon": p.get("time_horizon", "short_1m"),
                "score": p.get("score", 0),
                "source": "penny_scanner",
                "reasoning": p.get("reasoning", ""),
            })

    # From review verdicts — strong buys not already held
    for ticker, v in sorted(
        (verdicts or {}).items(),
        key=lambda x: -x[1].get("score", 0),
    ):
        if len(picks) >= 5:
            break
        if ticker in existing_tickers:
            continue
        if v.get("action", "").lower() in ("buy", "strong buy"):
            target_sig = v.get("analyst_signals", {}).get("target_analyst_agent", {})
            picks.append({
                "ticker": ticker,
                "price": 0,
                "target_price": target_sig.get("target_price", 0),
                "stop_loss": target_sig.get("stop_loss", 0),
                "time_horizon": target_sig.get("time_horizon", "short_1m"),
                "score": v.get("score", 0),
                "source": "meta_analyst",
                "reasoning": v.get("reasoning", "")[:200],
            })

    return picks[:5]


def load_rebalance_analysis() -> dict:
    """Load the latest rebalance analysis from cache."""
    if not REBALANCE_FILE.exists():
        return {}
    try:
        with open(REBALANCE_FILE) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to load rebalance analysis: %s", exc)
        return {}
