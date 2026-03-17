"""Messaging Notifier — sends portfolio alerts via OpenClaw (Telegram / WhatsApp).

Uses ``openclaw message send --channel <channel>`` to deliver formatted messages
at 9:15 IST (pre-market), 12:00 IST (midday), and 3:30 IST (closing).

Telegram setup:
  1. Create a bot via @BotFather on Telegram
  2. openclaw config set channels.telegram.botToken "<TOKEN>"
  3. openclaw config set channels.telegram.enabled true
  4. Set TELEGRAM_TARGET=<chat_id> in .env (numeric chat ID, not phone number)
  5. Set OPENCLAW_ENABLED=true in .env

WhatsApp setup (legacy):
  1. openclaw channels login --channel whatsapp
  2. Set OPENCLAW_CHANNEL=whatsapp and WHATSAPP_TARGET=+91... in .env
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
OUTPUTS_DIR = Path(__file__).resolve().parents[2] / "outputs"


def _is_enabled() -> bool:
    return os.getenv("OPENCLAW_ENABLED", "").lower() in ("true", "1", "yes")


def _channel() -> str:
    return os.getenv("OPENCLAW_CHANNEL", "telegram").lower()


def _target() -> str | None:
    ch = _channel()
    if ch == "telegram":
        return os.getenv("TELEGRAM_TARGET")
    return os.getenv("WHATSAPP_TARGET")


def send_message(message: str) -> bool:
    """Send a message via OpenClaw CLI on the configured channel. Returns True on success."""
    if not _is_enabled():
        log.debug("OpenClaw disabled — skipping message send")
        return False

    target = _target()
    channel = _channel()
    if not target:
        log.warning("%s target not set — cannot send", channel.upper())
        return False

    try:
        result = subprocess.run(
            ["openclaw", "message", "send",
             "--channel", channel,
             "--target", target,
             "--message", message],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            log.info("%s message sent to %s (%d chars)", channel, target, len(message))
            return True
        log.warning("openclaw send failed (code %d): %s", result.returncode, result.stderr[:200])
        return False
    except FileNotFoundError:
        log.warning("openclaw CLI not found — install OpenClaw to enable messaging")
        return False
    except subprocess.TimeoutExpired:
        log.warning("openclaw send timed out")
        return False
    except Exception as e:
        log.error("%s send error: %s", channel, e)
        return False


# Backward-compat alias
send_whatsapp = send_message


def _load_json(filename: str) -> dict:
    fp = OUTPUTS_DIR / filename
    if fp.exists():
        try:
            return json.loads(fp.read_text())
        except Exception:
            pass
    return {}


def _now_ist() -> datetime:
    return datetime.now(IST)


def format_pre_market_msg() -> str:
    """9:15 IST — Portfolio overview + watchlist."""
    review = _load_json("portfolio_review.json")
    daily = _load_json("daily_analysis.json")

    lines = [f"*Pre-Market Brief* — {_now_ist().strftime('%d %b %Y, %H:%M IST')}"]
    lines.append("")

    verdicts = review.get("verdicts", {})
    if verdicts:
        buys = sum(1 for v in verdicts.values() if "buy" in str(v.get("action", "")).lower())
        sells = sum(1 for v in verdicts.values() if "sell" in str(v.get("action", "")).lower())
        holds = len(verdicts) - buys - sells
        lines.append(f"Portfolio: {len(verdicts)} stocks — {buys} Buy | {holds} Hold | {sells} Sell")

        top_buys = [t.replace(".NS", "") for t, v in sorted(
            verdicts.items(), key=lambda x: x[1].get("score", 0), reverse=True
        ) if "buy" in str(v.get("action", "")).lower()][:3]
        if top_buys:
            lines.append(f"Top buys: {', '.join(top_buys)}")

        top_sells = [t.replace(".NS", "") for t, v in sorted(
            verdicts.items(), key=lambda x: x[1].get("score", 0)
        ) if "sell" in str(v.get("action", "")).lower()][:3]
        if top_sells:
            lines.append(f"Top sells: {', '.join(top_sells)}")

    mkt = daily.get("market_overview", {})
    if mkt:
        lines.append(f"\nMarket: {mkt.get('index', 'NIFTY')} {mkt.get('trend', '?')} "
                     f"({mkt.get('change_1d_pct', 0):+.1f}%)")

    penny = daily.get("penny_picks", [])
    if penny:
        lines.append(f"\nPenny watchlist: {', '.join(p.get('ticker', '?').replace('.NS','') for p in penny[:5])}")

    return "\n".join(lines)


def format_midday_msg() -> str:
    """12:00 IST — Review results + signal changes."""
    review = _load_json("portfolio_review.json")

    lines = [f"*Midday Update* — {_now_ist().strftime('%d %b, %H:%M IST')}"]
    lines.append("")

    verdicts = review.get("verdicts", {})
    if verdicts:
        buys = sum(1 for v in verdicts.values() if "buy" in str(v.get("action", "")).lower())
        sells = sum(1 for v in verdicts.values() if "sell" in str(v.get("action", "")).lower())
        holds = len(verdicts) - buys - sells
        lines.append(f"AI Review: {buys}B / {holds}H / {sells}S ({len(verdicts)} stocks)")

        changes = review.get("changes", {})
        if changes:
            flips = changes.get("signal_flips", [])
            if flips:
                lines.append(f"\nSignal changes ({len(flips)}):")
                for f in flips[:5]:
                    lines.append(f"  {f['ticker'].replace('.NS','')}: {f['from']} → {f['to']}")

            movers = changes.get("biggest_movers", [])
            if movers:
                lines.append(f"\nBiggest movers:")
                for m in movers[:3]:
                    arrow = "↑" if m["direction"] == "up" else "↓" if m["direction"] == "down" else "→"
                    lines.append(f"  {m['ticker'].replace('.NS','')} {arrow} {m['delta']:+.3f}")
    else:
        lines.append("No review data available yet.")

    return "\n".join(lines)


def format_closing_msg() -> str:
    """3:30 IST — Daily analysis summary."""
    daily = _load_json("daily_analysis.json")
    review = _load_json("portfolio_review.json")
    rebalance = _load_json("rebalance_analysis.json")

    lines = [f"*Closing Summary* — {_now_ist().strftime('%d %b, %H:%M IST')}"]
    lines.append("")

    vs = daily.get("verdict_summary", {})
    if vs.get("total"):
        lines.append(f"Verdicts: {vs['buys']}B / {vs['holds']}H / {vs['sells']}S out of {vs['total']}")

    mkt = daily.get("market_overview", {})
    if mkt:
        lines.append(f"Market: {mkt.get('trend', '?')} ({mkt.get('change_1d_pct', 0):+.1f}% today)")

    penny = daily.get("penny_picks", [])
    if penny:
        lines.append(f"\nPenny picks ({len(penny)}):")
        for p in penny[:5]:
            lines.append(f"  {p.get('ticker', '?').replace('.NS','')} ₹{p.get('last_close', 0):.2f} "
                        f"→ ₹{p.get('target_price', 0):.2f} ({p.get('time_horizon', '?')})")

    balance = daily.get("portfolio_balance", {}) or rebalance
    if balance.get("suggestions"):
        lines.append(f"\nRebalance suggestions:")
        for s in balance["suggestions"][:3]:
            lines.append(f"  {s.get('action', '?').upper()}: {s.get('ticker', '')} — {s.get('reason', '')}")

    picks = balance.get("short_term_picks", [])
    if picks:
        lines.append(f"\nShort-term picks: {', '.join(p.get('ticker', '?').replace('.NS','') for p in picks[:5])}")

    targets = daily.get("target_signals", [])
    if targets:
        lines.append(f"\nTarget signals ({len(targets)}):")
        for t in targets[:3]:
            lines.append(f"  {t.get('ticker', '?').replace('.NS','')}: "
                        f"{t.get('signal', '?')} target=₹{t.get('target_price', 0):.0f} "
                        f"({t.get('time_horizon', '?')})")

    return "\n".join(lines)
