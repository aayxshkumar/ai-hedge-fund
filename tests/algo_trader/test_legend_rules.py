"""Portfolio construction rules over a synthetic book; red flags fail every lens."""
from src.analysis.legend_lenses import portfolio_rules


def _scores(passed: dict, red=()):
    return {f"{t}.NS": {"passed": p, "red_flag": ({"reason": "x"} if t in red else None)} for t, p in passed.items()}


def test_rules_flag_concentration_and_red_flags():
    rows = [{"ticker": "A", "value": 50}, {"ticker": "B", "value": 30}, {"ticker": "GOLDBEES", "value": 20}]
    info = {"A": {"sector": "Financial Services"}, "B": {"sector": "Financial Services"}}
    r = portfolio_rules(rows, _scores({"A": 4, "B": 0}, red=("B",)), info)
    assert any("position > 10.0%" in c["rule"] and not c["pass"] for c in r["checks"])
    assert any("sector > 25.0%" in c["rule"] and not c["pass"] for c in r["checks"])
    assert any("gold hedge" in c["rule"] and not c["pass"] for c in r["checks"])  # 20% gold is no longer a hedge
    assert r["red"] == ["B"] and r["strong"] == ["A"]


def test_well_built_book_passes_most_rules():
    names = [f"S{i}" for i in range(20)]
    rows = [{"ticker": t, "value": (8 if i < 10 else 3)} for i, t in enumerate(names)]
    info = {t: {"sector": f"Sector{i % 6}"} for i, t in enumerate(names)}
    r = portfolio_rules(rows, _scores({t: (4 if i < 12 else 2) for i, t in enumerate(names)}), info)
    assert r["passed"] >= r["of"] - 1, [c for c in r["checks"] if not c["pass"]]


def test_gold_hedge_and_other_etf_caps_are_separate():
    from src.analysis.legend_lenses import portfolio_rules
    rows = [{"ticker": "GOLDBEES", "value": 7.5}, {"ticker": "SILVER", "value": 4.5}, {"ticker": "HNGSNGBEES", "value": 2.5},
            {"ticker": "GOLDIAM", "value": 2.0}] + [{"ticker": f"S{i}", "value": 83.5 / 16} for i in range(16)]
    r = portfolio_rules(rows, {})
    assert r["gold_pct"] == 7.5 and r["other_etf_pct"] == 7.0 and r["etf_pct"] == 14.5
    checks = {c["rule"]: c for c in r["checks"]}
    assert checks["gold hedge 6-8% of the book"]["pass"] is True
    assert checks["silver / other ETFs <= 2%"]["pass"] is False
