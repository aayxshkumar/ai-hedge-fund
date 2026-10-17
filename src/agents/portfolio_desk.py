"""Portfolio desk: a cheap, batched review of held stocks.

The full review runs every persona agent on every ticker (49 stocks x 16
LLM agents ~ 800 calls), which is slow and blew through a 5-hour usage window
in one go. The desk instead asks one strong model to score each stock on five
lenses (value, growth, quality, momentum, risk) from the same fundamentals and
technicals, several tickers per call. ~10 calls for the whole book, with the
same verdict shape the Portfolio page and the review differ already consume.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Literal

from pydantic import BaseModel, Field

from src.utils.llm import call_llm

log = logging.getLogger(__name__)

BATCH_SIZE = 6
LENSES = ("value", "growth", "quality", "momentum", "risk")


class Lens(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str = Field(description="One sentence citing the numbers")


class DeskVerdict(BaseModel):
    ticker: str
    action: Literal["strong buy", "buy", "hold", "sell", "strong sell"]
    confidence: int = Field(ge=0, le=100)
    thesis: str = Field(description="2-3 sentences: why this action, for an existing holder")
    key_risk: str = Field(description="The single thing most likely to break the thesis")
    value: Lens
    growth: Lens
    quality: Lens
    momentum: Lens
    risk: Lens


class DeskBatch(BaseModel):
    verdicts: list[DeskVerdict]


SYSTEM = """You are the review desk of a long-only Indian equity fund looking at stocks the client ALREADY HOLDS.
For each stock, score five lenses from the data given (value, growth, quality, momentum, risk) and conclude with an action
for a holder: strong buy / buy (add), hold, sell (trim), strong sell (exit). Use only the numbers provided; if a field is
missing say so rather than guessing. Be concrete: cite P/E, ROE, margins, debt, RSI, trend, drawdown, position P&L.
Momentum: RSI >70 overbought, <30 oversold; price vs EMA50/EMA200 defines trend. Risk: volatility, drawdown, leverage,
position size in the book, and whether the stock is a micro/small cap with thin data. Treat a large unrealised loss as
information, not a reason to hold. This is research output, not personalised advice."""


def _fmt(v, pct=False, digits=1):
    if v is None:
        return "n/a"
    try:
        return f"{v * 100:.{digits}f}%" if pct else (f"{v:,.{digits}f}" if isinstance(v, float) else str(v))
    except Exception:
        return str(v)


def _ticker_block(t: str, data: dict) -> str:
    f = data.get("fundamentals") or {}
    tech = data.get("technical") or {}
    h = data.get("holding") or {}
    cap = f.get("market_cap")
    cap_s = f"₹{cap / 1e7:,.0f} Cr" if cap else "n/a"
    lines = [
        f"### {t}  | sector {f.get('sector') or 'n/a'} / {f.get('industry') or 'n/a'} | mcap {cap_s}",
        f"price {_fmt(data.get('current_price'))} | 52w {_fmt(f.get('fifty_two_week_low'))}-{_fmt(f.get('fifty_two_week_high'))}",
        f"valuation: P/E {_fmt(f.get('pe_ratio'))}, P/B {_fmt(f.get('pb_ratio'))}, EPS {_fmt(f.get('eps'))}, div yield {_fmt(f.get('dividend_yield'), pct=True)}",
        f"quality: ROE {_fmt(f.get('roe'), pct=True)}, op margin {_fmt(f.get('operating_margin'), pct=True)}, net margin {_fmt(f.get('profit_margin'), pct=True)}, "
        f"D/E {_fmt(f.get('debt_to_equity'))}, current ratio {_fmt(f.get('current_ratio'))}, FCF {_fmt(f.get('free_cash_flow'))}",
        f"growth: revenue growth {_fmt(f.get('revenue_growth'), pct=True)}, earnings growth {_fmt(f.get('earnings_growth'), pct=True)}, revenue {_fmt(f.get('revenue'))}",
        f"technicals: RSI {_fmt(tech.get('rsi'))}, trend {tech.get('trend') or 'n/a'}, EMA50 {_fmt(tech.get('ema50'))}, EMA200 {_fmt(tech.get('ema200'))}, "
        f"MACD {_fmt(tech.get('macd'), digits=2)} vs signal {_fmt(tech.get('macd_signal'), digits=2)}, vol {_fmt(tech.get('volatility'))}%, "
        f"max DD {_fmt(tech.get('max_drawdown'))}%, support {_fmt(tech.get('support'))}, resistance {_fmt(tech.get('resistance'))}",
    ]
    if h:
        lines.append(f"position: {h.get('quantity')} sh @ avg {_fmt(h.get('avg_price'))}, P&L {_fmt(h.get('pnl_pct'))}%, "
                     f"{_fmt(h.get('weight'))}% of equity book")
    return "\n".join(lines)


def _to_meta_verdict(v: DeskVerdict) -> dict:
    lenses = {name: getattr(v, name) for name in LENSES}
    bull = sum(1 for l in lenses.values() if l.signal == "bullish")
    bear = sum(1 for l in lenses.values() if l.signal == "bearish")
    neut = len(lenses) - bull - bear
    score = sum((1 if l.signal == "bullish" else -1 if l.signal == "bearish" else 0) * l.confidence / 100 for l in lenses.values()) / len(lenses)
    action = {"strong buy": "Strong Buy", "buy": "Buy", "hold": "Hold", "sell": "Sell", "strong sell": "Strong Sell"}[v.action]
    return {
        "action": action,
        "confidence": round(v.confidence / 100, 2),
        "score": round(score, 3),
        "reasoning": f"{v.thesis} Key risk: {v.key_risk}",
        "thesis": v.thesis,
        "key_risk": v.key_risk,
        "signal_breakdown": {
            "bullish": bull, "bearish": bear, "neutral": neut, "total": len(lenses),
            "bullish_pct": round(bull / len(lenses) * 100, 1), "bearish_pct": round(bear / len(lenses) * 100, 1),
        },
        "analyst_signals": {
            f"{name}_lens": {"signal": l.signal, "confidence": l.confidence, "reasoning": l.reasoning}
            for name, l in lenses.items()
        },
        "source": "portfolio_desk",
    }


def gather_ticker_data(tickers: list[str], holdings_ctx: dict[str, dict] | None = None) -> dict[str, dict]:
    """Fundamentals + technicals for each ticker (concurrent, failures tolerated)."""
    from app.backend.routes.hedge_fund import _compute_technical, _fetch_fundamentals
    from app.backend.routes.algo_trader import _history_with_fallback

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    def one(t: str) -> tuple[str, dict]:
        d: dict = {"holding": (holdings_ctx or {}).get(t) or {}}
        try:
            df = _history_with_fallback(t, start, end)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().capitalize() for c in df.columns]
                d["technical"] = _compute_technical(df)
                d["current_price"] = round(float(df["Close"].iloc[-1]), 2)
        except Exception as e:
            log.warning("desk: history failed for %s: %s", t, e)
        try:
            d["fundamentals"] = _fetch_fundamentals(t)
        except Exception as e:
            log.warning("desk: fundamentals failed for %s: %s", t, e)
        return t, d

    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(ex.map(one, tickers))


def run_portfolio_desk(tickers: list[str], holdings_ctx: dict[str, dict] | None = None,
                       push: Callable[[dict], None] | None = None, batch_size: int = BATCH_SIZE) -> dict[str, dict]:
    """Return {ticker: meta-style verdict} for every ticker (defaults on failure)."""
    data = gather_ticker_data(tickers, holdings_ctx)
    verdicts: dict[str, dict] = {}
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]
    for i, batch in enumerate(batches, 1):
        if push:
            push({"type": "review", "msg": f"Desk review batch {i}/{len(batches)}: {', '.join(t.replace('.NS', '') for t in batch)}"})
        prompt = SYSTEM + "\n\nStocks:\n\n" + "\n\n".join(_ticker_block(t, data[t]) for t in batch) + \
            f"\n\nReturn one verdict per stock, for exactly these tickers: {', '.join(batch)}."
        result = call_llm(prompt, DeskBatch, agent_name=None, state=None, max_retries=2,
                          default_factory=lambda: DeskBatch(verdicts=[]))
        got = {v.ticker.strip().upper(): v for v in result.verdicts}
        for t in batch:
            v = got.get(t.upper()) or got.get(t.replace(".NS", "").replace(".BO", "").upper())
            if v is None:
                verdicts[t] = {"action": "Hold", "confidence": 0, "score": 0.0,
                               "reasoning": "No verdict returned (model unavailable or usage limit reached).",
                               "signal_breakdown": {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0, "bullish_pct": 0, "bearish_pct": 0},
                               "analyst_signals": {}, "source": "portfolio_desk"}
            else:
                verdicts[t] = _to_meta_verdict(v)
            verdicts[t]["current_price"] = data[t].get("current_price")
    return verdicts
