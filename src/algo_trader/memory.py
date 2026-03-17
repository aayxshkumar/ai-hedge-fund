"""OpenViking memory integration for the algo trader.

Stores and retrieves:
- Trading decisions and their outcomes
- Strategy performance metrics
- Market pattern observations
- Learned correlations and regime data

Uses OpenViking's filesystem-paradigm context database with L0/L1/L2 tiered
context loading for efficient retrieval during analysis cycles.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from src.algo_trader.config import AlgoTraderConfig

log = logging.getLogger(__name__)


class TradingMemory:
    """Persistent context memory for trading decisions and outcomes."""

    def __init__(self, config: AlgoTraderConfig):
        self.enabled = config.openviking_enabled
        self.base_url = config.openviking_url
        self._client = httpx.Client(timeout=15) if self.enabled else None
        self._local_log_path = Path("data/trade_log.jsonl")
        self._local_log_path.parent.mkdir(parents=True, exist_ok=True)

    def record_decision(self, decision: dict):
        """Log a trading decision for future reference."""
        entry = {
            "type": "decision",
            "timestamp": datetime.now().isoformat(),
            **decision,
        }
        self._append_local(entry)
        if self.enabled:
            self._store_context(f"decisions/{decision.get('ticker', 'unknown')}", entry)

    def record_outcome(self, ticker: str, entry_price: float, exit_price: float, pnl: float, holding_days: int):
        """Log the outcome of a closed trade."""
        entry = {
            "type": "outcome",
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": (exit_price - entry_price) / entry_price if entry_price > 0 else 0,
            "holding_days": holding_days,
        }
        self._append_local(entry)
        if self.enabled:
            self._store_context(f"outcomes/{ticker}", entry)

    def record_strategy_performance(self, strategy_name: str, metrics: dict):
        entry = {
            "type": "strategy_perf",
            "timestamp": datetime.now().isoformat(),
            "strategy": strategy_name,
            **metrics,
        }
        self._append_local(entry)
        if self.enabled:
            self._store_context(f"strategies/{strategy_name}", entry)

    def get_ticker_history(self, ticker: str, limit: int = 20) -> list[dict]:
        """Retrieve recent decisions/outcomes for a ticker."""
        if self.enabled:
            return self._query_context(f"decisions/{ticker}", limit) + self._query_context(f"outcomes/{ticker}", limit)
        return self._read_local_for_ticker(ticker, limit)

    def get_strategy_history(self, strategy_name: str, limit: int = 10) -> list[dict]:
        if self.enabled:
            return self._query_context(f"strategies/{strategy_name}", limit)
        return []

    # ── Local fallback (always writes, OpenViking optional) ──────────

    def _append_local(self, entry: dict):
        try:
            with open(self._local_log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            log.warning("Failed to write local trade log: %s", e)

    def _read_local_for_ticker(self, ticker: str, limit: int) -> list[dict]:
        entries = []
        try:
            with open(self._local_log_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("ticker") == ticker:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return entries[-limit:]

    # ── OpenViking API ──────────────────────────────────────────────

    def _store_context(self, path: str, data: dict):
        if not self._client:
            return
        try:
            self._client.post(
                f"{self.base_url}/api/v1/context",
                json={"path": f"algo_trader/{path}", "content": json.dumps(data)},
            )
        except httpx.HTTPError as e:
            log.debug("OpenViking store failed: %s", e)

    def _query_context(self, path: str, limit: int) -> list[dict]:
        if not self._client:
            return []
        try:
            resp = self._client.get(
                f"{self.base_url}/api/v1/context",
                params={"path": f"algo_trader/{path}", "limit": limit},
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                return [json.loads(item["content"]) for item in items if "content" in item]
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            log.debug("OpenViking query failed: %s", e)
        return []
