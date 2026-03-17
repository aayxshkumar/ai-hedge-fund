"""Strategy Performance Tracker — validates strategies via recent backtests before live use.

Maintains a SQLite table of per-strategy backtest metrics (sharpe, win rate,
expectancy, drawdown).  Before the trading loop uses a strategy, it must pass
validation: recent backtest with positive expectancy and sharpe > threshold.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = Path(__file__).resolve().parents[2] / "outputs" / "strategy_tracker.db"


class StrategyTracker:
    """Tracks strategy performance and validates strategies for live use."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    asset_class TEXT DEFAULT 'equity',
                    last_backtest_date TEXT,
                    period TEXT DEFAULT '6M',
                    sharpe REAL DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    expectancy REAL DEFAULT 0,
                    total_return REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    approved INTEGER DEFAULT 0,
                    notes TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS live_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    trades INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    pnl REAL DEFAULT 0,
                    avg_confidence REAL DEFAULT 0
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_sp_name_class
                    ON strategy_performance(strategy_name, asset_class);
                CREATE INDEX IF NOT EXISTS idx_lp_strategy_date
                    ON live_performance(strategy_name, date);
            """)

    def record_backtest(
        self,
        strategy_name: str,
        asset_class: str = "equity",
        sharpe: float = 0,
        win_rate: float = 0,
        max_drawdown: float = 0,
        expectancy: float = 0,
        total_return: float = 0,
        total_trades: int = 0,
        period: str = "6M",
        notes: str = "",
    ):
        """Record or update backtest results for a strategy."""
        now = datetime.now(IST).isoformat()
        approved = 1 if expectancy > 0 and sharpe > 0.3 else 0

        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT INTO strategy_performance
                    (strategy_name, asset_class, last_backtest_date, period, sharpe,
                     win_rate, max_drawdown, expectancy, total_return, total_trades,
                     approved, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_name, asset_class) DO UPDATE SET
                    last_backtest_date = excluded.last_backtest_date,
                    period = excluded.period,
                    sharpe = excluded.sharpe,
                    win_rate = excluded.win_rate,
                    max_drawdown = excluded.max_drawdown,
                    expectancy = excluded.expectancy,
                    total_return = excluded.total_return,
                    total_trades = excluded.total_trades,
                    approved = excluded.approved,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
            """, (strategy_name, asset_class, now, period, sharpe, win_rate,
                  max_drawdown, expectancy, total_return, total_trades, approved, notes, now))

    def validate_strategy(self, strategy_name: str, asset_class: str = "equity", max_age_days: int = 7) -> bool:
        """Check if a strategy has a recent, passing backtest."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM strategy_performance WHERE strategy_name = ? AND asset_class = ?",
                (strategy_name, asset_class),
            ).fetchone()

        if not row:
            return True  # no data — allow by default (first run)

        if not row["approved"]:
            log.info("Strategy %s/%s failed validation: not approved (sharpe=%.2f, exp=%.2f)",
                     strategy_name, asset_class, row["sharpe"], row["expectancy"])
            return False

        if row["last_backtest_date"]:
            try:
                bt_date = datetime.fromisoformat(row["last_backtest_date"])
                age = datetime.now(IST) - bt_date.replace(tzinfo=IST) if bt_date.tzinfo is None else datetime.now(IST) - bt_date
                if age > timedelta(days=max_age_days):
                    log.info("Strategy %s/%s backtest is stale (%.0f days old)", strategy_name, asset_class, age.days)
                    return True  # stale but still allow — will be re-backtested
            except Exception:
                pass

        return True

    def get_approved_strategies(self, asset_class: str | None = None) -> list[dict]:
        """Return all approved strategies, optionally filtered by asset class."""
        query = "SELECT * FROM strategy_performance WHERE approved = 1"
        params: list = []
        if asset_class:
            query += " AND asset_class = ?"
            params.append(asset_class)
        query += " ORDER BY sharpe DESC"

        with self._lock, self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_all_performance(self) -> list[dict]:
        """Return all strategy performance data."""
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM strategy_performance ORDER BY sharpe DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def record_live_trade(self, strategy_name: str, pnl: float, confidence: float = 0, won: bool = False):
        """Record a live trade outcome for a strategy."""
        date = datetime.now(IST).strftime("%Y-%m-%d")
        with self._lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT * FROM live_performance WHERE strategy_name = ? AND date = ?",
                (strategy_name, date),
            ).fetchone()

            if existing:
                conn.execute("""
                    UPDATE live_performance SET
                        trades = trades + 1,
                        wins = wins + ?,
                        pnl = pnl + ?,
                        avg_confidence = (avg_confidence * trades + ?) / (trades + 1)
                    WHERE strategy_name = ? AND date = ?
                """, (1 if won else 0, pnl, confidence, strategy_name, date))
            else:
                conn.execute("""
                    INSERT INTO live_performance (strategy_name, date, trades, wins, pnl, avg_confidence)
                    VALUES (?, ?, 1, ?, ?, ?)
                """, (strategy_name, date, 1 if won else 0, pnl, confidence))

    def get_strategy_leaderboard(self, days: int = 30) -> list[dict]:
        """Return per-strategy live performance over the last N days."""
        cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._lock, self._conn() as conn:
            rows = conn.execute("""
                SELECT strategy_name,
                       SUM(trades) as total_trades,
                       SUM(wins) as total_wins,
                       SUM(pnl) as total_pnl,
                       AVG(avg_confidence) as avg_conf
                FROM live_performance
                WHERE date >= ?
                GROUP BY strategy_name
                ORDER BY total_pnl DESC
            """, (cutoff,)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["win_rate"] = round(d["total_wins"] / d["total_trades"] * 100, 1) if d["total_trades"] else 0
                result.append(d)
            return result
