"""Hermes Bridge — routes all trading actions through Hermes for persistent learning.

Every significant action (trade, analysis, scan, review) is logged to Hermes memory
so the agent builds institutional knowledge over time.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

log = logging.getLogger(__name__)

_write_lock = threading.Lock()

IST = ZoneInfo("Asia/Kolkata")
MEMORY_DIR = Path.home() / ".hermes" / "memories"
TRADE_MEMORY = MEMORY_DIR / "trade_journal.md"
DAILY_DIGEST = MEMORY_DIR / "daily_digest.md"
STRATEGY_EVOLUTION = MEMORY_DIR / "strategy_evolution.md"


def _now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


def _append_memory(filepath: Path, content: str):
    """Append a timestamped entry to a Hermes memory file (thread-safe)."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with open(filepath, "a") as f:
            f.write(f"\n---\n### {_now_ist()}\n{content}\n")


def log_trade(trade: dict):
    """Log a trade execution to Hermes memory, including meta verdict context."""
    ticker = trade.get("ticker", "?")
    action = trade.get("action", "?")
    qty = trade.get("quantity", 0)
    price = trade.get("price", 0)
    confidence = trade.get("confidence", 0)
    reasoning = trade.get("reasoning", "")[:200]
    mode = trade.get("mode", "paper")
    executed = trade.get("executed", False)

    entry = (
        f"**TRADE {action.upper()}** {ticker} x{qty} @ ₹{price:,.2f} "
        f"(conf: {confidence:.0%}, mode: {mode}, executed: {executed})\n"
        f"Reasoning: {reasoning}"
    )

    meta = trade.get("meta_verdict")
    if meta:
        sb = meta.get("signal_breakdown", {})
        entry += (
            f"\nMeta Analyst: **{meta.get('action', '?').upper()}** "
            f"score={meta.get('score', 0):+.3f} conf={meta.get('confidence', 0):.0%} "
            f"({sb.get('bullish', 0)}B/{sb.get('bearish', 0)}S/{sb.get('neutral', 0)}N)"
        )

    _append_memory(TRADE_MEMORY, entry)
    log.info("[hermes] Logged trade: %s %s", action, ticker)


def log_analyst_review(review: dict):
    """Log a full analyst review (with Meta Analyst verdicts, swarm + options) to Hermes memory."""
    stocks = review.get("stocks_reviewed", [])
    verdicts = review.get("verdicts", {})
    summary = review.get("summary", "")

    n_agents = 0
    for v in verdicts.values():
        n_agents = max(n_agents, len(v.get("analyst_signals", {})))

    lines = [f"**PORTFOLIO ANALYST REVIEW** — {len(stocks)} stocks × {n_agents} agents (Meta Analyst + Swarm + Options)"]

    buys = sum(1 for v in verdicts.values() if "buy" in v.get("action", "").lower())
    sells = sum(1 for v in verdicts.values() if "sell" in v.get("action", "").lower())
    holds = len(verdicts) - buys - sells
    lines.append(f"**Verdict distribution**: {buys} Buy | {holds} Hold | {sells} Sell")

    for ticker, verdict in sorted(verdicts.items(), key=lambda x: -x[1].get("score", 0)):
        action = verdict.get("action", "hold")
        conf = verdict.get("confidence", 0)
        score = verdict.get("score", 0)
        reason = verdict.get("reasoning", "")[:200]
        sb = verdict.get("signal_breakdown", {})
        breakdown = f"({sb.get('bullish', 0)}B/{sb.get('bearish', 0)}S/{sb.get('neutral', 0)}N)" if sb else ""

        swarm = verdict.get("analyst_signals", {}).get("swarm_analyst_agent", {})
        swarm_note = ""
        if swarm:
            swarm_note = f" | Swarm: {swarm.get('signal', '?')} ({swarm.get('confidence', 0)}%)"

        options = verdict.get("analyst_signals", {}).get("options_analyst_agent", {})
        options_note = ""
        if options:
            options_note = f" | Options: {options.get('signal', '?')} ({options.get('confidence', 0)})"

        lines.append(
            f"- {ticker}: **{action.upper()}** score={score:+.3f} conf={conf:.0%} {breakdown}"
            f"{swarm_note}{options_note}\n  _{reason}_"
        )

    if summary:
        lines.append(f"\n**Summary**: {summary}")

    _append_memory(TRADE_MEMORY, "\n".join(lines))
    log.info("[hermes] Logged analyst review for %d stocks (%d agents)", len(stocks), n_agents)


def log_scan_results(results: list[dict]):
    """Log scanner results to Hermes memory."""
    lines = [f"**SCANNER** — {len(results)} stocks qualified"]
    for r in results[:10]:
        lines.append(f"- {r.get('ticker', '?')}: score={r.get('score', 0):.1f}, "
                      f"vol={r.get('volatility', 0):.1f}%, trend={r.get('trend', '?')}")
    _append_memory(TRADE_MEMORY, "\n".join(lines))


def log_daily_digest(stats: dict, portfolio_summary: dict | None = None, lessons: str = ""):
    """Log end-of-day digest combining tradebook stats + portfolio."""
    lines = [f"**END OF DAY DIGEST**"]

    if stats:
        lines.append(f"Win rate: {stats.get('win_rate', 0)}% | Total P&L: ₹{stats.get('total_pnl', 0):,.0f}")
        lines.append(f"Trades today: {stats.get('total_trades', 0)} | "
                      f"Open: {stats.get('open_trades', 0)} | "
                      f"Profit factor: {stats.get('profit_factor', 0):.2f}")

    if portfolio_summary:
        lines.append(f"Portfolio: ₹{portfolio_summary.get('portfolio_value', 0):,.0f} | "
                      f"P&L: ₹{portfolio_summary.get('total_pnl', 0):,.0f} "
                      f"({portfolio_summary.get('total_pnl_pct', 0):+.1f}%)")

    if lessons:
        lines.append(f"\n**Lessons**: {lessons}")

    _append_memory(DAILY_DIGEST, "\n".join(lines))
    log.info("[hermes] Daily digest recorded")


def log_penny_scan(results: list[dict]):
    """Log penny scanner results with momentum details to Hermes memory."""
    lines = [f"**PENNY SCANNER** — {len(results)} momentum candidates found"]
    for r in results[:10]:
        ticker = r.get("ticker", "?")
        price = r.get("last_close", 0)
        target = r.get("target_price", 0)
        horizon = r.get("time_horizon", "?")
        mom = r.get("momentum_5d", 0)
        vol = r.get("relative_volume", 1)
        score = r.get("score", 0)
        lines.append(
            f"- {ticker}: ₹{price:.2f} → ₹{target:.2f} ({horizon}) "
            f"mom5d={mom:+.1f}% vol={vol:.1f}x score={score:.0f}"
        )
    _append_memory(TRADE_MEMORY, "\n".join(lines))
    log.info("[hermes] Logged penny scan: %d results", len(results))


def log_daily_analysis(report: dict):
    """Log the daily analysis report to Hermes memory."""
    mkt = report.get("market_overview", {})
    vs = report.get("verdict_summary", {})
    penny = report.get("penny_picks", [])
    targets = report.get("target_signals", [])
    balance = report.get("portfolio_balance", {})

    lines = [f"**DAILY ANALYSIS REPORT**"]
    lines.append(f"Market: {mkt.get('index', 'NIFTY')} {mkt.get('trend', '?')} "
                 f"({mkt.get('change_1d_pct', 0):+.1f}% 1d, {mkt.get('change_5d_pct', 0):+.1f}% 5d)")

    if vs.get("total"):
        lines.append(f"Verdicts: {vs['buys']}B / {vs['holds']}H / {vs['sells']}S out of {vs['total']}")

    if penny:
        lines.append(f"Penny picks: {len(penny)} — top: {', '.join(p.get('ticker', '?').replace('.NS','') for p in penny[:5])}")

    if targets:
        lines.append(f"Target signals: {len(targets)} stocks with targets")
        for t in targets[:3]:
            lines.append(f"  {t.get('ticker', '?')}: {t.get('signal', '?')} "
                         f"target={t.get('target_price', 0):.2f} horizon={t.get('time_horizon', '?')}")

    if balance.get("current_allocation"):
        ca = balance["current_allocation"]
        lines.append(f"Portfolio balance: L={ca.get('large', 0)}% M={ca.get('mid', 0)}% S={ca.get('small', 0)}% "
                     f"(recommended: {balance.get('recommended_profile', '?')})")

    picks = balance.get("short_term_picks", [])
    if picks:
        lines.append(f"Short-term picks: {', '.join(p.get('ticker', '?').replace('.NS','') for p in picks[:5])}")

    _append_memory(TRADE_MEMORY, "\n".join(lines))
    log.info("[hermes] Logged daily analysis report")


def log_rebalance(result: dict):
    """Log portfolio rebalance suggestions to Hermes memory."""
    ca = result.get("current_allocation", {})
    profile = result.get("recommended_profile", "balanced")
    suggestions = result.get("suggestions", [])
    picks = result.get("short_term_picks", [])

    lines = [f"**PORTFOLIO REBALANCE** — Profile: {profile}"]
    lines.append(f"Current: L={ca.get('large', 0)}% M={ca.get('mid', 0)}% S={ca.get('small', 0)}%")

    for s in suggestions:
        lines.append(f"- {s.get('action', '?').upper()}: {s.get('ticker', '')} — {s.get('reason', '')}")

    if picks:
        lines.append(f"Short-term additions: {', '.join(p.get('ticker', '?') for p in picks)}")

    _append_memory(TRADE_MEMORY, "\n".join(lines))
    log.info("[hermes] Logged rebalance suggestions")


def log_action(action_type: str, details: str):
    """Log any significant action for Hermes learning."""
    _append_memory(TRADE_MEMORY, f"**{action_type.upper()}**: {details}")


def build_session_context(tradebook=None) -> str:
    """Assemble full context for the Hermes strategy advisor.

    Reads tradebook performance, daily summaries, market regime, and
    recent memory so the LLM can make informed strategy allocation decisions.
    """
    sections: list[str] = []

    # 1. Tradebook performance stats
    if tradebook is not None:
        try:
            stats = tradebook.get_performance_stats()
            sections.append(
                "## Tradebook Performance\n"
                f"Win rate: {stats.get('win_rate', 0)}% | Total P&L: ₹{stats.get('total_pnl', 0):,.0f}\n"
                f"Avg win: ₹{stats.get('avg_win', 0):,.0f} | Avg loss: ₹{stats.get('avg_loss', 0):,.0f}\n"
                f"Profit factor: {stats.get('profit_factor', 0):.2f} | "
                f"Avg holding: {stats.get('avg_holding_hours', 0):.1f}h\n"
                f"Total trades: {stats.get('total_trades', 0)} | "
                f"Open: {stats.get('open_trades', 0)} | "
                f"Closed: {stats.get('closed_trades', 0)}"
            )

            by_action = stats.get("by_action", [])
            if by_action:
                lines = ["### By Action"]
                for a in by_action:
                    lines.append(f"- {a['action']}: {a['count']} trades, P&L ₹{a['total_pnl']:,.0f}")
                sections.append("\n".join(lines))

            by_ticker = stats.get("by_ticker", [])
            if by_ticker:
                lines = ["### Top Tickers"]
                for t in by_ticker[:10]:
                    lines.append(f"- {t['ticker']}: {t['count']} trades, P&L ₹{t['total_pnl']:,.0f}, {t.get('wins', 0)} wins")
                sections.append("\n".join(lines))
        except Exception as e:
            log.warning("Failed to load tradebook stats for context: %s", e)

    # 2. Recent daily summaries / lessons
    if tradebook is not None:
        try:
            summaries = tradebook.get_daily_summaries(limit=5)
            if summaries:
                lines = ["## Recent Daily Summaries"]
                for s in summaries:
                    lines.append(
                        f"- {s['date']}: {s['total_trades']} trades, "
                        f"{s['winning_trades']}W/{s['losing_trades']}L, "
                        f"P&L ₹{s.get('total_pnl', 0):,.0f}"
                    )
                    if s.get("lessons"):
                        lines.append(f"  Lessons: {s['lessons'][:200]}")
                sections.append("\n".join(lines))
        except Exception as e:
            log.warning("Failed to load daily summaries: %s", e)

    # 3. Per-strategy performance from recent trades
    if tradebook is not None:
        try:
            recent = tradebook.get_trades(limit=100)
            strategy_stats: dict[str, dict] = {}
            for t in recent:
                scores = t.get("strategy_scores", {})
                if isinstance(scores, str):
                    try:
                        scores = json.loads(scores)
                    except Exception:
                        scores = {}
                for sname, sval in scores.items():
                    if sname not in strategy_stats:
                        strategy_stats[sname] = {"count": 0, "wins": 0, "total_pnl": 0.0}
                    strategy_stats[sname]["count"] += 1
                    pnl = t.get("pnl") or 0
                    strategy_stats[sname]["total_pnl"] += pnl
                    if pnl > 0:
                        strategy_stats[sname]["wins"] += 1

            if strategy_stats:
                lines = ["## Strategy Performance (last 100 trades)"]
                for sname, ss in sorted(strategy_stats.items(), key=lambda x: -x[1]["total_pnl"]):
                    wr = (ss["wins"] / ss["count"] * 100) if ss["count"] else 0
                    lines.append(f"- {sname}: {ss['count']} trades, WR {wr:.0f}%, P&L ₹{ss['total_pnl']:,.0f}")
                sections.append("\n".join(lines))
        except Exception as e:
            log.warning("Failed to compute strategy stats: %s", e)

    # 4. Market regime from latest daily analysis
    try:
        daily_file = Path(__file__).resolve().parents[2] / "outputs" / "daily_analysis.json"
        if daily_file.exists():
            data = json.loads(daily_file.read_text())
            mkt = data.get("market_overview", {})
            vs = data.get("verdict_summary", {})
            sections.append(
                "## Current Market Regime\n"
                f"Index: {mkt.get('index', 'NIFTY')} | Trend: {mkt.get('trend', 'unknown')}\n"
                f"1D: {mkt.get('change_1d_pct', 0):+.1f}% | 5D: {mkt.get('change_5d_pct', 0):+.1f}%\n"
                f"Verdicts: {vs.get('buys', 0)}B / {vs.get('holds', 0)}H / {vs.get('sells', 0)}S"
            )
    except Exception as e:
        log.warning("Failed to load market regime: %s", e)

    # 5. Recent Hermes memory tail
    try:
        if TRADE_MEMORY.exists():
            text = TRADE_MEMORY.read_text()
            lines = text.strip().split("\n")
            tail = lines[-60:] if len(lines) > 60 else lines
            sections.append("## Recent Trade Journal (tail)\n" + "\n".join(tail))
    except Exception as e:
        log.warning("Failed to read trade memory: %s", e)

    # 6. Strategy evolution history
    try:
        if STRATEGY_EVOLUTION.exists():
            text = STRATEGY_EVOLUTION.read_text()
            lines = text.strip().split("\n")
            tail = lines[-30:] if len(lines) > 30 else lines
            sections.append("## Strategy Evolution History\n" + "\n".join(tail))
    except Exception as e:
        log.warning("Failed to read strategy evolution: %s", e)

    return "\n\n".join(sections) if sections else "No historical context available — first session."


def write_session_review(session_stats: dict):
    """Post-session: analyze what worked, write lessons, update strategy evolution."""
    trades = session_stats.get("trades", [])
    strategy_pnl: dict[str, float] = {}
    asset_pnl: dict[str, float] = {}
    mistakes: list[str] = []

    for t in trades:
        pnl = t.get("pnl") or 0
        sname = t.get("strategy_name", "unknown")
        itype = t.get("instrument_type", "equity")
        strategy_pnl[sname] = strategy_pnl.get(sname, 0) + pnl
        asset_pnl[itype] = asset_pnl.get(itype, 0) + pnl

        if pnl < -500:
            mistakes.append(
                f"Loss ₹{pnl:,.0f} on {t.get('ticker', '?')} "
                f"via {sname} ({itype}) — {t.get('exit_reason', 'unknown')}"
            )

    lines = ["**SESSION REVIEW**"]
    lines.append(f"Trades: {len(trades)} | "
                 f"Total P&L: ₹{sum(t.get('pnl', 0) or 0 for t in trades):,.0f}")

    if strategy_pnl:
        lines.append("\n**By Strategy:**")
        for sn, pnl in sorted(strategy_pnl.items(), key=lambda x: -x[1]):
            lines.append(f"  {sn}: ₹{pnl:+,.0f}")

    if asset_pnl:
        lines.append("\n**By Asset Class:**")
        for ac, pnl in sorted(asset_pnl.items(), key=lambda x: -x[1]):
            lines.append(f"  {ac}: ₹{pnl:+,.0f}")

    if mistakes:
        lines.append(f"\n**Mistakes ({len(mistakes)}):**")
        for m in mistakes[:5]:
            lines.append(f"  - {m}")

    lessons = session_stats.get("lessons", "")
    if lessons:
        lines.append(f"\n**Lessons:** {lessons}")

    _append_memory(TRADE_MEMORY, "\n".join(lines))

    # Update strategy evolution log
    if strategy_pnl:
        evo_lines = [f"**STRATEGY WEIGHTS UPDATE** — Session {_now_ist()}"]
        weights = session_stats.get("strategy_weights", {})
        if weights:
            for sn, w in sorted(weights.items(), key=lambda x: -x[1]):
                pnl = strategy_pnl.get(sn, 0)
                evo_lines.append(f"  {sn}: weight={w:.2f}, session_pnl=₹{pnl:+,.0f}")
        _append_memory(STRATEGY_EVOLUTION, "\n".join(evo_lines))

    log.info("[hermes] Session review written — %d trades, %d strategies", len(trades), len(strategy_pnl))


def invoke_hermes(task: str) -> str | None:
    """Invoke Hermes CLI for a task and return its response."""
    try:
        result = subprocess.run(
            ["hermes", "run", "--task", task],
            capture_output=True, text=True, timeout=120,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        if result.returncode == 0:
            return result.stdout.strip()
        log.warning("[hermes] CLI returned %d: %s", result.returncode, result.stderr[:200])
        return None
    except FileNotFoundError:
        log.warning("[hermes] CLI not found — falling back to direct execution")
        return None
    except subprocess.TimeoutExpired:
        log.warning("[hermes] CLI timed out")
        return None
    except Exception as e:
        log.warning("[hermes] CLI error: %s", e)
        return None
