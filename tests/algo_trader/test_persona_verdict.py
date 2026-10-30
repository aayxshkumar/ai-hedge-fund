from src.analysis.persona_scores import consensus_verdict, _conviction, QUANT


def _row(personas):
    sigs = [p.get("signal") for p in personas.values()]
    return {"personas": personas, "bullish": sigs.count("bullish"), "bearish": sigs.count("bearish"),
            "neutral": sigs.count("neutral"), "no_data": sum(1 for p in personas.values() if p.get("no_data")), "red_flag": None}


def _p(sig, score=None, mx=10, conf=None):
    d = {"signal": sig, "details": [], "no_data": False}
    if score is not None:
        d["score"], d["max"] = score, mx
    if conf is not None:
        d["confidence"] = conf
    return d


def test_conviction_scales_with_distance_from_threshold():
    assert _conviction(_p("bullish", 9.5)) > _conviction(_p("bullish", 7.0)) >= 0.25
    assert _conviction(_p("bullish", conf=90)) == 0.9
    assert _conviction({"signal": "bullish"}) == 0.25


def test_high_conviction_bears_outweigh_marginal_bulls():
    # 4 marginal bulls (7/10) vs 3 bears at 1/10: raw count says bull, weighting says sell-side
    personas = {f"bull{i}": _p("bullish", 7.0) for i in range(4)}
    personas.update({f"bear{i}": _p("bearish", 1.0) for i in range(3)})
    v = consensus_verdict(_row(personas))
    assert v["raw_score"] > 0
    assert v["signal_breakdown"]["weighted_score"] < 0
    assert v["action"] in ("Hold", "Sell")


def test_quant_analysts_carry_half_weight():
    quant = {q.replace("_analyst", ""): _p("bearish", conf=100) for q in QUANT}
    personas = {"warren_buffett": _p("bullish", 9.0), "charlie_munger": _p("bullish", 9.0), "ben_graham": _p("bullish", 9.0)}
    personas.update(quant)
    v = consensus_verdict(_row(personas))
    # 3 strong personas (w=0.8 each=2.4) vs 4 quant at 0.5 (=2.0): weighted stays positive
    assert v["signal_breakdown"]["weighted_score"] > 0
    assert v["analyst_signals"]["fundamentals"]["weight"] == 0.5
    assert v["analyst_signals"]["warren_buffett"]["weight"] == 0.8


def test_disagreement_lowers_confidence():
    agree = {f"b{i}": _p("bullish", 9.0) for i in range(8)}
    split = {f"b{i}": _p("bullish", 9.0) for i in range(8)}
    split.update({f"s{i}": _p("bearish", 1.0) for i in range(5)})
    assert consensus_verdict(_row(agree))["confidence"] > consensus_verdict(_row(split))["confidence"]


def test_tape_downgrades_buy_in_downtrend_but_never_upgrades():
    personas = {f"b{i}": _p("bullish", 9.0) for i in range(7)}
    personas["x"] = _p("neutral", 5.0)
    base = consensus_verdict(_row(personas))
    assert base["action"] == "Strong Buy" and "tape" not in base
    down = consensus_verdict(_row(personas), tech={"rsi": 28, "vs_e200": -22, "d20": -14, "vs_s20": -6, "pos52": 5})
    assert down["action"] == "Buy" and down["fundamental_action"] == "Strong Buy" and "downtrend" in down["tape"]
    hold = {f"b{i}": _p("bullish", 7.0) for i in range(2)}
    hold.update({f"s{i}": _p("bearish", 3.0) for i in range(2)})
    up = consensus_verdict(_row(hold), tech={"rsi": 80, "vs_e200": 30, "d20": 15, "vs_s20": 10, "pos52": 99})
    assert up["action"] == "Hold" and "tape" not in up


def test_oversold_sell_keeps_action_with_timing_note():
    personas = {f"s{i}": _p("bearish", 1.0) for i in range(8)}
    v = consensus_verdict(_row(personas), tech={"rsi": 18, "vs_e200": -30, "d20": -20, "vs_s20": -12, "pos52": 1})
    assert v["action"] == "Strong Sell" and "oversold" in v["tape"]


def test_red_flag_and_no_data_unchanged():
    personas = {f"b{i}": _p("bullish", 9.0) for i in range(8)}
    row = _row(personas); row["red_flag"] = {"reason": "SEBI order", "date": "2026-01-01"}
    assert consensus_verdict(row)["action"] == "Red flag"
    nd = {f"p{i}": {"signal": None, "details": [], "no_data": True} for i in range(12)}
    assert consensus_verdict(_row(nd))["action"] == "No data"


def test_lender_halves_ebitda_model_personas():
    from src.analysis.persona_scores import is_lender
    assert is_lender("MAHABANK.NS") and is_lender("SBIFUNDS") and is_lender("CANBK.NS") and not is_lender("GOLDIAM.NS") and not is_lender("COALINDIA.NS")
    assert is_lender("XYZ.NS", sector="Banks - Regional") and is_lender("ABC.NS", sector="Asset Management") and not is_lender("ABC.NS", sector="Steel")
    personas = {"michael_burry": _p("bearish", 1.0), "charlie_munger": _p("bearish", 1.0), "phil_fisher": _p("bearish", 1.0),
                "warren_buffett": _p("bullish", 8.5), "ben_graham": _p("bullish", 8.5), "rakesh_jhunjhunwala": _p("bullish", 7.5)}
    row = _row(personas)
    industrial = consensus_verdict(row, ticker="XYZ.NS")
    bank = consensus_verdict(row, ticker="XYZBANK.NS")
    assert industrial["signal_breakdown"]["weighted_score"] < 0 < bank["signal_breakdown"]["weighted_score"]
    assert bank["signal_breakdown"]["lender_fit"] is True and "Lender" in bank["reasoning"]
    # Burry 1/10 -> conviction 0.8, halved on a lender = 0.4; Buffett 8.5/10 -> conviction 0.7, full weight
    assert bank["analyst_signals"]["michael_burry"]["weight"] == 0.4 and bank["analyst_signals"]["warren_buffett"]["weight"] == 0.7
    assert industrial["analyst_signals"]["michael_burry"]["weight"] == 0.8
