"""Portfolio-level diagnostics the stock-by-stock agents never see:
concentration, sector/size mix, tiny and illiquid lines, deep losers."""

from __future__ import annotations

from collections import defaultdict

ETF_HINTS = ("BEES", "ETF", "SILVER", "GOLD", "IETF")


def book_health(holdings: list[dict], info: dict[str, dict] | None = None) -> dict:
    """holdings: [{ticker, quantity, avg_price, last_price, turnover_cr?}]; info: ticker -> fundamentals."""
    info = info or {}
    rows = []
    for h in holdings:
        q, avg, ltp = float(h.get("quantity") or 0), float(h.get("avg_price") or 0), float(h.get("last_price") or 0)
        if q <= 0:
            continue
        f = info.get(h["ticker"]) or {}
        mc = f.get("market_cap")
        is_etf = any(x in h["ticker"].upper() for x in ETF_HINTS) and not f.get("sector")
        size = ("ETF" if is_etf else "Large (>₹50k Cr)" if mc and mc > 5e11 else "Mid (₹10k-50k Cr)" if mc and mc > 1e11
                else "Small (₹1k-10k Cr)" if mc and mc > 1e10 else "Micro (<₹1k Cr)" if mc else "Unknown")
        rows.append({"ticker": h["ticker"], "value": q * ltp, "invested": q * avg, "pnl_pct": (ltp / avg - 1) * 100 if avg else None,
                     "sector": f.get("sector") or ("ETF / Commodity" if is_etf else "Unknown"), "size": size,
                     "turnover_cr": h.get("turnover_cr"), "ret_1y": h.get("ret_1y")})
    total = sum(r["value"] for r in rows) or 1.0
    inv = sum(r["invested"] for r in rows) or 1.0
    w = sorted((r["value"] / total for r in rows), reverse=True)
    hhi = sum(x * x for x in w)
    sectors, sizes = defaultdict(float), defaultdict(float)
    for r in rows:
        sectors[r["sector"]] += r["value"] / total * 100
        sizes[r["size"]] += r["value"] / total * 100
    fin = sectors.get("Financial Services", 0.0)
    tiny = [r["ticker"] for r in rows if r["value"] < 5000]
    illiquid = [r["ticker"] for r in rows if r.get("turnover_cr") is not None and r["turnover_cr"] < 1]
    losers = [(r["ticker"], round(r["ret_1y"] * 100)) for r in rows if r.get("ret_1y") is not None and r["ret_1y"] < -0.3]
    flags = []
    if len(rows) > 30: flags.append(f"{len(rows)} names: more than one person can review monthly (target 20–25)")
    if w and w[0] > 0.10: flags.append(f"Largest position {w[0]*100:.1f}% of the book")
    if fin > 25: flags.append(f"Financials {fin:.0f}% of the book")
    if tiny: flags.append(f"{len(tiny)} positions under ₹5,000")
    if illiquid: flags.append(f"{len(illiquid)} names trade under ₹1 Cr/day")
    if sizes.get("Micro (<₹1k Cr)", 0) > 5: flags.append(f"Micro-caps {sizes['Micro (<₹1k Cr)']:.1f}% of the book")
    if losers: flags.append(f"{len(losers)} names down more than 30% over a year")
    return {
        "names": len(rows), "value": round(total, 2), "invested": round(inv, 2), "pnl_pct": round((total / inv - 1) * 100, 2),
        "winners": sum(1 for r in rows if (r["pnl_pct"] or 0) > 0), "losers": sum(1 for r in rows if (r["pnl_pct"] or 0) < 0),
        "effective_names": round(1 / hhi, 1) if hhi else 0, "top5_pct": round(sum(w[:5]) * 100, 1), "top10_pct": round(sum(w[:10]) * 100, 1),
        "sectors": sorted(({"name": k, "pct": round(v, 1)} for k, v in sectors.items()), key=lambda x: -x["pct"]),
        "sizes": sorted(({"name": k, "pct": round(v, 1)} for k, v in sizes.items()), key=lambda x: -x["pct"]),
        "tiny_positions": tiny, "illiquid": illiquid, "deep_losers": losers, "flags": flags,
    }
