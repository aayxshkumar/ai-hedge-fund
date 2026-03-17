"""Connection management routes — Zerodha Kite Connect, API keys, trading config."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.repositories.api_key_repository import ApiKeyRepository

log = logging.getLogger(__name__)
router = APIRouter(prefix="/connections", tags=["connections"])

IST = ZoneInfo("Asia/Kolkata")
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


# ── Pydantic schemas ─────────────────────────────────────────────────

class KiteCredentials(BaseModel):
    api_key: str
    api_secret: str


class KiteTokenRequest(BaseModel):
    request_token: str


class TradingConfigUpdate(BaseModel):
    mode: str | None = None
    auto_trade: bool | None = None
    max_position_pct: float | None = None
    max_portfolio_exposure: float | None = None
    max_single_order_value: float | None = None
    max_daily_loss_pct: float | None = None
    max_open_positions: int | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    analysis_interval_minutes: int | None = None
    model_name: str | None = None
    model_provider: str | None = None


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class BulkEnvUpdate(BaseModel):
    vars: list[EnvVarUpdate]


# ── Helpers ───────────────────────────────────────────────────────────

def _get_algo_state():
    from app.backend.routes.algo_trader import _state
    return _state


def _read_env_file() -> dict[str, str]:
    result: dict[str, str] = {}
    if not ENV_PATH.exists():
        return result
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _write_env_file(data: dict[str, str]):
    lines: list[str] = []
    existing_keys: set[str] = set()

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(line)
                continue
            if "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                existing_keys.add(k)
                if k in data:
                    lines.append(f'{k}="{data[k]}"' if " " in data[k] else f"{k}={data[k]}")
                else:
                    lines.append(line)
            else:
                lines.append(line)

    for k, v in data.items():
        if k not in existing_keys:
            lines.append(f'{k}="{v}"' if " " in v else f"{k}={v}")

    ENV_PATH.write_text("\n".join(lines) + "\n")
    for k, v in data.items():
        os.environ[k] = v


# ── Connection status ─────────────────────────────────────────────────

@router.get("/status")
async def get_all_connection_status(db: Session = Depends(get_db)):
    state = _get_algo_state()
    zerodha = state.executor.connection_status()

    repo = ApiKeyRepository(db)
    all_keys = repo.get_all_api_keys(include_inactive=True)
    api_keys_status: list[dict[str, Any]] = []
    for k in all_keys:
        api_keys_status.append({
            "provider": k.provider,
            "is_active": k.is_active,
            "has_key": bool(k.key_value),
            "last_used": k.last_used.isoformat() if k.last_used else None,
        })
    provider_set = {k.provider for k in all_keys if k.is_active and k.key_value}

    now_ist = datetime.now(IST)

    return {
        "zerodha": zerodha,
        "api_keys": api_keys_status,
        "active_providers": sorted(provider_set),
        "trading": {
            "mode": "paper" if state.config.broker.read_only else "live",
            "auto_trade": not state.config.risk.require_confirmation,
            "trader_running": state.running,
            "scanner_running": state.scanner_running,
        },
        "risk": {
            "max_position_pct": state.config.risk.max_position_pct,
            "max_portfolio_exposure": state.config.risk.max_portfolio_exposure,
            "max_single_order_value": state.config.risk.max_single_order_value,
            "max_daily_loss_pct": state.config.risk.max_daily_loss_pct,
            "max_open_positions": state.config.risk.max_open_positions,
            "stop_loss_pct": state.config.risk.stop_loss_pct,
            "take_profit_pct": state.config.risk.take_profit_pct,
        },
        "scheduler": {
            "market_open": state.config.scheduler.market_open,
            "market_close": state.config.scheduler.market_close,
            "analysis_interval_minutes": state.config.scheduler.analysis_interval_minutes,
        },
        "model": {
            "name": state.config.model_name,
            "provider": state.config.model_provider,
        },
        "watchlist_count": len(state.config.watchlist),
        "current_time_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── Zerodha Kite Connect ─────────────────────────────────────────────

@router.post("/zerodha/test")
async def test_zerodha_connection():
    """Test the Kite Connect connection by fetching profile."""
    state = _get_algo_state()
    result = state.executor.connection_status()

    funds = None
    if result.get("connected"):
        funds = state.executor.get_funds()

    return {**result, "funds": funds}


@router.put("/zerodha/credentials")
async def update_zerodha_credentials(creds: KiteCredentials):
    """Save Kite Connect API key and secret, reinitialize the executor."""
    state = _get_algo_state()
    state.config.broker.api_key = creds.api_key
    state.config.broker.api_secret = creds.api_secret

    _write_env_file({
        "KITE_API_KEY": creds.api_key,
        "KITE_API_SECRET": creds.api_secret,
    })

    state.executor._init_kite()
    state.push_event({"type": "config_update", "msg": "Kite Connect credentials updated"})

    login_url = state.executor.generate_login_url()
    return {
        "message": "Credentials saved",
        "login_url": login_url,
        "has_api_key": bool(creds.api_key),
    }


@router.get("/zerodha/login-url")
async def get_zerodha_login_url():
    """Get the Kite Connect login URL for the user to authenticate."""
    state = _get_algo_state()
    url = state.executor.generate_login_url()
    if not url:
        raise HTTPException(400, "No API key configured — set credentials first")
    return {"login_url": url}


@router.post("/zerodha/callback")
async def zerodha_callback(req: KiteTokenRequest):
    """Exchange request_token for access_token after the user completes login."""
    state = _get_algo_state()
    result = state.executor.generate_session(req.request_token)

    if result.get("error"):
        raise HTTPException(400, result["error"])

    access_token = result.get("access_token", "")
    if access_token:
        _write_env_file({"KITE_ACCESS_TOKEN": access_token})

    state.push_event({"type": "zerodha", "msg": f"Logged in as {result.get('user_name', 'user')}"})
    return result


# ── Trading config ────────────────────────────────────────────────────

@router.put("/trading/config")
async def update_trading_config(update: TradingConfigUpdate):
    state = _get_algo_state()
    changes: list[str] = []

    if update.mode is not None:
        if update.mode == "paper":
            state.config.broker.read_only = True
            changes.append("mode→paper")
        elif update.mode == "live":
            state.config.broker.read_only = False
            state.config.risk.require_confirmation = False
            changes.append("mode→LIVE")
        state.push_event({"type": "mode", "msg": f"Trading mode changed to {update.mode.upper()}"})

    if update.auto_trade is not None:
        state.config.risk.require_confirmation = not update.auto_trade
        changes.append(f"auto_trade→{update.auto_trade}")

    risk = state.config.risk
    if update.max_position_pct is not None:
        risk.max_position_pct = update.max_position_pct
    if update.max_portfolio_exposure is not None:
        risk.max_portfolio_exposure = update.max_portfolio_exposure
    if update.max_single_order_value is not None:
        risk.max_single_order_value = update.max_single_order_value
    if update.max_daily_loss_pct is not None:
        risk.max_daily_loss_pct = update.max_daily_loss_pct
    if update.max_open_positions is not None:
        risk.max_open_positions = update.max_open_positions
    if update.stop_loss_pct is not None:
        risk.stop_loss_pct = update.stop_loss_pct
    if update.take_profit_pct is not None:
        risk.take_profit_pct = update.take_profit_pct

    if update.analysis_interval_minutes is not None:
        state.config.scheduler.analysis_interval_minutes = update.analysis_interval_minutes
    if update.model_name is not None:
        state.config.model_name = update.model_name
    if update.model_provider is not None:
        state.config.model_provider = update.model_provider

    if changes:
        state.push_event({"type": "config_update", "msg": f"Trading config: {', '.join(changes)}"})

    return {
        "message": f"Updated: {', '.join(changes)}" if changes else "Config saved",
        "mode": "paper" if state.config.broker.read_only else "live",
        "risk": {
            "max_position_pct": risk.max_position_pct,
            "max_portfolio_exposure": risk.max_portfolio_exposure,
            "max_single_order_value": risk.max_single_order_value,
            "max_daily_loss_pct": risk.max_daily_loss_pct,
            "max_open_positions": risk.max_open_positions,
            "stop_loss_pct": risk.stop_loss_pct,
            "take_profit_pct": risk.take_profit_pct,
        },
        "scheduler": {
            "analysis_interval_minutes": state.config.scheduler.analysis_interval_minutes,
        },
    }


# ── Environment variables ─────────────────────────────────────────────

@router.get("/env")
async def get_env_vars():
    data = _read_env_file()
    safe: dict[str, Any] = {}
    for k, v in data.items():
        if "KEY" in k or "SECRET" in k or "TOKEN" in k or "PASSWORD" in k:
            safe[k] = f"{'*' * min(len(v), 8)}...{v[-4:]}" if len(v) > 4 else "****"
        else:
            safe[k] = v
    return {"env": safe, "path": str(ENV_PATH)}


@router.put("/env")
async def update_env_vars(update: BulkEnvUpdate):
    data = {v.key: v.value for v in update.vars}
    _write_env_file(data)
    return {"message": f"Updated {len(data)} env var(s)", "keys": list(data.keys())}
