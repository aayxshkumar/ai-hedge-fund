"""Persistent tradebook — records every trade decision, execution, and outcome for model learning.

Stores trades in a SQLite database with full context: analyst signals, strategy scores,
technical indicators at entry/exit, P&L, and reasoning. This data can be used by the
model to learn what strategies and conditions produce profitable trades.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = Path(__file__).resolve().parents[2] / "outputs" / "tradebook.db"


class Tradebook:
    """Thread-safe persistent trade journal."""

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
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER DEFAULT 0,
                    price REAL DEFAULT 0,
                    order_type TEXT DEFAULT 'MARKET',
                    mode TEXT DEFAULT 'paper',

                    -- Decision context
                    confidence REAL DEFAULT 0,
                    decision_score REAL DEFAULT 0,
                    reasoning TEXT DEFAULT '',
                    strategy_scores TEXT DEFAULT '{}',
                    analyst_signals TEXT DEFAULT '{}',

                    -- Technical snapshot at entry
                    rsi REAL,
                    macd REAL,
                    ema50 REAL,
                    ema200 REAL,
                    trend TEXT,
                    volatility REAL,
                    volume_ratio REAL,

                    -- Execution result
                    order_id TEXT,
                    executed INTEGER DEFAULT 0,
                    execution_price REAL,
                    execution_msg TEXT DEFAULT '',

                    -- Outcome (filled when position is closed)
                    exit_price REAL,
                    exit_timestamp TEXT,
                    pnl REAL,
                    pnl_pct REAL,
                    holding_duration_hours REAL,
                    exit_reason TEXT,

                    -- Metadata
                    model_name TEXT DEFAULT '',
                    source TEXT DEFAULT 'auto_trader',
                    tags TEXT DEFAULT '[]',

                    -- F&O fields
                    instrument_type TEXT DEFAULT 'equity',
                    strategy_name TEXT DEFAULT '',
                    legs_json TEXT DEFAULT '[]',
                    underlying TEXT DEFAULT '',
                    expiry TEXT DEFAULT '',
                    margin_used REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS daily_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE NOT NULL,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    best_trade_ticker TEXT,
                    best_trade_pnl REAL DEFAULT 0,
                    worst_trade_ticker TEXT,
                    worst_trade_pnl REAL DEFAULT 0,
                    market_conditions TEXT DEFAULT '{}',
                    lessons TEXT DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
                CREATE INDEX IF NOT EXISTS idx_trades_action ON trades(action);
                CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_summary(date);
            """)

            self._migrate_fno_columns(conn)

            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_instrument ON trades(instrument_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_name)")
            except Exception:
                pass

    def _migrate_fno_columns(self, conn: sqlite3.Connection):
        """Add F&O columns if missing (idempotent migration)."""
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
            new_cols = {
                "instrument_type": "TEXT DEFAULT 'equity'",
                "strategy_name": "TEXT DEFAULT ''",
                "legs_json": "TEXT DEFAULT '[]'",
                "underlying": "TEXT DEFAULT ''",
                "expiry": "TEXT DEFAULT ''",
                "margin_used": "REAL DEFAULT 0",
            }
            for col, typedef in new_cols.items():
                if col not in cols:
                    conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {typedef}")
        except Exception as e:
            log.warning("F&O column migration: %s", e)

    def record_trade(self, trade: dict[str, Any]) -> int:
        """Record a new trade entry. Returns the trade ID."""
        now = datetime.now(IST).isoformat()
        with self._lock, self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO trades (
                    timestamp, ticker, action, side, quantity, price, order_type, mode,
                    confidence, decision_score, reasoning, strategy_scores, analyst_signals,
                    rsi, macd, ema50, ema200, trend, volatility, volume_ratio,
                    order_id, executed, execution_price, execution_msg,
                    model_name, source, tags,
                    instrument_type, strategy_name, legs_json, underlying, expiry, margin_used
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get("timestamp", now),
                trade.get("ticker", ""),
                trade.get("action", "hold"),
                trade.get("side", "BUY"),
                trade.get("quantity", 0),
                trade.get("price", 0),
                trade.get("order_type", "MARKET"),
                trade.get("mode", "paper"),
                trade.get("confidence", 0),
                trade.get("decision_score", 0),
                trade.get("reasoning", ""),
                json.dumps(trade.get("strategy_scores", {})),
                json.dumps(trade.get("analyst_signals", {})),
                trade.get("rsi"),
                trade.get("macd"),
                trade.get("ema50"),
                trade.get("ema200"),
                trade.get("trend"),
                trade.get("volatility"),
                trade.get("volume_ratio"),
                trade.get("order_id"),
                1 if trade.get("executed") else 0,
                trade.get("execution_price"),
                trade.get("execution_msg", ""),
                trade.get("model_name", ""),
                trade.get("source", "auto_trader"),
                json.dumps(trade.get("tags", [])),
                trade.get("instrument_type", "equity"),
                trade.get("strategy_name", ""),
                json.dumps(trade.get("legs", [])),
                trade.get("underlying", ""),
                trade.get("expiry", ""),
                trade.get("margin_used", 0),
            ))
            return cur.lastrowid

    def record_exit(self, trade_id: int, exit_price: float, exit_reason: str = ""):
        """Record exit for an open trade, computing P&L."""
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            if not row:
                return

            now = datetime.now(IST).isoformat()
            entry_price = row["execution_price"] or row["price"]
            qty = row["quantity"]
            side = row["side"]

            if side == "BUY":
                pnl = (exit_price - entry_price) * qty
            else:
                pnl = (entry_price - exit_price) * qty

            pnl_pct = ((exit_price / entry_price) - 1) * 100 if entry_price > 0 else 0
            if side == "SELL":
                pnl_pct = -pnl_pct

            entry_time = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            exit_time = datetime.now(IST)
            duration_hours = (exit_time - entry_time).total_seconds() / 3600

            conn.execute("""
                UPDATE trades SET
                    exit_price = ?, exit_timestamp = ?, pnl = ?, pnl_pct = ?,
                    holding_duration_hours = ?, exit_reason = ?
                WHERE id = ?
            """, (exit_price, now, round(pnl, 2), round(pnl_pct, 2), round(duration_hours, 2), exit_reason, trade_id))

    def get_trades(self, limit: int = 50, ticker: str | None = None,
                   action: str | None = None, only_open: bool = False) -> list[dict]:
        """Query trades with optional filters."""
        query = "SELECT * FROM trades WHERE 1=1"
        params: list = []
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if action:
            query += " AND action = ?"
            params.append(action)
        if only_open:
            query += " AND exit_price IS NULL AND executed = 1"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_performance_stats(self) -> dict:
        """Aggregate performance statistics for model learning."""
        with self._lock, self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM trades WHERE executed = 1").fetchone()["c"]
            closed = conn.execute("SELECT COUNT(*) as c FROM trades WHERE exit_price IS NOT NULL").fetchone()["c"]
            winners = conn.execute("SELECT COUNT(*) as c FROM trades WHERE pnl > 0").fetchone()["c"]
            losers = conn.execute("SELECT COUNT(*) as c FROM trades WHERE pnl < 0 AND exit_price IS NOT NULL").fetchone()["c"]
            total_pnl = conn.execute("SELECT COALESCE(SUM(pnl), 0) as s FROM trades WHERE exit_price IS NOT NULL").fetchone()["s"]
            avg_win = conn.execute("SELECT COALESCE(AVG(pnl), 0) as a FROM trades WHERE pnl > 0").fetchone()["a"]
            avg_loss = conn.execute("SELECT COALESCE(AVG(pnl), 0) as a FROM trades WHERE pnl < 0 AND exit_price IS NOT NULL").fetchone()["a"]
            sum_wins = conn.execute("SELECT COALESCE(SUM(pnl), 0) as s FROM trades WHERE pnl > 0").fetchone()["s"]
            sum_losses = conn.execute("SELECT COALESCE(SUM(pnl), 0) as s FROM trades WHERE pnl < 0 AND exit_price IS NOT NULL").fetchone()["s"]
            avg_duration = conn.execute("SELECT COALESCE(AVG(holding_duration_hours), 0) as a FROM trades WHERE exit_price IS NOT NULL").fetchone()["a"]

            best = conn.execute("SELECT ticker, pnl FROM trades WHERE pnl IS NOT NULL ORDER BY pnl DESC LIMIT 1").fetchone()
            worst = conn.execute("SELECT ticker, pnl FROM trades WHERE pnl IS NOT NULL ORDER BY pnl ASC LIMIT 1").fetchone()

            by_action = conn.execute("""
                SELECT action, COUNT(*) as count, COALESCE(SUM(pnl),0) as total_pnl,
                       COALESCE(AVG(pnl),0) as avg_pnl
                FROM trades WHERE exit_price IS NOT NULL GROUP BY action
            """).fetchall()

            by_ticker = conn.execute("""
                SELECT ticker, COUNT(*) as count, COALESCE(SUM(pnl),0) as total_pnl,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
                FROM trades WHERE exit_price IS NOT NULL GROUP BY ticker ORDER BY total_pnl DESC LIMIT 20
            """).fetchall()

            return {
                "total_trades": total,
                "closed_trades": closed,
                "open_trades": total - closed,
                "winning_trades": winners,
                "losing_trades": losers,
                "win_rate": round(winners / closed * 100, 1) if closed > 0 else 0,
                "total_pnl": round(total_pnl, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "profit_factor": round(sum_wins / abs(sum_losses), 2) if sum_losses != 0 else 0,
                "avg_holding_hours": round(avg_duration, 1),
                "best_trade": {"ticker": best["ticker"], "pnl": best["pnl"]} if best else None,
                "worst_trade": {"ticker": worst["ticker"], "pnl": worst["pnl"]} if worst else None,
                "by_action": [dict(r) for r in by_action],
                "by_ticker": [dict(r) for r in by_ticker],
            }

    def get_learning_context(self, ticker: str | None = None, limit: int = 10) -> str:
        """Generate a text summary of recent trades for model context/prompting."""
        trades = self.get_trades(limit=limit, ticker=ticker)
        stats = self.get_performance_stats()

        lines = [f"## Tradebook Summary (last {limit} trades)"]
        lines.append(f"Win rate: {stats['win_rate']}% | Total P&L: ₹{stats['total_pnl']:,.0f} | "
                      f"Avg win: ₹{stats['avg_win']:,.0f} | Avg loss: ₹{stats['avg_loss']:,.0f}")

        if stats.get("best_trade") and stats["best_trade"].get("pnl") is not None:
            lines.append(f"Best: {stats['best_trade']['ticker']} +₹{stats['best_trade']['pnl']:,.0f}")
        if stats.get("worst_trade") and stats["worst_trade"].get("pnl") is not None:
            lines.append(f"Worst: {stats['worst_trade']['ticker']} ₹{stats['worst_trade']['pnl']:,.0f}")

        lines.append("\n### Recent Trades")
        for t in trades[:limit]:
            pnl_str = f"P&L: ₹{t['pnl']:,.0f}" if t.get("pnl") is not None else "OPEN"
            lines.append(f"- {t['ticker']} {t['action']} x{t['quantity']} @ ₹{t['price']:,.2f} "
                          f"(conf: {t['confidence']:.0%}, RSI: {t.get('rsi', 'N/A')}) → {pnl_str}")
            if t.get("reasoning"):
                lines.append(f"  Reason: {t['reasoning'][:120]}")

        return "\n".join(lines)

    def record_daily_summary(self, date: str | None = None, lessons: str = ""):
        """Compute and store daily summary."""
        if not date:
            date = datetime.now(IST).strftime("%Y-%m-%d")

        with self._lock, self._conn() as conn:
            day_trades = conn.execute(
                "SELECT * FROM trades WHERE timestamp LIKE ? AND executed = 1", (f"{date}%",)
            ).fetchall()

            if not day_trades:
                return

            total = len(day_trades)
            closed = [t for t in day_trades if t["exit_price"] is not None]
            winners = [t for t in closed if (t["pnl"] or 0) > 0]
            losers = [t for t in closed if (t["pnl"] or 0) < 0]
            total_pnl = sum(t["pnl"] or 0 for t in closed)

            best = max(closed, key=lambda t: t["pnl"] or 0) if closed else None
            worst = min(closed, key=lambda t: t["pnl"] or 0) if closed else None

            conn.execute("""
                INSERT OR REPLACE INTO daily_summary
                (date, total_trades, winning_trades, losing_trades, total_pnl,
                 best_trade_ticker, best_trade_pnl, worst_trade_ticker, worst_trade_pnl, lessons)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date, total, len(winners), len(losers), round(total_pnl, 2),
                best["ticker"] if best else None, best["pnl"] if best else 0,
                worst["ticker"] if worst else None, worst["pnl"] if worst else 0,
                lessons,
            ))

    def get_daily_summaries(self, limit: int = 30) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_summary ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_strategy_performance(self, strategy_name: str, days: int = 30) -> dict:
        """Per-strategy performance over the last N days."""
        cutoff = (datetime.now(IST) - __import__("datetime").timedelta(days=days)).isoformat()
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE strategy_name = ? AND timestamp >= ? AND exit_price IS NOT NULL",
                (strategy_name, cutoff),
            ).fetchall()
            if not rows:
                return {"strategy": strategy_name, "trades": 0}
            wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
            total_pnl = sum(r["pnl"] or 0 for r in rows)
            avg_hold = sum(r["holding_duration_hours"] or 0 for r in rows) / len(rows) if rows else 0
            return {
                "strategy": strategy_name,
                "trades": len(rows),
                "wins": wins,
                "win_rate": round(wins / len(rows) * 100, 1) if rows else 0,
                "total_pnl": round(total_pnl, 2),
                "avg_holding_hours": round(avg_hold, 1),
            }

    def get_asset_class_performance(self, instrument_type: str = "equity", days: int = 30) -> dict:
        """Performance breakdown by asset class."""
        cutoff = (datetime.now(IST) - __import__("datetime").timedelta(days=days)).isoformat()
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE instrument_type = ? AND timestamp >= ? AND exit_price IS NOT NULL",
                (instrument_type, cutoff),
            ).fetchall()
            if not rows:
                return {"instrument_type": instrument_type, "trades": 0}
            wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
            total_pnl = sum(r["pnl"] or 0 for r in rows)
            return {
                "instrument_type": instrument_type,
                "trades": len(rows),
                "wins": wins,
                "win_rate": round(wins / len(rows) * 100, 1) if rows else 0,
                "total_pnl": round(total_pnl, 2),
            }

    def get_mistake_patterns(self, days: int = 14) -> list[dict]:
        """Identify repeated losing patterns (strategy + market regime)."""
        cutoff = (datetime.now(IST) - __import__("datetime").timedelta(days=days)).isoformat()
        with self._lock, self._conn() as conn:
            rows = conn.execute("""
                SELECT strategy_name, trend, instrument_type,
                       COUNT(*) as count, SUM(pnl) as total_loss
                FROM trades
                WHERE timestamp >= ? AND pnl < 0 AND exit_price IS NOT NULL
                GROUP BY strategy_name, trend, instrument_type
                HAVING count >= 2
                ORDER BY total_loss ASC
            """, (cutoff,)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("strategy_scores", "analyst_signals", "tags"):
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
