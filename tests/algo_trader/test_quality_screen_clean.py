import json
import math

from src.analysis.quality_screen import _clean, score_row


def test_clean_replaces_nan_and_inf_recursively():
    row = {"ret_1y": float("nan"), "technical": {"rsi": float("inf"), "trend": "Bullish"}, "why": [1.0, float("nan")]}
    out = _clean(row)
    assert out["ret_1y"] is None and out["technical"]["rsi"] is None and out["why"] == [1.0, None]
    json.dumps(out)  # must be strict-JSON serialisable


def test_score_row_ignores_cleaned_nan_fields():
    f = _clean({"roe": float("nan"), "operating_margin": 0.2, "debt_to_equity": 10.0, "pe_ratio": None})
    s, why = score_row(f, {"trend": "Bullish", "rsi": None}, None)
    assert s == 3 and not any(math.isnan(x) for x in [s])
