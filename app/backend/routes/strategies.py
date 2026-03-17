"""Strategy Lab API — endpoints for listing strategies, running batch backtests,
and fetching results for the frontend dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.algo_trader.strategies import STRATEGY_REGISTRY
from src.algo_trader.simulation.batch_runner import (
    BatchConfig,
    run_batch,
    load_results,
    get_strategy_summary,
    get_progress,
    is_running,
)
from src.algo_trader.simulation.nifty50 import NIFTY_50

router = APIRouter(prefix="/strategies", tags=["strategies"])
log = logging.getLogger(__name__)


class BatchRequest(BaseModel):
    strategies: list[str] | None = None
    tickers: list[str] | None = None
    periods: list[dict] | None = None
    initial_capital: float = 10_00_000
    max_workers: int = 6


@router.get("/list")
async def list_strategies():
    """Return all available strategies with descriptions."""
    return [
        {"name": name, "description": desc}
        for name, (_cls, desc) in STRATEGY_REGISTRY.items()
    ]


@router.get("/tickers")
async def list_tickers():
    """Return the Nifty 50 ticker universe."""
    return NIFTY_50


@router.post("/backtest-batch")
async def start_batch(req: BatchRequest, background_tasks: BackgroundTasks):
    """Trigger a batch backtest run in the background.  Returns immediately."""
    if is_running():
        return {"status": "error", "message": "A batch is already running"}

    config = BatchConfig(
        tickers=req.tickers or NIFTY_50[:],
        strategy_names=req.strategies or list(STRATEGY_REGISTRY.keys()),
        initial_capital=req.initial_capital,
        max_workers=req.max_workers,
    )
    if req.periods:
        config.periods = req.periods

    def _run():
        try:
            run_batch(config)
        except Exception as e:
            log.error("Batch run failed: %s", e)

    background_tasks.add_task(_run)
    return {"status": "started", "total_jobs": config.total_jobs}


@router.get("/backtest-batch/stream")
async def stream_progress():
    """SSE stream of batch progress updates."""
    async def event_gen():
        while True:
            progress = get_progress()
            data = json.dumps(progress.to_dict())
            yield f"data: {data}\n\n"
            if not is_running() and progress.completed > 0:
                yield f"data: {json.dumps({**progress.to_dict(), 'done': True})}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/status")
async def batch_status():
    """Current batch run progress."""
    return {
        "running": is_running(),
        "progress": get_progress().to_dict(),
    }


@router.get("/results")
async def get_results(
    strategy: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Fetch backtest results with optional filters."""
    data = load_results()
    if strategy:
        data = [r for r in data if r["strategy"] == strategy]
    if ticker:
        data = [r for r in data if r["ticker"] == ticker]
    if period:
        data = [r for r in data if r["period"] == period]
    return data[:limit]


@router.get("/results/summary")
async def get_results_summary():
    """Aggregated performance summary per strategy."""
    return get_strategy_summary()


@router.get("/results/{strategy_name}")
async def get_strategy_results(strategy_name: str):
    """All results for a single strategy."""
    data = load_results()
    return [r for r in data if r["strategy"] == strategy_name]


@router.get("/compare")
async def compare_strategies(
    strategies: str = Query(..., description="Comma-separated strategy names"),
    period: Optional[str] = Query(None),
):
    """Side-by-side comparison of selected strategies."""
    names = [s.strip() for s in strategies.split(",")]
    data = load_results()
    filtered = [r for r in data if r["strategy"] in names]
    if period:
        filtered = [r for r in filtered if r["period"] == period]
    return filtered


@router.get("/heatmap")
async def returns_heatmap(period: Optional[str] = Query(None)):
    """Strategy x Ticker returns matrix for the heatmap visualization."""
    data = load_results()
    if period:
        data = [r for r in data if r["period"] == period]

    matrix: dict[str, dict[str, float]] = {}
    for r in data:
        if r.get("error"):
            continue
        strat = r["strategy"]
        if strat not in matrix:
            matrix[strat] = {}
        matrix[strat][r["ticker"]] = r["total_return_pct"]

    return matrix
