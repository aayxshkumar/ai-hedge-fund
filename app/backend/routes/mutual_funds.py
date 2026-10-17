"""Mutual-fund portfolio: Kite MF holdings enriched with NAV analytics and an
LLM review. Read-only with respect to the broker."""

from __future__ import annotations

import asyncio
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
