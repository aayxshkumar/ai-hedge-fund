"""Rules review and look-through are deterministic over a tiny synthetic book."""
from src.mf.rules_review import cap_lookthrough, rules_review


def _book(funds):
    tot = sum(f["current"] for f in funds)
    for f in funds:
        f["weight"] = round(f["current"] / tot * 100, 2)
        f.setdefault("scheme_code", hash(f["fund"]) % 100000)
        f.setdefault("history_years", 6)
    by = {}
    for f in funds:
        b = by.setdefault(f["bucket"], {"name": f["bucket"], "weight": 0, "count": 0, "current": 0, "invested": 0, "pnl_pct": 0})
        b["weight"] += f["weight"]; b["count"] += 1; b["current"] += f["current"]
    return {"funds": funds, "fund_count": len(funds), "by_bucket": sorted(by.values(), key=lambda b: -b["weight"]),
            "by_amc": [{"name": "X", "weight": 100, "count": len(funds)}],
            "concentration": {"effective_funds": 2.0, "top3_weight": 100, "top_fund_weight": 60}}


def test_thematic_heavy_book_scores_low_and_flags_core():
    book = _book([{"fund": "DEFENCE INDEX", "bucket": "Sectoral / Thematic", "current": 60},
                  {"fund": "HEALTH FUND", "bucket": "Sectoral / Thematic", "current": 30},
                  {"fund": "PHARMA FUND", "bucket": "Sectoral / Thematic", "current": 10}])
    r = rules_review(book, None, profile="growth")
    assert r["health_score"] < 60
    assert any("Core" in c for c in r["concerns"]) and any("thematic" in c.lower() for c in r["concerns"])
    assert any("healthcare/pharma" in x for x in r["redundancies"])
    assert r["next_steps"][0]["priority"] == "high"


def test_balanced_core_book_scores_high():
    book = _book([{"fund": "NIFTY LARGEMIDCAP 250 INDEX", "bucket": "Index - Broad", "current": 40},
                  {"fund": "FLEXI CAP", "bucket": "Flexi / Multi / Focused", "current": 25},
                  {"fund": "MID CAP", "bucket": "Mid Cap", "current": 15},
                  {"fund": "NASDAQ 100 INDEX", "bucket": "International", "current": 10},
                  {"fund": "MULTI ASSET", "bucket": "Hybrid", "current": 10}])
    r = rules_review(book, None, profile="growth")
    assert r["health_score"] >= 85 and not r["redundancies"]


def test_lookthrough_uses_index_names():
    lt = cap_lookthrough([{"fund": "NIFTY NEXT 50 INDEX", "bucket": "Index - Broad", "current": 50},
                          {"fund": "NIFTY MIDCAP 150 INDEX", "bucket": "Index - Broad", "current": 50}])
    assert lt == {"large": 50.0, "mid": 50.0, "small": 0.0, "international": 0.0, "other": 0.0}


def test_household_gold_counts_toward_ballast():
    funds = [{"fund": "MIDCAP INDEX", "bucket": "Index - Broad", "current": 70},
             {"fund": "SMALL CAP", "bucket": "Small Cap", "current": 30}]
    book = _book(funds); book["current"] = 100
    bare = rules_review(book, None, profile="growth")
    assert any("ballast" in c.lower() for c in bare["concerns"])
    with_gold = rules_review(book, None, profile="growth", household_ballast={"value": 8, "label": "demat gold"})
    assert not any("ballast" in c.lower() for c in with_gold["concerns"])
    assert any("demat gold" in s for s in with_gold["strengths"])



def test_thematic_at_the_cap_is_a_note_not_a_cut():
    # 20.1% thematic for a growth profile (cap 20): a note, no "cut from 20% toward 20%" step
    book = _book([{"fund": "NIFTY 50 INDEX", "bucket": "Index - Broad", "current": 79.9},
                  {"fund": "DEFENCE INDEX", "bucket": "Sectoral / Thematic", "current": 20.1}])
    r = rules_review(book, None, profile="growth")
    assert any("at the cap" in c for c in r["concerns"])
    assert not any(st["title"].startswith("Cut thematic") for st in r["next_steps"])
    over = _book([{"fund": "NIFTY 50 INDEX", "bucket": "Index - Broad", "current": 70},
                  {"fund": "DEFENCE INDEX", "bucket": "Sectoral / Thematic", "current": 30}])
    r2 = rules_review(over, None, profile="growth")
    assert any(st["title"] == "Cut thematic from 30.0% to under 20%" for st in r2["next_steps"])
