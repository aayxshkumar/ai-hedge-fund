"""Process-wide LLM availability status.

Command Code (and most gateways) enforce a rolling usage window. When a call
comes back 429 with a "resets at" timestamp, every further call in that window
is wasted - a 49-stock, 21-agent review would otherwise retry ~800 times into
the wall. Agents consult this before calling and the UI surfaces it."""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_state: dict = {"limited_until": None, "last_error": None, "last_error_at": None, "calls_ok": 0, "calls_failed": 0}

_RESET_RE = re.compile(r"resets? at (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)")


def note_success():
    with _lock:
        _state["calls_ok"] += 1


def note_error(exc: BaseException) -> bool:
    """Record an error; return True if it is a usage-window limit (do not retry)."""
    text = str(exc)
    with _lock:
        _state["calls_failed"] += 1
        _state["last_error"] = text[:300]
        _state["last_error_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if "rate_limit_error" in text or "usage limit" in text.lower() or "429" in text[:40]:
            m = _RESET_RE.search(text)
            if m:
                ts = m.group(1).replace("Z", "+00:00")
                try:
                    _state["limited_until"] = datetime.fromisoformat(ts).astimezone(timezone.utc).isoformat(timespec="seconds")
                except ValueError:
                    _state["limited_until"] = None
            return "usage limit" in text.lower() or m is not None
    return False


def limited_until() -> datetime | None:
    with _lock:
        v = _state["limited_until"]
    if not v:
        return None
    dt = datetime.fromisoformat(v)
    if dt <= datetime.now(timezone.utc):
        with _lock:
            _state["limited_until"] = None
        return None
    return dt


def is_limited() -> bool:
    return limited_until() is not None


def snapshot() -> dict:
    lu = limited_until()
    with _lock:
        return {**_state, "limited": lu is not None, "limited_until": lu.isoformat() if lu else None}
