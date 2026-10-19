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
    assert any("ETFs <= 10.0%" in c["rule"] and not c["pass"] for c in r["checks"])
    assert r["red"] == ["B"] and r["strong"] == ["A"]


def test_well_built_book_passes_most_rules():
    names = [f"S{i}" for i in range(20)]
    rows = [{"ticker": t, "value": (8 if i < 10 else 3)} for i, t in enumerate(names)]
    info = {t: {"sector": f"Sector{i % 6}"} for i, t in enumerate(names)}
    r = portfolio_rules(rows, _scores({t: (4 if i < 12 else 2) for i, t in enumerate(names)}), info)
    assert r["passed"] >= r["of"] - 1, [c for c in r["checks"] if not c["pass"]]
