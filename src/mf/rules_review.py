"""Deterministic portfolio-construction review for the mutual-fund book.

Same output shape as the LLM review (MFReview) so the page can show either,
but every statement here is a rule over the numbers: overlap per role,
thematic cap, missing core, sub-scale lines, AMC concentration, young funds,
laggards versus category peers. Profile 'growth' (default) is for a long
horizon: the core is a broad or large+mid index rather than Nifty 50, and
mid/small are allowed up to half the book."""

from __future__ import annotations

from src.mf.universe import best_in_bucket, find, rank_fund


def _ord(n):
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"

PROFILES = {
    # bucket -> (min, max) share of the fund book, in %
    "growth": {"core_min": 30, "thematic_max": 20, "midsmall_max": 50, "international": (5, 15), "line_min": 3,
               "core_buckets": ("Index - Broad", "Flexi / Multi / Focused", "Large Cap"), "ballast_min": 5},
    "balanced": {"core_min": 45, "thematic_max": 15, "midsmall_max": 35, "international": (5, 15), "line_min": 3,
                 "core_buckets": ("Index - Broad", "Flexi / Multi / Focused", "Large Cap"), "ballast_min": 10},
}

# Rough large/mid/small look-through per role (index compositions are by construction;
# active categories by SEBI mandate minimums; flexi assumed 65/25/10).
CAP_MIX = {
    "Large Cap": (90, 10, 0), "Index - Broad": (60, 30, 10), "Index - Factor / Smart Beta": (60, 30, 10),
    "Flexi / Multi / Focused": (65, 25, 10), "Mid Cap": (15, 75, 10), "Small Cap": (5, 20, 75),
    "ELSS": (60, 25, 15), "Sectoral / Thematic": (55, 30, 15), "International": (0, 0, 0),
    "Hybrid": (50, 15, 5), "Debt / Liquid": (0, 0, 0), "Gold / Commodity": (0, 0, 0), "Other": (50, 30, 20),
}
NAME_MIX = {  # name patterns that override the bucket default
    "next 50": (100, 0, 0), "nifty 50": (100, 0, 0), "midcap 150": (0, 100, 0), "smallcap 250": (0, 0, 100),
    "largemidcap 250": (50, 50, 0), "large midcap 250": (50, 50, 0), "nifty 500": (75, 15, 10), "microcap": (0, 0, 100),
}


def cap_lookthrough(funds: list[dict]) -> dict:
    tot = sum(f["current"] for f in funds) or 1.0
    large = mid = small = intl = other = 0.0
    for f in funds:
        w = f["current"] / tot * 100
        name = f["fund"].lower()
        mix = next((m for k, m in NAME_MIX.items() if k in name), None) or CAP_MIX.get(f.get("bucket"), (50, 30, 20))
        if f.get("bucket") == "International":
            intl += w
            continue
        l, m, s = mix
        large += w * l / 100; mid += w * m / 100; small += w * s / 100
        other += w * (100 - l - m - s) / 100
    return {"large": round(large, 1), "mid": round(mid, 1), "small": round(small, 1), "international": round(intl, 1), "other": round(other, 1)}


def rules_review(portfolio: dict, universe: dict | None, profile: str = "growth",
                 household_ballast: dict | None = None) -> dict:
    """`household_ballast` = {"value": ₹, "label": "..."}: non-equity assets held outside the fund book
    (gold/silver ETFs in the demat, sovereign gold bonds) that count toward the ballast rule."""
    P = PROFILES.get(profile, PROFILES["growth"])
    funds = portfolio["funds"]
    by_bucket = {b["name"]: b for b in portfolio["by_bucket"]}
    held = {f["scheme_code"] for f in funds}
    strengths, concerns, redundancies, steps, notes = [], [], [], [], []
    score = 100

    def w(b): return by_bucket.get(b, {}).get("weight", 0.0)
    def cnt(b): return by_bucket.get(b, {}).get("count", 0)

    # --- ranks vs peers ---
    ranks = {f["scheme_code"]: rank_fund(universe, f) for f in funds}

    # 1. core
    core = sum(w(b) for b in P["core_buckets"])
    if core < P["core_min"]:
        score -= 15
        concerns.append(f"Core (broad index + flexi/focused + large cap) is {core:.0f}% of the book; a {profile} profile needs at least {P['core_min']}%.")
        picks = find(universe, r"largemidcap 250|large midcap 250|nifty 500", 3)
        steps.append({"title": "Add a broad-market core index fund", "priority": "high",
                      "rationale": "Use a Nifty LargeMidcap 250 or Nifty 500 index fund (not Nifty 50) so the core stays mid-cap-tilted. Candidates by 3y CAGR/vol: "
                                   + ", ".join(f"{p['name']} ({(p.get('cagr_3y') or 0)*100:.1f}%)" for p in picks)})
    else:
        strengths.append(f"Core allocation {core:.0f}% meets the {P['core_min']}% floor.")

    # 2. thematic
    th = w("Sectoral / Thematic")
    if th > P["thematic_max"] + 1:
        score -= min(20, int(th - P["thematic_max"]))
        concerns.append(f"Sectoral/thematic is {th:.1f}% across {cnt('Sectoral / Thematic')} funds (cap {P['thematic_max']}%).")
        steps.append({"title": f"Cut thematic from {th:.1f}% to under {P['thematic_max']}%", "priority": "high",
                      "rationale": "Themes are timing bets layered on the market; keep at most two, each a deliberate size."})
    elif th > P["thematic_max"]:
        # Within a point of the cap: at the ceiling, not over it. No step, no penalty - just no new thematic money.
        concerns.append(f"Sectoral/thematic is at the cap ({th:.1f}% across {cnt('Sectoral / Thematic')} funds, cap {P['thematic_max']}%): no new thematic money.")

    # 3. mid + small
    ms = w("Mid Cap") + w("Small Cap") + (w("Index - Broad") * 0.4)
    if ms > P["midsmall_max"]:
        score -= 10
        concerns.append(f"Mid + small exposure is roughly {ms:.0f}% (including index look-through); above the {P['midsmall_max']}% ceiling for a {profile} profile.")
    else:
        strengths.append(f"Mid + small exposure (~{ms:.0f}%) is within the {P['midsmall_max']}% ceiling for a {profile} profile.")

    # 4. overlap per role
    for b, limit in (("Mid Cap", 2), ("Small Cap", 2), ("Flexi / Multi / Focused", 2), ("International", 2), ("Large Cap", 1)):
        if cnt(b) > limit:
            score -= 5
            names = [f["fund"] for f in funds if f["bucket"] == b]
            redundancies.append(f"{cnt(b)} funds in {b} ({w(b):.0f}%): {'; '.join(n.replace(' - DIRECT PLAN', '') for n in names)}. Keep the top {limit} by category rank.")
    # healthcare / pharma overlap inside thematic
    hc = [f for f in funds if f["bucket"] == "Sectoral / Thematic" and any(k in f["fund"].lower() for k in ("health", "pharma"))]
    if len(hc) > 1:
        score -= 5
        redundancies.append(f"{len(hc)} healthcare/pharma funds ({sum(f['weight'] for f in hc):.1f}%): one fund expresses the view.")

    # 5. sub-scale lines
    tiny = [f for f in funds if f["weight"] < P["line_min"]]
    if tiny:
        score -= min(10, 2 * len(tiny))
        concerns.append(f"{len(tiny)} lines under {P['line_min']}% of the book cannot move the outcome: " + ", ".join(f["fund"].split(" - ")[0].title() for f in tiny) + ".")
        steps.append({"title": f"Close or merge the {len(tiny)} sub-{P['line_min']}% lines", "priority": "medium",
                      "rationale": "Small gains mean trivial tax; fewer statements, fewer rebalancing decisions."})

    # 6. AMC concentration
    top_amc = portfolio["by_amc"][0] if portfolio.get("by_amc") else None
    if top_amc and top_amc["weight"] > 30:
        score -= 5
        concerns.append(f"{top_amc['name']} runs {top_amc['weight']:.0f}% of the book ({top_amc['count']} funds): one research desk, one style.")

    # 7. young funds
    young = [f for f in funds if (f.get("history_years") or 0) < 3]
    yw = sum(f["weight"] for f in young)
    if yw > 10:
        score -= 5
        concerns.append(f"{yw:.0f}% is in funds with under three years of NAV history ({len(young)} funds) — no full cycle on record.")

    # 8. laggards vs peers
    lag = []
    for f in funds:
        r = ranks.get(f["scheme_code"]) or {}
        if r.get("cagr_3y_pct") is not None and r["cagr_3y_pct"] < 33 and f["weight"] >= 2:
            lag.append((f, r))
    if lag:
        score -= min(10, 3 * len(lag))
        concerns.append("Bottom-third of category over 3 years: " + "; ".join(
            f"{f['fund'].split(' - ')[0].title()} ({(f.get('cagr_3y') or 0)*100:.1f}% vs median {(r['cagr_3y_median'] or 0)*100:.1f}%)" for f, r in lag) + ".")
        for f, r in lag:
            better = best_in_bucket(universe, f["bucket"], 3, exclude=held, theme=r.get("theme"))
            peer_label = f"{r['theme']} " if r.get("theme") else ""
            steps.append({"title": f"Re-underwrite {f['fund'].split(' - ')[0].title()}", "priority": "medium",
                          "rationale": f"Ranks at the {_ord(r['cagr_3y_pct'])} percentile of {r['peers']} {peer_label}{f['bucket']} funds. Peers with better 3y CAGR/vol: "
                                       + ", ".join(f"{b['name']} ({(b.get('cagr_3y') or 0)*100:.1f}%)" for b in better)})

    # 9. ballast — fund-side hybrid/debt/gold plus anything the household holds outside the fund book
    ballast = w("Hybrid") + w("Debt / Liquid") + w("Gold / Commodity")
    hb_value = float((household_ballast or {}).get("value") or 0)
    fund_total = float(portfolio.get("current") or sum(f.get("current", 0) for f in funds) or 0)
    if hb_value > 0 and fund_total > 0:
        combined = fund_total + hb_value
        ballast = (ballast / 100 * fund_total + hb_value) / combined * 100
        notes_ballast = f"{(household_ballast or {}).get('label') or 'non-equity assets outside the fund book'} (₹{hb_value:,.0f}) counted"
    else:
        notes_ballast = ""
    if ballast >= P["ballast_min"] and notes_ballast:
        strengths.append(f"Ballast {ballast:.1f}% of the household book once {notes_ballast} — above the {P['ballast_min']}% floor.")
    if ballast < P["ballast_min"]:
        concerns.append(f"Non-equity ballast is {ballast:.1f}% ({notes_ballast or 'no hybrid/multi-asset/gold in the fund book'}) — a −35% mid/small year has little to rebalance from.")
        picks = find(universe, r"multi asset", 3)
        steps.append({"title": "Add a multi-asset fund as ballast instead of large-cap", "priority": "medium",
                      "rationale": "Keeps the growth tilt while adding something that rebalances into equity after a fall. Best by 3y CAGR/vol: "
                                   + ", ".join(f"{p['name']} ({(p.get('cagr_3y') or 0)*100:.1f}%)" for p in picks)})

    # 10. international
    lo, hi = P["international"]
    intl = w("International")
    if intl < lo:
        concerns.append(f"International is {intl:.0f}%; {lo}-{hi}% diversifies away single-country risk.")
    elif intl > hi:
        concerns.append(f"International is {intl:.0f}%; above the {hi}% ceiling.")
    else:
        strengths.append(f"International sleeve {intl:.0f}% is in the {lo}-{hi}% band.")

    # strengths from ranks
    tops = [f for f in funds if (ranks.get(f["scheme_code"]) or {}).get("cagr_3y_pct", 0) >= 80 and f["weight"] >= 3]
    if tops:
        strengths.append("Top-quintile funds in their categories: " + ", ".join(f"{f['fund'].split(' - ')[0].title()} ({_ord(ranks[f['scheme_code']].get('cagr_3y_pct'))} pct)" for f in tops) + ".")
    if portfolio["concentration"]["effective_funds"] >= 8:
        strengths.append(f"No single-fund dependence: {portfolio['concentration']['effective_funds']} effective funds, top-3 {portfolio['concentration']['top3_weight']}%.")

    # fund notes
    for f in funds:
        r = ranks.get(f["scheme_code"]) or {}
        pct = r.get("cagr_3y_pct")
        if f["weight"] < P["line_min"]:
            flag, role, note = "review", "sub-scale line", f"{f['weight']}% of the book; merge or close."
        elif pct is not None and pct < 33:
            flag, role, note = "review", f"{f['bucket']} laggard", f"{_ord(pct)} percentile of {r['peers']} {r.get('theme') or ''} peers on 3y CAGR; median {(r.get('cagr_3y_median') or 0)*100:.1f}%."
        elif f["bucket"] in ("Mid Cap", "Small Cap", "Flexi / Multi / Focused", "International") and cnt(f["bucket"]) > 2:
            flag, role, note = "overlap", f"one of {cnt(f['bucket'])} in {f['bucket']}", (f"{_ord(pct)} percentile of peers." if pct is not None else "Overlapping role.")
        elif pct is not None and pct >= 67:
            flag, role, note = "core", f"{f['bucket']} leader", f"{_ord(pct)} percentile of {r['peers']} {r.get('theme') or ''} peers; 3y CAGR {(f.get('cagr_3y') or 0)*100:.1f}%."
        else:
            flag, role, note = "satellite", f["bucket"], (f"{_ord(pct)} percentile of peers." if pct is not None else "Under three years of history; unranked.")
        notes.append({"fund": f["fund"], "role": role, "flag": flag, "note": note})

    score = max(0, min(100, score))
    headline = (f"{'Well' if score >= 70 else 'Reasonably' if score >= 50 else 'Poorly'} constructed for a {profile} profile: "
                f"{len(funds)} funds, core {core:.0f}%, mid+small ~{ms:.0f}%, thematic {th:.0f}%, international {intl:.0f}%.")
    lt = cap_lookthrough(funds)
    return {
        "health_score": score, "headline": headline,
        "overall_assessment": (f"Look-through market-cap mix: large {lt['large']}%, mid {lt['mid']}%, small {lt['small']}%, international {lt['international']}%. "
                               f"Rules applied: core ≥ {P['core_min']}%, thematic ≤ {P['thematic_max']}%, mid+small ≤ {P['midsmall_max']}%, ≤2 funds per role, "
                               f"lines ≥ {P['line_min']}%, ballast ≥ {P['ballast_min']}%, every fund ranked against its category peers."),
        "strengths": strengths, "concerns": concerns, "redundancies": redundancies,
        "diversification_notes": f"{portfolio['fund_count']} funds behave like {portfolio['concentration']['effective_funds']}; top fund {portfolio['concentration']['top_fund_weight']}%.",
        "next_steps": sorted(steps, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s["priority"]]),
        "fund_notes": notes, "cap_lookthrough": lt, "profile": profile, "source": "rules",
    }
