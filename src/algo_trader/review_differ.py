"""Review Differ — saves review snapshots and computes structured diffs between scans.

Keeps up to MAX_SNAPSHOTS timestamped review files and produces a diff dict
describing signal flips, score changes, ticker additions/removals, and top movers.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

HISTORY_DIR = Path(__file__).resolve().parents[2] / "outputs" / "review_history"
MAX_SNAPSHOTS = 30


def save_review_snapshot(review: dict) -> Path:
    """Persist a timestamped copy of the review and prune old snapshots."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    ts = review.get("review_time") or review.get("timestamp") or datetime.utcnow().isoformat()
    safe_ts = str(ts).replace(":", "-").replace("+", "_")
    filepath = HISTORY_DIR / f"review_{safe_ts}.json"

    with open(filepath, "w") as f:
        json.dump(review, f, indent=2, default=str)

    _prune_old_snapshots()
    log.info("Saved review snapshot: %s", filepath.name)
    return filepath


def _prune_old_snapshots():
    snapshots = sorted(HISTORY_DIR.glob("review_*.json"), key=lambda p: p.stat().st_mtime)
    while len(snapshots) > MAX_SNAPSHOTS:
        old = snapshots.pop(0)
        old.unlink(missing_ok=True)
        log.debug("Pruned old snapshot: %s", old.name)


def list_snapshots() -> list[dict]:
    """Return metadata for all stored snapshots, newest first."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for p in sorted(HISTORY_DIR.glob("review_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text())
            verdicts = data.get("verdicts", {})
            buys = sum(1 for v in verdicts.values() if "buy" in str(v.get("action", "")).lower())
            sells = sum(1 for v in verdicts.values() if "sell" in str(v.get("action", "")).lower())
            holds = len(verdicts) - buys - sells
            result.append({
                "filename": p.name,
                "timestamp": data.get("review_time") or data.get("timestamp"),
                "stocks_reviewed": data.get("stocks_reviewed", len(verdicts)),
                "model_used": data.get("model_used", "unknown"),
                "buys": buys,
                "sells": sells,
                "holds": holds,
            })
        except Exception:
            continue
    return result


def load_snapshot_by_filename(filename: str) -> dict | None:
    filepath = (HISTORY_DIR / filename).resolve()
    if not str(filepath).startswith(str(HISTORY_DIR.resolve())):
        log.warning("Blocked path traversal attempt: %s", filename)
        return None
    if filepath.exists():
        return json.loads(filepath.read_text())
    return None


def load_previous_review() -> dict | None:
    """Load the second-most-recent snapshot (the one before the current scan)."""
    snapshots = sorted(HISTORY_DIR.glob("review_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if len(snapshots) < 2:
        return None
    try:
        return json.loads(snapshots[1].read_text())
    except Exception:
        return None


def load_review_at(index: int) -> dict | None:
    """Load the Nth most recent snapshot (0 = latest, 1 = previous, etc.)."""
    snapshots = sorted(HISTORY_DIR.glob("review_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if index < 0 or index >= len(snapshots):
        return None
    try:
        return json.loads(snapshots[index].read_text())
    except Exception:
        return None


def _action_bucket(action: str) -> str:
    a = (action or "hold").lower()
    if "strong" in a and "buy" in a:
        return "strong_buy"
    if "buy" in a:
        return "buy"
    if "strong" in a and "sell" in a:
        return "strong_sell"
    if "sell" in a:
        return "sell"
    return "hold"


def diff_reviews(current: dict, previous: dict) -> dict:
    """Compute a structured diff between two review snapshots.

    Returns dict with keys: signal_flips, score_changes, new_tickers,
    removed_tickers, biggest_movers, summary.
    """
    cur_verdicts = current.get("verdicts", {})
    prev_verdicts = previous.get("verdicts", {})

    cur_tickers = set(cur_verdicts.keys())
    prev_tickers = set(prev_verdicts.keys())

    new_tickers = sorted(cur_tickers - prev_tickers)
    removed_tickers = sorted(prev_tickers - cur_tickers)
    common = cur_tickers & prev_tickers

    signal_flips: list[dict] = []
    score_changes: list[dict] = []

    for ticker in sorted(common):
        cv = cur_verdicts[ticker]
        pv = prev_verdicts[ticker]

        cur_action = _action_bucket(cv.get("action", "hold"))
        prev_action = _action_bucket(pv.get("action", "hold"))

        cur_score = cv.get("score", 0) or 0
        prev_score = pv.get("score", 0) or 0
        delta = cur_score - prev_score

        cur_conf = cv.get("confidence", 0) or 0
        prev_conf = pv.get("confidence", 0) or 0
        conf_delta = cur_conf - prev_conf

        if cur_action != prev_action:
            signal_flips.append({
                "ticker": ticker,
                "from": prev_action,
                "to": cur_action,
                "score_delta": round(delta, 4),
                "prev_score": round(prev_score, 4),
                "cur_score": round(cur_score, 4),
            })

        score_changes.append({
            "ticker": ticker,
            "prev_score": round(prev_score, 4),
            "cur_score": round(cur_score, 4),
            "delta": round(delta, 4),
            "direction": "up" if delta > 0.001 else ("down" if delta < -0.001 else "flat"),
            "confidence_delta": round(conf_delta, 4),
        })

    score_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)
    biggest_movers = score_changes[:5]

    n_flips = len(signal_flips)
    n_improved = sum(1 for s in score_changes if s["direction"] == "up")
    n_declined = sum(1 for s in score_changes if s["direction"] == "down")

    return {
        "signal_flips": signal_flips,
        "score_changes": score_changes,
        "new_tickers": new_tickers,
        "removed_tickers": removed_tickers,
        "biggest_movers": biggest_movers,
        "summary": {
            "total_compared": len(common),
            "signal_flips": n_flips,
            "improved": n_improved,
            "declined": n_declined,
            "new_count": len(new_tickers),
            "removed_count": len(removed_tickers),
        },
        "current_timestamp": current.get("review_time") or current.get("timestamp"),
        "previous_timestamp": previous.get("review_time") or previous.get("timestamp"),
    }
