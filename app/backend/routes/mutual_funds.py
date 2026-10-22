"""Mutual-fund portfolio: Kite MF holdings enriched with NAV analytics and an
LLM review. Read-only with respect to the broker."""

from __future__ import annotations

import asyncio
import re
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.backend.routes.algo_state import state as _state
from src.mf.analyzer import build_mf_portfolio, fetch_nav_history, review_prompt
from src.mf.rules_review import cap_lookthrough, rules_review
from src.mf.universe import best_in_bucket, build_universe, find, load_universe, rank_fund

log = logging.getLogger(__name__)
router = APIRouter(prefix="/mutual-funds", tags=["mutual-funds"])

OUT_DIR = Path(__file__).resolve().parents[3] / "outputs"
REVIEW_FILE = OUT_DIR / "mf_review.json"
PORTFOLIO_TTL = 15 * 60

_cache: dict = {"portfolio": None, "at": 0.0}
_review: dict = {"running": False, "started_at": None, "error": None}
_lock = threading.Lock()


def _kite():
    k = getattr(_state.executor, "_kite", None)
    if k is None or not _state.executor.is_connected():
        raise HTTPException(503, "Zerodha is not connected. Log in from Settings > Connections.")
    return k


def _equity_summary() -> dict | None:
    try:
        holdings = _state.executor.get_holdings()
    except Exception:
        return None
    if not holdings:
        return None
    inv = sum(h.average_price * h.quantity for h in holdings)
    cur = sum(h.last_price * h.quantity for h in holdings)
    top = sorted(holdings, key=lambda h: -h.last_price * h.quantity)[:8]
    return {
        "count": len(holdings), "invested": round(inv, 2), "current": round(cur, 2),
        "pnl": round(cur - inv, 2), "pnl_pct": round((cur / inv - 1) * 100, 2) if inv else None,
        "top": ", ".join(f"{h.ticker} {h.last_price * h.quantity / cur * 100:.1f}%" for h in top) if cur else "",
    }


def _build(refresh: bool = False) -> dict:
    with _lock:
        if not refresh and _cache["portfolio"] and time.time() - _cache["at"] < PORTFOLIO_TTL:
            return _cache["portfolio"]
        raw = _kite().mf_holdings()
        portfolio = build_mf_portfolio(raw)
        portfolio["equity"] = _equity_summary()
        universe = load_universe()
        for f in portfolio["funds"]:
            f["rank"] = rank_fund(universe, f)
        portfolio["cap_lookthrough"] = cap_lookthrough(portfolio["funds"])
        portfolio["universe_as_of"] = (universe or {}).get("as_of")
        if universe is None and not _universe_state["running"]:
            threading.Thread(target=_build_universe_sync, daemon=True).start()
        _cache["portfolio"], _cache["at"] = portfolio, time.time()
        return portfolio


@router.get("/holdings")
async def get_holdings(refresh: bool = False):
    """MF holdings with per-fund analytics, allocation and concentration."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: _build(refresh))
    except HTTPException:
        raise
    except Exception as e:
        log.exception("mf holdings failed")
        raise HTTPException(500, str(e))


@router.get("/fund/{scheme_code}/nav")
async def get_fund_nav(scheme_code: int, days: int = 1095):
    loop = asyncio.get_running_loop()
    df = await loop.run_in_executor(None, lambda: fetch_nav_history(scheme_code))
    if df.empty:
        raise HTTPException(404, "No NAV history for this scheme")
    df = df[df.index >= df.index[-1] - pd_days(days)]
    return {"scheme_code": scheme_code,
            "points": [{"d": d.strftime("%Y-%m-%d"), "v": float(v)} for d, v in df["nav"].items()]}


def pd_days(days: int):
    import pandas as pd
    return pd.Timedelta(days=days)


# ── Universe (peer ranking) and rules-based review ──────────────────────────

_universe_state: dict = {"running": False, "done": 0, "total": 0, "error": None}


def _build_universe_sync():
    _universe_state.update(running=True, done=0, error=None)
    try:
        def prog(i, n):
            _universe_state["done"], _universe_state["total"] = i, n
        build_universe(progress=prog)
        _cache["at"] = 0.0          # holdings get re-ranked on next request
    except Exception as e:
        log.exception("universe build failed")
        _universe_state["error"] = str(e)
    finally:
        _universe_state["running"] = False


@router.post("/universe/refresh")
async def universe_refresh(background_tasks: BackgroundTasks):
    if _universe_state["running"]:
        return {"running": True, **_universe_state}
    loop = asyncio.get_running_loop()
    background_tasks.add_task(loop.run_in_executor, None, _build_universe_sync)
    return {"running": True, "message": "universe build started"}


@router.get("/universe")
async def universe_get(bucket: str | None = None, q: str | None = None, n: int = 10):
    """Best funds per role (by 3y CAGR / vol), or a name search, from the cached universe."""
    u = load_universe(max_age=365 * 24 * 3600)
    if u is None:
        return {"as_of": None, "rows": [], **_universe_state}
    held = {f["scheme_code"] for f in ((_cache["portfolio"] or {}).get("funds") or [])}
    if q:
        rows = find(u, q, n)
    elif bucket:
        rows = best_in_bucket(u, bucket, n, exclude=held)
    else:
        buckets = sorted({r["bucket"] for r in u["rows"]})
        rows = {b: best_in_bucket(u, b, 5, exclude=held) for b in buckets}
    return {"as_of": u.get("as_of"), "count": u.get("count"), "rows": rows, **_universe_state}


# Gold/silver ETF tickers and sovereign gold bonds — anchored so GOLDIAM (a jeweller) does not match.
_BALLAST_RE = re.compile(r"^(?:[A-Z]*GOLD(?:BEES|CASE|IETF|ETF|1|SHARE)?|SETFGOLD|[A-Z]*SILVER(?:BEES|IETF|ETF|ADD)?|TATSILV|SGB[A-Z0-9]*)(?:-[A-Z]+)?$", re.I)


def _household_ballast() -> dict | None:
    """Gold/silver ETFs and sovereign gold bonds sitting in the demat: ballast the fund rules should count."""
    try:
        rows = _kite().holdings()
    except Exception:
        return None
    value = sum((h.get("quantity", 0) + h.get("t1_quantity", 0)) * (h.get("last_price") or 0)
                for h in rows if _BALLAST_RE.search(h.get("tradingsymbol", "")))
    if value <= 0:
        return None
    names = sorted({h["tradingsymbol"] for h in rows if _BALLAST_RE.search(h.get("tradingsymbol", ""))})
    return {"value": round(value, 2), "label": "demat gold/silver (" + ", ".join(names) + ")"}


@router.get("/rules-review")
async def rules_review_get(profile: str = "growth", refresh: bool = False):
    """Deterministic construction review (no LLM): rules over the holdings and their peer ranks."""
    loop = asyncio.get_running_loop()
    portfolio = await loop.run_in_executor(None, lambda: _build(refresh))
    universe = load_universe(max_age=365 * 24 * 3600)
    household = await loop.run_in_executor(None, _household_ballast)
    review = rules_review(portfolio, universe, profile=profile, household_ballast=household)
    review["household_ballast"] = household
    review["timestamp"] = datetime.now().isoformat(timespec="seconds")
    review["universe_as_of"] = (universe or {}).get("as_of")
    return review


# ── LLM review ──────────────────────────────────────────────────────────────

class NextStep(BaseModel):
    title: str
    rationale: str
    priority: Literal["high", "medium", "low"] = "medium"


class FundNote(BaseModel):
    fund: str
    role: str = Field(description="What this fund contributes to the portfolio, in a few words")
    flag: Literal["core", "satellite", "overlap", "review"] = "satellite"
    note: str


class MFReview(BaseModel):
    health_score: int = Field(ge=0, le=100, description="Overall portfolio construction quality, 0-100")
    headline: str = Field(description="One sentence summary")
    overall_assessment: str
    strengths: list[str]
    concerns: list[str]
    redundancies: list[str] = Field(description="Groups of funds doing the same job")
    diversification_notes: str
    next_steps: list[NextStep]
    fund_notes: list[FundNote]


REVIEW_SYSTEM = """You are a SEBI-registered-adviser-style mutual fund portfolio reviewer for an Indian retail investor.
You are reviewing PORTFOLIO CONSTRUCTION, not predicting markets. Be specific and quantitative, cite the numbers you were given,
and keep every statement grounded in them. Where you suggest a change, phrase it as something to evaluate, with the trade-off,
and mention tax/exit-load considerations where relevant (equity LTCG after 12 months, exit loads typically within 1 year).
Flag: overlapping funds in the same category, too many funds for the corpus, concentration in sector/thematic bets,
international exposure, cost (direct vs regular), funds with short track records, and whether the direct-equity book
duplicates what the funds already hold. This is educational analysis, not personalised financial advice, and must say so once."""


def _run_review_sync():
    from src.utils.llm import call_llm
    _review.update(running=True, started_at=datetime.now().isoformat(timespec="seconds"), error=None)
    try:
        portfolio = _build(refresh=False)
        prompt = REVIEW_SYSTEM + "\n\n" + review_prompt(portfolio, portfolio.get("equity")) + \
            "\n\nReturn the structured review. Reference funds by their full names as given."
        result = call_llm(prompt, MFReview, agent_name=None, state=None, max_retries=2)
        review = result.model_dump()
        review["timestamp"] = datetime.now().isoformat(timespec="seconds")
        review["fund_count"] = portfolio["fund_count"]
        review["current"] = portfolio["current"]
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        REVIEW_FILE.write_text(json.dumps(review, indent=2))
    except Exception as e:
        log.exception("MF review failed")
        _review["error"] = str(e)
    finally:
        _review["running"] = False


@router.post("/review")
async def start_review(background_tasks: BackgroundTasks):
    if _review["running"]:
        return {"running": True, "message": "Review already in progress"}
    loop = asyncio.get_running_loop()
    background_tasks.add_task(loop.run_in_executor, None, _run_review_sync)
    return {"running": True, "message": "Review started"}


@router.get("/review")
async def get_review():
    review = json.loads(REVIEW_FILE.read_text()) if REVIEW_FILE.exists() else None
    return {"review": review, "running": _review["running"], "started_at": _review["started_at"], "error": _review["error"]}
