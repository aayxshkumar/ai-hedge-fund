"""Shared state and utilities for the algo-trader route package.

All route sub-modules import ``state``, the Pydantic request models, and
helper constants from here rather than defining their own.
"""

from __future__ import annotations

import logging
import secrets
import threading
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from src.algo_trader.config import AlgoTraderConfig
from src.algo_trader.executor import ZerodhaExecutor
from src.algo_trader.risk_engine import RiskEngine
from src.algo_trader.paper_trader import PaperTrader
from src.algo_trader.tradebook import Tradebook

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN_HOUR, MARKET_OPEN_MIN = 9, 15
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 15, 30
SCAN_INTERVAL_MINUTES = 30


def is_market_hours(now_ist: datetime | None = None) -> bool:
    t = (now_ist or datetime.now(IST)).time()
    return dtime(MARKET_OPEN_HOUR, MARKET_OPEN_MIN) <= t <= dtime(MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN)


class AlgoState:
    """Module-level singleton holding the running algo-trader state."""

    def __init__(self):
        self.config: AlgoTraderConfig = AlgoTraderConfig.from_env()
        self.executor: ZerodhaExecutor = ZerodhaExecutor(self.config)
        self.risk: RiskEngine = RiskEngine(self.config)
        self.running: bool = False
        self.mode: str = "paper"
        self.thread: threading.Thread | None = None
        self.stop_event: threading.Event = threading.Event()
        self.signals: list[dict] = []
        self.execution_log: list[dict] = []
        self.last_cycle_time: str | None = None
        self.events: list[dict] = []
        self._event_lock = threading.Lock()
        self.paper_trader: PaperTrader = PaperTrader()
        self.scanner_running: bool = False
        self.scanner_thread: threading.Thread | None = None
        self.scanner_stop: threading.Event = threading.Event()
        self.last_scan_time: str | None = None
        self.last_scan_results: list[dict] = []
        self.tradebook: Tradebook = Tradebook()
        self.analyst_review: dict | None = None
        self.analyst_review_time: str | None = None
        self.analyst_review_running: bool = False
        self.review_scheduler_running: bool = False
        self.review_scheduler_thread: threading.Thread | None = None
        self.review_scheduler_stop: threading.Event = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._live_confirm_token: str | None = None
        self._live_confirm_expiry: datetime | None = None

        # Generation status tracking (protected by _gen_lock)
        self._gen_lock = threading.Lock()
        self._daily_analysis_generating: bool = False
        self._daily_analysis_ready: bool = False
        self._penny_scan_running: bool = False
        self._penny_scan_ready: bool = False

    def push_event(self, event: dict):
        with self._event_lock:
            event["ts"] = datetime.now(timezone.utc).isoformat()
            self.events.append(event)
            if len(self.events) > 500:
                self.events = self.events[-300:]

    def zerodha_status(self) -> dict:
        return self.executor.connection_status()

    # Thread-safe properties for generation status
    @property
    def daily_analysis_generating(self) -> bool:
        with self._gen_lock:
            return self._daily_analysis_generating

    @daily_analysis_generating.setter
    def daily_analysis_generating(self, v: bool):
        with self._gen_lock:
            self._daily_analysis_generating = v

    @property
    def daily_analysis_ready(self) -> bool:
        with self._gen_lock:
            return self._daily_analysis_ready

    @daily_analysis_ready.setter
    def daily_analysis_ready(self, v: bool):
        with self._gen_lock:
            self._daily_analysis_ready = v

    @property
    def penny_scan_running(self) -> bool:
        with self._gen_lock:
            return self._penny_scan_running

    @penny_scan_running.setter
    def penny_scan_running(self, v: bool):
        with self._gen_lock:
            self._penny_scan_running = v

    @property
    def penny_scan_ready(self) -> bool:
        with self._gen_lock:
            return self._penny_scan_ready

    @penny_scan_ready.setter
    def penny_scan_ready(self, v: bool):
        with self._gen_lock:
            self._penny_scan_ready = v

    def try_start_penny_scan(self) -> bool:
        """Atomically check-and-set penny_scan_running. Returns True if started."""
        with self._gen_lock:
            if self._penny_scan_running:
                return False
            self._penny_scan_running = True
            self._penny_scan_ready = False
            return True

    def try_start_daily_analysis(self) -> bool:
        """Atomically check-and-set daily_analysis_generating. Returns True if started."""
        with self._gen_lock:
            if self._daily_analysis_generating:
                return False
            self._daily_analysis_generating = True
            self._daily_analysis_ready = False
            return True


state = AlgoState()


def get_meta_verdict(ticker: str) -> dict | None:
    """Look up the Meta Analyst verdict for *ticker* from the cached review."""
    review = state.analyst_review
    if review is None:
        return None
    verdicts = review.get("verdicts", {})
    clean = ticker.replace(".NS", "").replace(".BO", "")
    return verdicts.get(ticker) or verdicts.get(f"{clean}.NS") or verdicts.get(f"{clean}.BO") or verdicts.get(clean)


# ── Pydantic models ──────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    watchlist: list[str] | None = None
    auto_trade: bool | None = None
    read_only: bool | None = None
    max_daily_loss_pct: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_position_pct: float | None = None
    model_name: str | None = None


class RunCycleRequest(BaseModel):
    tickers: list[str] | None = None


class ScreenRequest(BaseModel):
    tickers: list[str] | None = None
    top_n: int = 15
    auto_update_watchlist: bool = False
