"""Derivatives API — endpoints for options and futures backtesting."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.algo_trader.options.strategies import OPTIONS_STRATEGY_REGISTRY
from src.algo_trader.options.batch_runner import (
    OptionsBatchConfig,
    run_options_batch,
    load_options_results,
    get_options_summary,
    get_options_progress,
    is_options_running,
    INDICES as OPT_INDICES,
)
from src.algo_trader.futures.strategies import FUTURES_STRATEGY_REGISTRY
from src.algo_trader.futures.engine import (
    FuturesBatchConfig,
    run_futures_batch,
    load_futures_results,
    get_futures_summary,
    get_futures_progress,
    is_futures_running,
    INDICES as FUT_INDICES,
)

router = APIRouter(prefix="/derivatives", tags=["derivatives"])
log = logging.getLogger(__name__)


# ── Schemas ──

class OptionsBatchRequest(BaseModel):
    strategies: list[str] | None = None
    indices: list[str] | None = None
    periods: list[dict] | None = None
    initial_capital: float = 10_00_000
    expiry_cycle: str = "weekly"


class FuturesBatchRequest(BaseModel):
    strategies: list[str] | None = None
    indices: list[str] | None = None
    periods: list[dict] | None = None
    initial_capital: float = 10_00_000


# ── Options Endpoints ──

@router.get("/options/strategies")
async def list_options_strategies():
    return [
        {"name": name, "description": desc, "instrument": "options"}
        for name, (_cls, desc) in OPTIONS_STRATEGY_REGISTRY.items()
    ]


@router.get("/options/indices")
async def list_options_indices():
    return OPT_INDICES


@router.post("/options/backtest-batch")
async def start_options_batch(req: OptionsBatchRequest, background_tasks: BackgroundTasks):
    if is_options_running():
        return {"status": "error", "message": "An options batch is already running"}

    indices = OPT_INDICES[:]
    if req.indices:
        indices = [i for i in OPT_INDICES if i["name"] in req.indices]

    config = OptionsBatchConfig(
        indices=indices,
        strategy_names=req.strategies or list(OPTIONS_STRATEGY_REGISTRY.keys()),
        initial_capital=req.initial_capital,
        expiry_cycle=req.expiry_cycle,
    )
    if req.periods:
        config.periods = req.periods

    def _run():
        try:
            run_options_batch(config)
        except Exception as e:
            log.error("Options batch failed: %s", e)

    background_tasks.add_task(_run)
    return {"status": "started", "total_jobs": config.total_jobs}


@router.get("/options/backtest-batch/stream")
async def stream_options_progress():
    async def event_gen():
        while True:
            progress = get_options_progress()
            data = json.dumps(progress.to_dict())
            yield f"data: {data}\n\n"
            if not is_options_running() and progress.completed > 0:
                yield f"data: {json.dumps({**progress.to_dict(), 'done': True})}\n\n"
                break
            await asyncio.sleep(1)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/options/status")
async def options_status():
    return {"running": is_options_running(), "progress": get_options_progress().to_dict()}


@router.get("/options/results")
async def get_options_results(limit: int = Query(500, ge=1, le=5000)):
    return load_options_results()[:limit]


@router.get("/options/results/summary")
async def options_results_summary():
    return get_options_summary()


# ── Futures Endpoints ──

@router.get("/futures/strategies")
async def list_futures_strategies():
    return [
        {"name": name, "description": desc, "instrument": "futures"}
        for name, (_cls, desc) in FUTURES_STRATEGY_REGISTRY.items()
    ]


@router.get("/futures/indices")
async def list_futures_indices():
    return FUT_INDICES


@router.post("/futures/backtest-batch")
async def start_futures_batch(req: FuturesBatchRequest, background_tasks: BackgroundTasks):
    if is_futures_running():
        return {"status": "error", "message": "A futures batch is already running"}

    indices = FUT_INDICES[:]
    if req.indices:
        indices = [i for i in FUT_INDICES if i["name"] in req.indices]

    config = FuturesBatchConfig(
        indices=indices,
        strategy_names=req.strategies or list(FUTURES_STRATEGY_REGISTRY.keys()),
        initial_capital=req.initial_capital,
    )
    if req.periods:
        config.periods = req.periods

    def _run():
        try:
            run_futures_batch(config)
        except Exception as e:
            log.error("Futures batch failed: %s", e)

    background_tasks.add_task(_run)
    return {"status": "started", "total_jobs": config.total_jobs}


@router.get("/futures/backtest-batch/stream")
async def stream_futures_progress():
    async def event_gen():
        while True:
            progress = get_futures_progress()
            data = json.dumps(progress.to_dict())
            yield f"data: {data}\n\n"
            if not is_futures_running() and progress.completed > 0:
                yield f"data: {json.dumps({**progress.to_dict(), 'done': True})}\n\n"
                break
            await asyncio.sleep(1)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/futures/status")
async def futures_status():
    return {"running": is_futures_running(), "progress": get_futures_progress().to_dict()}


@router.get("/futures/results")
async def get_futures_results(limit: int = Query(500, ge=1, le=5000)):
    return load_futures_results()[:limit]


@router.get("/futures/results/summary")
async def futures_results_summary():
    return get_futures_summary()
