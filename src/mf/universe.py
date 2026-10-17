"""The whole Indian open-ended equity/hybrid/index/overseas fund universe
(direct plan, growth option) with the same NAV metrics as the holdings, so a
held fund can be ranked against its peers instead of judged in isolation.

Built from AMFI NAVAll + mfapi.in; ~1,000 schemes, ~30 s cold, cached a day."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from src.mf.analyzer import CACHE_DIR, classify, fetch_nav_history, fund_metrics, load_amfi_map, theme_of

log = logging.getLogger(__name__)

UNIVERSE_FILE = CACHE_DIR / "universe.json"
UNIVERSE_TTL = 24 * 3600
CATEGORY_PREFIXES = ("Equity", "Other Scheme - Index", "Other Scheme - FoF Overseas", "Overseas",
                     "Hybrid Scheme - Aggressive", "Hybrid Scheme - Dynamic", "Hybrid Scheme - Multi Asset",
                     "Hybrid Scheme - Balanced Advantage", "Solution Oriented")
MIN_HISTORY_YEARS = 3.0


def build_universe(workers: int = 4, progress=None) -> dict:
    amfi = load_amfi_map()
    rows, seen = [], set()
    for isin, e in amfi.items():
        code = e.get("scheme_code")
        if not code or code in seen or e.get("plan") != "Direct Plan" or not str(e.get("option", "")).lower().startswith("growth"):
            continue
        if not str(e.get("category", "")).startswith(CATEGORY_PREFIXES):
            continue
        seen.add(code)
        rows.append({"scheme_code": code, "name": e["scheme_name"], "category": e["category"], "amc": e["amc"],
                     "isin": isin, "bucket": classify(e["category"], e["scheme_name"])})

    def one(r):
        try:
            m = fund_metrics(fetch_nav_history(r["scheme_code"]))
            m.pop("sparkline", None)
            r.update(m)
            r["ok"] = True
        except Exception as ex:
            r["ok"], r["error"] = False, str(ex)[:80]
        return r

    t0 = time.time()
    out = []
    with ThreadPoolExecutor(workers) as ex:
        for i, r in enumerate(ex.map(one, rows), 1):
            out.append(r)
            if progress and i % 100 == 0:
                progress(i, len(rows))
    data = {"as_of": datetime.now().isoformat(timespec="seconds"), "count": len(out), "seconds": round(time.time() - t0), "rows": out}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    UNIVERSE_FILE.write_text(json.dumps(data, default=str))
    return data


def load_universe(max_age: int = UNIVERSE_TTL, build_if_missing: bool = False) -> dict | None:
    if UNIVERSE_FILE.exists() and time.time() - UNIVERSE_FILE.stat().st_mtime < max_age:
        try:
            return json.loads(UNIVERSE_FILE.read_text())
        except Exception:
            pass
    if build_if_missing:
        return build_universe()
    # stale is better than nothing
    if UNIVERSE_FILE.exists():
        try:
            return json.loads(UNIVERSE_FILE.read_text())
        except Exception:
            return None
    return None


def _ratio(r: dict):
    c, v = r.get("cagr_3y"), r.get("vol_1y")
    return (c / v) if c is not None and v else None


def peers(universe: dict, bucket: str, min_years: float = MIN_HISTORY_YEARS, theme: str | None = None) -> list[dict]:
    rows = [r for r in universe.get("rows", []) if r.get("ok") and r.get("bucket") == bucket
            and r.get("cagr_3y") is not None and (r.get("history_years") or 0) >= min_years]
    if bucket == "Sectoral / Thematic" and theme:
        same = [r for r in rows if theme_of(r["name"]) == theme]
        if len(same) >= 5:
            return same
    return rows


def rank_fund(universe: dict | None, fund: dict) -> dict:
    """Percentile ranks of a held fund within its bucket (higher = better)."""
    if not universe:
        return {}
    theme = theme_of(fund.get("fund") or fund.get("name") or "") if fund.get("bucket") == "Sectoral / Thematic" else None
    ps = peers(universe, fund.get("bucket", ""), theme=theme)
    if len(ps) < 5:
        return {"peers": len(ps), "theme": theme}
    out = {"peers": len(ps), "theme": theme}
    for key, getter in (("cagr_3y", lambda r: r.get("cagr_3y")), ("ratio", _ratio), ("max_dd_3y", lambda r: r.get("max_dd_3y"))):
        mine = getter(fund)
        vals = [getter(r) for r in ps if getter(r) is not None]
        if mine is None or not vals:
            continue
        better = sum(1 for v in vals if v < mine)          # for drawdown "less negative" is better too
        out[f"{key}_pct"] = round(better / len(vals) * 100)
        s = sorted(vals)
        out[f"{key}_median"] = s[len(s) // 2]
    return out


def best_in_bucket(universe: dict | None, bucket: str, n: int = 5, exclude: set | None = None, theme: str | None = None) -> list[dict]:
    if not universe:
        return []
    ps = [r for r in peers(universe, bucket, theme=theme) if r["scheme_code"] not in (exclude or set())]
    ps.sort(key=lambda r: -(_ratio(r) or 0))
    return [{k: r.get(k) for k in ("scheme_code", "name", "amc", "cagr_3y", "cagr_5y", "ret_1y", "vol_1y", "max_dd_3y", "history_years")} | {"ratio": _ratio(r)} for r in ps[:n]]


def find(universe: dict | None, pattern: str, n: int = 10) -> list[dict]:
    import re
    if not universe:
        return []
    rx = re.compile(pattern, re.I)
    hits = [r for r in universe["rows"] if r.get("ok") and rx.search(r["name"]) and (r.get("cagr_3y") or 0) >= 0.08]
    hits.sort(key=lambda r: -(_ratio(r) or 0))
    return hits[:n]
