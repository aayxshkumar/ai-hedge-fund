"""Mutual-fund portfolio analytics.

Data sources (all read-only):
  * Kite Connect ``mf_holdings()`` — what the user actually holds (ISIN, units,
    average NAV, current NAV, XIRR).
  * AMFI NAVAll.txt — maps ISIN -> scheme code and gives the SEBI category
    (section headers such as "Equity Scheme - Mid Cap Fund").
  * mfapi.in — full NAV history per scheme code, used for CAGR, volatility,
    drawdown and a sparkline.

Everything is cached on disk under outputs/mf_cache so the page is fast and we
are polite to the free endpoints.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "outputs" / "mf_cache"
AMFI_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
MFAPI_URL = "https://api.mfapi.in/mf/{code}"
AMFI_TTL = 24 * 3600
NAV_TTL = 12 * 3600
RISK_FREE = 0.065          # ~ India 1y T-bill, for Sharpe
TRADING_DAYS = 252


# ── AMFI master: ISIN -> scheme code + category ─────────────────────────────

def _cached_text(path: Path, url: str, ttl: int) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        return path.read_text(encoding="utf-8", errors="replace")
    r = requests.get(url, timeout=60, headers={"User-Agent": "ai-hedge-fund/1.0"})
    r.raise_for_status()
    path.write_text(r.text, encoding="utf-8")
    return r.text


def load_amfi_map() -> dict[str, dict]:
    """ISIN -> {scheme_code, scheme_name, category, amc, nav, nav_date}."""
    text = _cached_text(CACHE_DIR / "navall.txt", AMFI_URL, AMFI_TTL)
    out: dict[str, dict] = {}
    category = ""
    amc = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        if ";" not in line:
            m = re.match(r"^(Open|Close|Interval) Ended Schemes\s*\((.*)\)\s*$", line)
            if m:
                category = m.group(2).strip()
            else:
                amc = line
            continue
        parts = line.split(";")
        if len(parts) < 8:
            continue
        code, isin_g, isin_r, name, plan, option, nav, date = parts[:8]
        entry = {
            "scheme_code": int(code) if code.isdigit() else None,
            "scheme_name": name.strip(),
            "plan": plan.strip(),
            "option": option.strip(),
            "category": category,
            "amc": amc,
            "nav": _f(nav),
            "nav_date": date.strip(),
        }
        for isin in (isin_g, isin_r):
            isin = isin.strip()
            if isin and isin != "-":
                out[isin] = entry
    return out


def _f(x) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ── NAV history ─────────────────────────────────────────────────────────────

def fetch_nav_history(scheme_code: int) -> pd.DataFrame:
    """Daily NAV series (index = date, column 'nav'), oldest first."""
    path = CACHE_DIR / f"nav_{scheme_code}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = None
    if path.exists() and time.time() - path.stat().st_mtime < NAV_TTL:
        data = json.loads(path.read_text())
    else:
        try:
            r = requests.get(MFAPI_URL.format(code=scheme_code), timeout=60)
            r.raise_for_status()
            data = r.json()
            path.write_text(json.dumps(data))
        except Exception as e:
            log.warning("mfapi fetch failed for %s: %s", scheme_code, e)
            if path.exists():
                data = json.loads(path.read_text())
    rows = (data or {}).get("data") or []
    if not rows:
        return pd.DataFrame(columns=["nav"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    df = df.dropna().sort_values("date").set_index("date")
    return df[["nav"]]


# ── Metrics ─────────────────────────────────────────────────────────────────

def _cagr(series: pd.Series, years: float) -> float | None:
    if series.empty:
        return None
    end = series.index[-1]
    start_target = end - pd.Timedelta(days=int(365.25 * years))
    before = series[series.index <= start_target]
    if before.empty:
        return None
    start_val = float(before.iloc[-1])
    end_val = float(series.iloc[-1])
    actual_years = (end - before.index[-1]).days / 365.25
    if start_val <= 0 or actual_years < years * 0.9:
        return None
    return (end_val / start_val) ** (1 / actual_years) - 1


def _period_return(series: pd.Series, days: int) -> float | None:
    if series.empty:
        return None
    end = series.index[-1]
    before = series[series.index <= end - pd.Timedelta(days=days)]
    if before.empty:
        return None
    return float(series.iloc[-1]) / float(before.iloc[-1]) - 1


def fund_metrics(nav: pd.DataFrame) -> dict:
    s = nav["nav"].astype(float) if not nav.empty else pd.Series(dtype=float)
    out: dict = {
        "history_years": round((s.index[-1] - s.index[0]).days / 365.25, 1) if len(s) > 1 else 0,
        "ret_1m": _period_return(s, 30), "ret_3m": _period_return(s, 91),
        "ret_6m": _period_return(s, 182), "ret_1y": _period_return(s, 365),
        "cagr_3y": _cagr(s, 3), "cagr_5y": _cagr(s, 5),
        "vol_1y": None, "sharpe_1y": None, "max_dd_3y": None, "sparkline": [],
    }
    if len(s) < 30:
        return out
    last_1y = s[s.index >= s.index[-1] - pd.Timedelta(days=365)]
    rets = last_1y.pct_change().dropna()
    if len(rets) > 20:
        vol = float(rets.std() * math.sqrt(TRADING_DAYS))
        out["vol_1y"] = vol
        r1y = out["ret_1y"]
        if r1y is not None and vol > 0:
            out["sharpe_1y"] = (r1y - RISK_FREE) / vol
    last_3y = s[s.index >= s.index[-1] - pd.Timedelta(days=3 * 365)]
    if len(last_3y) > 20:
        dd = last_3y / last_3y.cummax() - 1
        out["max_dd_3y"] = float(dd.min())
    # ~ weekly points for a 3y sparkline
    spark = last_3y.resample("W").last().dropna()
    out["sparkline"] = [{"d": d.strftime("%Y-%m-%d"), "v": round(float(v), 4)} for d, v in spark.items()]
    return out


# ── Classification ──────────────────────────────────────────────────────────

BUCKETS = [
    ("International", r"international|overseas|global|nasdaq|taiwan|europe|us equity|s&p|china|japan|fof.*(global|overseas|emerging market)"),
    ("Sectoral / Thematic", r"sectoral|thematic|healthcare|pharma|infrastructure|defence|defense|banking|psu|energy|technology|digital|consumption|capital market|manufacturing|transport|esg|business cycle"),
    ("Index - Factor / Smart Beta", r"value index|momentum|quality|low vol|alpha|equal weight|enhanced value|factor"),
    ("Index - Broad", r"index fund|nifty 50\b|nifty next 50|nifty 100|nifty 500|sensex|midcap 150|smallcap 250|etf"),
    ("Small Cap", r"small ?cap"),
    ("Mid Cap", r"mid ?cap"),
    ("Large Cap", r"large ?cap|bluechip|top 100"),
    ("Flexi / Multi / Focused", r"flexi|multi ?cap|focused|large & mid|large and mid"),
    ("ELSS", r"elss|tax saver"),
    ("Hybrid", r"hybrid|balanced|arbitrage|asset allocation|dynamic asset"),
    ("Debt / Liquid", r"debt|liquid|overnight|gilt|bond|duration|money market|credit|corporate|banking and psu debt|floater"),
    ("Gold / Commodity", r"gold|silver|commodit"),
]


def classify(category: str, name: str) -> str:
    text = f"{category} {name}".lower()
    # Sector index funds are thematic bets, not broad index exposure.
    for bucket, pattern in BUCKETS:
        if re.search(pattern, text):
            if bucket == "Index - Broad" and re.search(r"bank|defence|defense|healthcare|capital market|it index|pharma|auto|infra", text):
                return "Sectoral / Thematic"
            return bucket
    return "Other"


# ── Portfolio build ─────────────────────────────────────────────────────────

def build_mf_portfolio(mf_holdings: list[dict], include_history: bool = True) -> dict:
    """Turn raw Kite mf_holdings into an analysed portfolio."""
    try:
        amfi = load_amfi_map()
    except Exception as e:
        log.warning("AMFI master unavailable: %s", e)
        amfi = {}

    funds: list[dict] = []
    for h in mf_holdings:
        qty = float(h.get("quantity") or 0)
        if qty <= 0:
            continue
        isin = (h.get("tradingsymbol") or "").strip()
        meta = amfi.get(isin, {})
        avg = float(h.get("average_price") or 0)
        nav = float(h.get("last_price") or meta.get("nav") or 0)
        invested = avg * qty
        current = nav * qty
        name = h.get("fund") or meta.get("scheme_name") or isin
        category = meta.get("category") or ""
        fund = {
            "fund": name,
            "isin": isin,
            "folio": h.get("folio"),
            "scheme_code": meta.get("scheme_code"),
            "amc": meta.get("amc") or _guess_amc(name),
            "category": category,
            "bucket": classify(category, name),
            "plan": meta.get("plan") or ("Direct" if "DIRECT" in name.upper() else ""),
            "units": round(qty, 3),
            "avg_nav": round(avg, 4),
            "nav": round(nav, 4),
            "nav_date": h.get("last_price_date") or meta.get("nav_date"),
            "invested": round(invested, 2),
            "current": round(current, 2),
            "pnl": round(current - invested, 2),
            "pnl_pct": round((current / invested - 1) * 100, 2) if invested > 0 else None,
            # Kite reports 0.0 when it has not computed XIRR for a folio; treat as unknown.
            "xirr": (lambda v: v if v else None)(_f(h.get("xirr"))),
        }
        if include_history and fund["scheme_code"]:
            try:
                fund.update(fund_metrics(fetch_nav_history(fund["scheme_code"])))
            except Exception as e:
                log.warning("metrics failed for %s: %s", name, e)
        funds.append(fund)

    total_inv = sum(f["invested"] for f in funds)
    total_cur = sum(f["current"] for f in funds)
    for f in funds:
        f["weight"] = round(f["current"] / total_cur * 100, 2) if total_cur else 0

    funds.sort(key=lambda f: -f["current"])

    def _agg(key):
        agg: dict[str, dict] = {}
        for f in funds:
            k = f.get(key) or "Other"
            a = agg.setdefault(k, {"name": k, "current": 0.0, "invested": 0.0, "count": 0})
            a["current"] += f["current"]; a["invested"] += f["invested"]; a["count"] += 1
        for a in agg.values():
            a["weight"] = round(a["current"] / total_cur * 100, 2) if total_cur else 0
            a["pnl_pct"] = round((a["current"] / a["invested"] - 1) * 100, 2) if a["invested"] else None
            a["current"] = round(a["current"], 2); a["invested"] = round(a["invested"], 2)
        return sorted(agg.values(), key=lambda a: -a["current"])

    weights = np.array([f["current"] / total_cur for f in funds]) if total_cur else np.array([])
    hhi = float((weights ** 2).sum()) if len(weights) else 0.0

    def _wavg(key):
        vals = [(f[key], f["current"]) for f in funds if f.get(key) is not None]
        tot = sum(w for _, w in vals)
        return round(sum(v * w for v, w in vals) / tot, 4) if tot else None

    return {
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "fund_count": len(funds),
        "invested": round(total_inv, 2),
        "current": round(total_cur, 2),
        "pnl": round(total_cur - total_inv, 2),
        "pnl_pct": round((total_cur / total_inv - 1) * 100, 2) if total_inv else None,
        "by_bucket": _agg("bucket"),
        "by_amc": _agg("amc"),
        "concentration": {
            "top_fund_weight": round(float(weights.max() * 100), 2) if len(weights) else 0,
            "top3_weight": round(float(np.sort(weights)[-3:].sum() * 100), 2) if len(weights) else 0,
            "hhi": round(hhi, 4),
            "effective_funds": round(1 / hhi, 1) if hhi else 0,
        },
        "weighted": {
            "ret_1y": _wavg("ret_1y"), "cagr_3y": _wavg("cagr_3y"),
            "vol_1y": _wavg("vol_1y"), "max_dd_3y": _wavg("max_dd_3y"), "xirr": _wavg("xirr"),
        },
        "funds": funds,
    }


def _guess_amc(name: str) -> str:
    first = name.split(" ")[0].title() if name else "Unknown"
    aliases = {"Sbi": "SBI", "Icici": "ICICI Prudential", "Hdfc": "HDFC", "Hsbc": "HSBC", "Jm": "JM Financial",
               "Ppfas": "PPFAS", "Parag": "PPFAS", "Motilal": "Motilal Oswal", "Nippon": "Nippon India",
               "Navi": "Navi", "Kotak": "Kotak", "Edelweiss": "Edelweiss", "Bandhan": "Bandhan"}
    return aliases.get(first, first)


# ── LLM review ──────────────────────────────────────────────────────────────

def review_prompt(portfolio: dict, equity_summary: dict | None = None) -> str:
    """Compact, number-dense context for the reviewer model."""
    lines = [
        f"As of {portfolio['as_of'][:10]}. {portfolio['fund_count']} mutual funds, invested ₹{portfolio['invested']:,.0f}, "
        f"current ₹{portfolio['current']:,.0f}, P&L {portfolio['pnl_pct']}%.",
        f"Concentration: top fund {portfolio['concentration']['top_fund_weight']}%, top-3 {portfolio['concentration']['top3_weight']}%, "
        f"effective number of funds {portfolio['concentration']['effective_funds']}.",
        "Weighted metrics: " + ", ".join(f"{k}={v}" for k, v in portfolio["weighted"].items() if v is not None),
        "", "Allocation by bucket:",
    ]
    for b in portfolio["by_bucket"]:
        lines.append(f"  - {b['name']}: {b['weight']}% ({b['count']} funds, P&L {b['pnl_pct']}%)")
    lines += ["", "Allocation by AMC:"]
    for a in portfolio["by_amc"][:12]:
        lines.append(f"  - {a['name']}: {a['weight']}% ({a['count']} funds)")
    lines += ["", "Funds (weight | bucket | P&L% | XIRR | 1y ret | 3y CAGR | 1y vol | 3y maxDD):"]
    for f in portfolio["funds"]:
        def pct(x): return "n/a" if x is None else f"{x*100:.1f}%"
        lines.append(
            f"  - {f['fund']} | {f['weight']}% | {f['bucket']} | {f['pnl_pct']}% | "
            f"{'n/a' if f['xirr'] is None else str(round(f['xirr'],1))+'%'} | {pct(f.get('ret_1y'))} | "
            f"{pct(f.get('cagr_3y'))} | {pct(f.get('vol_1y'))} | {pct(f.get('max_dd_3y'))}"
        )
    if equity_summary:
        lines += ["", f"Direct equity alongside: {equity_summary.get('count')} stocks, current ₹{equity_summary.get('current', 0):,.0f} "
                      f"(P&L {equity_summary.get('pnl_pct')}%). Top sectors/tickers: {equity_summary.get('top', '')}"]
    return "\n".join(lines)
