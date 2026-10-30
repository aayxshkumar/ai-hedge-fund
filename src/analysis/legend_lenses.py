"""Stock and portfolio screens modelled on how India's best-known investors
say they build portfolios - encoded as rules over the same statements the
persona agents use, so every verdict is reproducible without a model.

Lenses (sources in analysis/2026-10-19-legends-playbook.md):
  qglp        Raamdeo Agrawal: Quality, Growth, Longevity, reasonable Price.
  coffee_can  Saurabh Mukherjea / Marcellus: revenue growth >= 10% AND return on
              capital >= 15% in EVERY year on record (lenders: ROE >= 15%, ROA >= 1%).
  smile       Vijay Kedia: Small in size, Medium in experience, Large in
              aspiration, Extra-large market potential - growth from a small base.
  dhandho     Mohnish Pabrai: "heads I win, tails I don't lose much" - low
              leverage, cash yield, cheap EV, insiders buying.
  conviction  Jhunjhunwala / R.K. Damani / Ramesh Damani: businesses you can
              hold for a decade - consistent earnings, returns on equity,
              dividends, bought at a sensible price.

Every lens starts with the one rule all of them share: management integrity.
A ticker listed in outputs/red_flags.json (regulatory action, auditor
resignation, governance event) fails every lens regardless of its numbers.
"""

from __future__ import annotations

import re

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

OUT = Path(__file__).resolve().parents[2] / "outputs"
RED_FLAGS_FILE = OUT / "red_flags.json"
LENDER_HINTS = ("bank", "finance", "financial", "credit", "nbfc", "capital", "gilts", "funds", "housing", "sfb", "ireda")


def load_red_flags() -> dict[str, dict]:
    if RED_FLAGS_FILE.exists():
        try:
            return {k.upper(): v for k, v in json.loads(RED_FLAGS_FILE.read_text()).items()}
        except Exception:
            return {}
    return {}


def _is_lender(ticker: str, sector: str | None, metrics: list) -> bool:
    if sector and "financial" in sector.lower():
        return True
    t = ticker.lower()
    return any(h in t for h in LENDER_HINTS)


def _series(metrics, attr):
    return [getattr(m, attr) for m in metrics if getattr(m, attr) is not None]


def _f(x, pct=False):
    if x is None:
        return "n/a"
    return f"{x*100:.0f}%" if pct else f"{x:.2f}"


def score_ticker(ticker: str, end_date: str | None = None, sector: str | None = None) -> dict:
    from src.tools.api import get_financial_metrics, get_insider_trades, get_market_cap, search_line_items

    end = end_date or datetime.now().strftime("%Y-%m-%d")
    red = load_red_flags().get(ticker.upper()) or load_red_flags().get(ticker.upper().replace(".NS", "").replace(".BO", ""))
    out: dict = {"ticker": ticker, "red_flag": red, "lenses": {}, "passed": 0, "of": 5, "notes": []}

    try:
        metrics = get_financial_metrics(ticker, end, period="ttm", limit=10)
        items = search_line_items(ticker, ["revenue", "net_income", "free_cash_flow", "capital_expenditure",
                                           "dividends_and_other_cash_distributions", "total_debt", "cash_and_equivalents",
                                           "shareholders_equity", "earnings_per_share", "ebitda"], end, period="ttm", limit=10)
        mcap = get_market_cap(ticker, end)
        insiders = get_insider_trades(ticker, end, limit=100)
    except Exception as e:
        out["error"] = str(e)[:120]
        return out
    metrics = [m for m in metrics if m.return_on_equity is not None or m.revenue_growth is not None]
    if not metrics:
        out["notes"].append("no financial statements available")
        return out

    latest = metrics[0]
    lender = _is_lender(ticker, sector, metrics)
    roe = _series(metrics, "return_on_equity")
    roic = _series(metrics, "return_on_invested_capital")
    roa = _series(metrics, "return_on_assets")
    rev_g = _series(metrics, "revenue_growth")
    eps_g = _series(metrics, "earnings_per_share_growth") or _series(metrics, "earnings_growth")
    de = latest.debt_to_equity
    years = len(metrics)
    net_income = [getattr(i, "net_income", None) for i in items if getattr(i, "net_income", None) is not None]
    fcf = [getattr(i, "free_cash_flow", None) for i in items if getattr(i, "free_cash_flow", None) is not None]
    divs = [getattr(i, "dividends_and_other_cash_distributions", None) for i in items]
    pays_div = any(d is not None and d < 0 for d in divs) or (latest.payout_ratio or 0) > 0
    debt = getattr(items[0], "total_debt", None) if items else None
    cash = getattr(items[0], "cash_and_equivalents", None) if items else None
    net_cash = (cash or 0) - (debt or 0) if (cash is not None or debt is not None) else None
    buys = sum(1 for t in insiders if (t.transaction_shares or 0) > 0)
    sells = sum(1 for t in insiders if (t.transaction_shares or 0) < 0)
    mcap_cr = (mcap or 0) / 1e7

    # ---------------- QGLP ----------------
    q = {}
    ret = (roe[0] if roe else None) if lender else (roic[0] if roic else (roe[0] if roe else None))
    q["quality"] = bool(ret is not None and ret >= 0.15 and (lender or de is None or de < 0.5) and (latest.operating_margin or 0) >= (0.20 if lender else 0.10))
    q["growth"] = bool(eps_g and eps_g[0] >= 0.15) or bool(rev_g and rev_g[0] >= 0.15)
    ret_series = roe if lender else (roic or roe)
    q["longevity"] = bool(len(ret_series) >= 3 and sum(1 for r in ret_series if r >= 0.15) >= max(3, len(ret_series) - 1) and len(net_income) >= 3 and all(n > 0 for n in net_income))
    pe = latest.price_to_earnings_ratio
    peg = latest.peg_ratio
    q["price"] = bool((peg is not None and 0 < peg <= 1.5) or (pe is not None and 0 < pe <= 20))
    q_score = sum(q.values())
    out["lenses"]["qglp"] = {"score": q_score, "max": 4, "pass": q_score >= 3, "checks": q,
                             "detail": f"ret {_f(ret, True)}, D/E {_f(de)}, OPM {_f(latest.operating_margin, True)}, EPS g {_f(eps_g[0] if eps_g else None, True)}, rev g {_f(rev_g[0] if rev_g else None, True)}, P/E {_f(pe)}, PEG {_f(peg)}, {years} yrs"}

    # ---------------- Coffee Can ----------------
    cc_years = min(len(rev_g), len(ret_series))
    rev_ok = sum(1 for g in rev_g if g >= 0.10)
    if lender:
        ret_ok = sum(1 for r in roe if r >= 0.15)
        roa_ok = sum(1 for r in roa if r >= 0.01) if roa else 0
        ret_label = f"ROE>=15% in {ret_ok}/{len(roe)} yrs, ROA>=1% in {roa_ok}/{len(roa)}"
        ret_pass = len(roe) >= 3 and ret_ok == len(roe)
    else:
        ret_ok = sum(1 for r in ret_series if r >= 0.15)
        ret_label = f"ROCE>=15% in {ret_ok}/{len(ret_series)} yrs"
        ret_pass = len(ret_series) >= 3 and ret_ok == len(ret_series)
    rev_pass = len(rev_g) >= 3 and rev_ok == len(rev_g)
    out["lenses"]["coffee_can"] = {"pass": bool(rev_pass and ret_pass), "score": int(rev_pass) + int(ret_pass), "max": 2,
                                   "detail": f"revenue>=10% in {rev_ok}/{len(rev_g)} yrs; {ret_label} (needs every year on record, min 3)"}

    # ---------------- SMILE ----------------
    s = {}
    s["small"] = bool(mcap_cr and mcap_cr < 10_000)
    s["medium_experience"] = bool(len(net_income) >= 3 and sum(1 for n in net_income if n > 0) >= 3)
    s["large_aspiration"] = bool(rev_g and rev_g[0] >= 0.15 and (latest.earnings_per_share_growth or 0) > 0)
    s["xl_potential"] = bool(len(rev_g) >= 2 and sum(rev_g[:3]) / min(3, len(rev_g)) >= 0.15)
    s["clean_management"] = bool(red is None and sells == 0 and (fcf[0] > 0 if fcf else True))
    s_score = sum(s.values())
    out["lenses"]["smile"] = {"score": s_score, "max": 5, "pass": s_score >= 4, "checks": s,
                              "detail": f"mcap ₹{mcap_cr:,.0f} Cr, rev g {_f(rev_g[0] if rev_g else None, True)}, 3y avg rev g {_f(sum(rev_g[:3]) / min(3, len(rev_g)) if rev_g else None, True)}, insiders {buys} buys / {sells} sells"}

    # ---------------- Dhandho ----------------
    d = {}
    d["low_leverage"] = bool(lender and (de or 0) < 1.5) or bool(not lender and (de is None or de < 0.5))
    d["cash_yield"] = bool((latest.free_cash_flow_yield or 0) >= 0.06) if not lender else bool((latest.price_to_earnings_ratio or 99) <= 10)
    ev = latest.enterprise_value_to_ebitda_ratio
    d["cheap_ev"] = bool(ev is not None and 0 < ev < 10) if not lender else bool((latest.price_to_book_ratio or 9) <= 1.5)
    d["insiders_buying"] = buys > sells and buys > 0
    d["earning"] = bool(net_income and net_income[0] > 0)
    d_score = sum(d.values())
    out["lenses"]["dhandho"] = {"score": d_score, "max": 5, "pass": d_score >= 4, "checks": d,
                                "detail": f"D/E {_f(de)}, FCF yield {_f(latest.free_cash_flow_yield, True)}, EV/EBITDA {_f(ev)}, P/B {_f(latest.price_to_book_ratio)}, net cash {'n/a' if net_cash is None else f'₹{net_cash/1e7:,.0f} Cr'}"}

    # ---------------- Conviction / buy-and-hold ----------------
    c = {}
    c["consistent_earnings"] = bool(len(net_income) >= 3 and all(n > 0 for n in net_income))
    c["returns"] = bool(ret is not None and ret >= 0.15)
    c["pays_dividend"] = bool(pays_div)
    c["sensible_price"] = bool(pe is not None and 0 < pe <= 25)
    c["not_tiny"] = bool(mcap_cr >= 1_000)
    c_score = sum(c.values())
    out["lenses"]["conviction"] = {"score": c_score, "max": 5, "pass": c_score >= 4, "checks": c,
                                   "detail": f"{len(net_income)} yrs profit {'all +' if c['consistent_earnings'] else 'mixed'}, ROE {_f(roe[0] if roe else None, True)}, dividend {'yes' if pays_div else 'no'}, P/E {_f(pe)}, ₹{mcap_cr:,.0f} Cr"}

    if red:
        for l in out["lenses"].values():
            l["pass"] = False
        out["notes"].append(f"RED FLAG: {red.get('reason', 'governance')} ({red.get('date', '')}) - fails every lens")
    out["passed"] = sum(1 for l in out["lenses"].values() if l["pass"])
    out["lender"] = lender
    out["mcap_cr"] = round(mcap_cr)
    return out


def score_many(tickers: list[str], sectors: dict[str, str] | None = None, workers: int = 3) -> dict[str, dict]:
    from concurrent.futures import ThreadPoolExecutor
    sectors = sectors or {}
    with ThreadPoolExecutor(workers) as ex:
        return dict(zip(tickers, ex.map(lambda t: score_ticker(t, sector=sectors.get(t)), tickers)))


# ---------------- Portfolio-level construction rules ----------------

RULES = {
    "names": (15, 25),          # legends run 10-25; IIMA (2021) says 40-50 for full risk reduction - we take the legends' range for a conviction book
    "max_position": 10.0,       # % of book
    "max_sector": 25.0,
    "min_position": 2.0,
    "gold_hedge": (6.0, 8.0),   # gold ETFs/SGBs kept as a hedge (beta ~0.7, held up through the 2026 drawdown); above 8% it stops being a hedge
    "max_other_etf": 2.0,       # silver and every other commodity/index ETF: Naren - be careful with an asset class that has done extremely well
    "top10_target": (50, 65),   # conviction tiering: top-10 should carry the book
}


def portfolio_rules(rows: list[dict], lens_scores: dict[str, dict], info: dict[str, dict] | None = None) -> dict:
    """rows: [{ticker, value}], lens_scores: score_many output."""
    info = info or {}
    total = sum(r["value"] for r in rows) or 1.0
    w = {r["ticker"]: r["value"] / total * 100 for r in rows}
    ranked = sorted(w.items(), key=lambda kv: -kv[1])
    is_etf = lambda t: any(x in t.upper() for x in ("BEES", "ETF", "SILVER", "GOLD")) and "GOLDIAM" not in t.upper()
    is_gold = lambda t: is_etf(t) and (re.match(r"^(?:[A-Z]*GOLD(?:BEES|CASE|IETF|ETF|1|SHARE)?|SETFGOLD|SGB[A-Z0-9]*)(?:-[A-Z]+)?$", t.upper().replace(".NS", "").replace(".BO", "")) is not None)
    gold = sum(v for t, v in w.items() if is_gold(t))
    other_etf = sum(v for t, v in w.items() if is_etf(t) and not is_gold(t))
    etf = gold + other_etf
    sectors: dict[str, float] = {}
    for t, v in w.items():
        s = (info.get(t) or {}).get("sector") or ("ETF / Commodity" if any(x in t.upper() for x in ("BEES", "ETF", "SILVER", "GOLD")) else "Unknown")
        sectors[s] = sectors.get(s, 0) + v
    top_sector = max(sectors.items(), key=lambda kv: kv[1]) if sectors else ("", 0)
    legends_pass = {t: (lens_scores.get(t) or lens_scores.get(t + ".NS") or {}).get("passed", 0) for t in w}
    red = [t for t in w if (lens_scores.get(t) or lens_scores.get(t + ".NS") or {}).get("red_flag")]
    strong = [t for t, p in legends_pass.items() if p >= 3]
    weak = [t for t, p in legends_pass.items() if p == 0 and t not in red and not any(x in t.upper() for x in ("BEES", "ETF", "SILVER", "GOLD"))]
    conviction_weight = sum(w[t] for t in strong)
    checks = [
        {"rule": f"{RULES['names'][0]}-{RULES['names'][1]} names (legends' range; IIMA 2021 says 40-50 for full diversification)", "value": len(w), "pass": RULES["names"][0] <= len(w) <= RULES["names"][1]},
        {"rule": f"no position > {RULES['max_position']}%", "value": f"{ranked[0][0]} {ranked[0][1]:.1f}%" if ranked else "", "pass": not ranked or ranked[0][1] <= RULES["max_position"]},
        {"rule": f"no position < {RULES['min_position']}%", "value": f"{sum(1 for v in w.values() if v < RULES['min_position'])} below", "pass": all(v >= RULES["min_position"] for v in w.values())},
        {"rule": f"no sector > {RULES['max_sector']}%", "value": f"{top_sector[0]} {top_sector[1]:.0f}%", "pass": top_sector[1] <= RULES["max_sector"]},
        {"rule": f"gold hedge {RULES['gold_hedge'][0]:.0f}-{RULES['gold_hedge'][1]:.0f}% of the book", "value": f"{gold:.1f}%", "pass": gold <= RULES["gold_hedge"][1]},
        {"rule": f"silver / other ETFs <= {RULES['max_other_etf']:.0f}%", "value": f"{other_etf:.1f}%", "pass": other_etf <= RULES["max_other_etf"]},
        {"rule": "top-10 carries 50-65% of the book (conviction tiering)", "value": f"{sum(v for _, v in ranked[:10]):.0f}%", "pass": RULES["top10_target"][0] <= sum(v for _, v in ranked[:10]) <= RULES["top10_target"][1]},
        {"rule": "weight in names passing >= 3 legend lenses >= 50%", "value": f"{conviction_weight:.0f}% in {len(strong)} names", "pass": conviction_weight >= 50},
        {"rule": "no red-flagged names", "value": ", ".join(red) or "none", "pass": not red},
        {"rule": "no names passing 0 lenses (ETFs excluded)", "value": f"{len(weak)}: {', '.join(weak[:8])}{'…' if len(weak) > 8 else ''}", "pass": not weak},
    ]
    return {"checks": checks, "passed": sum(1 for c in checks if c["pass"]), "of": len(checks),
            "weights": dict(ranked), "sectors": dict(sorted(sectors.items(), key=lambda kv: -kv[1])), "strong": strong, "weak": weak, "red": red,
            "etf_pct": round(etf, 1), "gold_pct": round(gold, 1), "other_etf_pct": round(other_etf, 1)}
