"""Run every persona agent's deterministic half and read off its pre-signal.

Each analyst in src/agents computes scores, margin of safety and a rule-based
signal before it asks an LLM to write a sentence. With the LLM captured
(src.utils.llm.capture_prompts) the agents still run end to end; the prompt
they would have sent carries their full analysis as JSON, which we parse. Zero
model calls, same numbers the LLM would have seen.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from src.utils.llm import capture_prompts

log = logging.getLogger(__name__)

PERSONAS = ["warren_buffett", "charlie_munger", "ben_graham", "peter_lynch", "phil_fisher", "mohnish_pabrai",
            "michael_burry", "bill_ackman", "aswath_damodaran", "stanley_druckenmiller", "rakesh_jhunjhunwala", "cathie_wood"]
QUANT = ["fundamentals_analyst", "growth_analyst", "valuation_analyst", "sentiment_analyst"]
DETAIL_KEYS = {"details", "detail", "fundamentals", "consistency", "moat", "pricing_power", "book_value", "management", "notes"}


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None


def _json_after(text: str, start: int):
    i = text.find("{", start)
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                blob = text[i:j + 1]
                for cand in (blob, re.sub(r",\s*}", "}", blob)):
                    try:
                        return json.loads(cand)
                    except Exception:
                        continue
                return None
    return None


def _ticker_in(text: str, tickers: list[str], pos: int) -> str | None:
    m = re.search(r"(?:Analysis Data for|Ticker:|analysis data for|for)\s+([A-Z0-9\-&]+\.(?:NS|BO))", text)
    if m and m.group(1) in tickers:
        return m.group(1)
    return tickers[pos] if pos < len(tickers) else None


def _facts(text: str, tk: str) -> dict:
    k = text.find(f'"{tk}":')
    if k >= 0:
        obj = _json_after(text, k + len(tk) + 3)
        if isinstance(obj, dict):
            return obj
    for marker in ("Facts:", "Analysis Data:", "analysis data:", "Data:"):
        k = text.find(marker)
        if k >= 0:
            obj = _json_after(text, k)
            if isinstance(obj, dict):
                return obj.get(tk, obj) if tk in obj else obj
    obj = _json_after(text, 0)
    return obj if isinstance(obj, dict) else {}


def _details(o, out: list):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in DETAIL_KEYS and isinstance(v, str) and len(v) > 8:
                out.append(v[:260])
            elif isinstance(v, (dict, list)):
                _details(v, out)
    elif isinstance(o, list):
        for v in o:
            _details(v, out)


def _mos(f: dict):
    for k in ("margin_of_safety", "margin_of_safety_vs_fair_value"):
        if _num(f.get(k)) is not None:
            return _num(f.get(k))
    for sub in ("valuation_analysis", "intrinsic_value_analysis"):
        if isinstance(f.get(sub), dict) and _num(f[sub].get("margin_of_safety")) is not None:
            return _num(f[sub].get("margin_of_safety"))
    return None


def _signal(name: str, f: dict, score, mx, mos):
    sig = f.get("pre_signal") or f.get("signal")
    if sig in ("bullish", "bearish", "neutral"):
        return sig
    if score is None or not mx:
        return None
    r = score / mx
    if name == "warren_buffett":          # the rule the agent's prompt gives the model
        return "bullish" if r >= 0.6 and (mos or 0) > 0 else "bearish" if r < 0.35 or (mos is not None and mos < -0.3) else "neutral"
    return "bullish" if r >= 0.7 else "bearish" if r <= 0.3 else "neutral"


def score_tickers(tickers: list[str], personas: list[str] | None = None, include_quant: bool = True,
                  lookback_days: int = 90) -> dict:
    """Return {ticker: {"personas": {name: {signal, score, max, mos, details, no_data}},
    "bullish": n, "bearish": n, "neutral": n, "no_data": n}}."""
    from src.utils.analysts import ANALYST_CONFIG

    wanted = personas or PERSONAS
    keys = [k for k in ANALYST_CONFIG if k in wanted or (include_quant and f"{k}_agent" in [q + "_agent" for q in QUANT] or k in QUANT)]
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    state = {"messages": [], "data": {"tickers": tickers, "portfolio": {"cash": 1_000_000, "positions": {}},
                                      "start_date": start, "end_date": end, "analyst_signals": {}},
             "metadata": {"show_reasoning": False, "model_name": "none", "model_provider": "none", "request": None}}
    captured: dict[str, list] = {}
    with capture_prompts() as records:
        for key in keys:
            fn = ANALYST_CONFIG[key]["agent_func"]
            before = len(records)
            try:
                fn(state)
            except Exception as e:  # one broken agent must not sink the run
                log.warning("persona %s failed: %s", key, e)
            captured[key] = records[before:]

    out = {t: {"personas": {}} for t in tickers}
    for key, recs in captured.items():
        name = key.replace("_agent", "")
        if name in QUANT or key in QUANT:
            continue
        for pos, rec in enumerate(recs):
            tk = _ticker_in(rec["prompt"], tickers, pos)
            if not tk:
                continue
            f = _facts(rec["prompt"], tk)
            score, mx, mos = _num(f.get("score")), _num(f.get("max_score")), _mos(f)
            det: list = []
            _details(f, det)
            no_data = bool(score == 0 and any("insufficient" in d.lower() or "no data" in d.lower() for d in det[:3]))
            out[tk]["personas"][name] = {"signal": None if no_data else _signal(name, f, score, mx, mos),
                                         "score": score, "max": mx, "mos": mos, "details": det[:8], "no_data": no_data}
    if include_quant:
        for q in QUANT:
            sig = state["data"]["analyst_signals"].get(f"{q}_agent") or {}
            for t, v in sig.items():
                if t in out and isinstance(v, dict):
                    out[t]["personas"][q.replace("_analyst", "")] = {"signal": v.get("signal"), "confidence": v.get("confidence"),
                                                                      "details": [json.dumps(v.get("reasoning"))[:600]], "no_data": False}
    from src.analysis.legend_lenses import load_red_flags
    red = load_red_flags()
    for t, row in out.items():
        row["red_flag"] = red.get(t.upper()) or red.get(t.upper().replace(".NS", "").replace(".BO", ""))
        sigs = [p.get("signal") for p in row["personas"].values()]
        row["bullish"] = sigs.count("bullish"); row["bearish"] = sigs.count("bearish")
        row["neutral"] = sigs.count("neutral"); row["no_data"] = sum(1 for p in row["personas"].values() if p.get("no_data"))
        row["verdict"] = consensus_verdict(row)
    return out


def consensus_verdict(row: dict) -> dict:
    """Meta-style verdict from persona pre-signals (same shape the Portfolio page reads)."""
    bull, bear = row["bullish"], row["bearish"]
    total = bull + bear + row["neutral"]
    score = (bull - bear) / total if total else 0.0
    personas_total = sum(1 for n in row["personas"] if n not in [q.replace("_analyst", "") for q in QUANT])
    if row.get("red_flag"):
        # Governance/regulatory event on file: the statements the personas
        # scored may be the very numbers in question. Integrity first.
        rf = row["red_flag"]
        return {"action": "Red flag", "confidence": 1.0, "score": -1.0,
                "reasoning": f"RED FLAG - {rf.get('reason', 'governance event')} ({rf.get('date', '')}). Analyst scores ({bull} bullish / {bear} bearish) are not actionable.",
                "signal_breakdown": {"bullish": bull, "bearish": bear, "neutral": row["neutral"], "total": total,
                                     "bullish_pct": round(bull / total * 100, 1) if total else 0, "bearish_pct": round(bear / total * 100, 1) if total else 0},
                "analyst_signals": {n: {"signal": p.get("signal") or "no data", "confidence": p.get("confidence", 0), "reasoning": "; ".join(p.get("details") or [])[:400]} for n, p in row["personas"].items()},
                "source": "persona_scores", "red_flag": rf}
    if personas_total and row["no_data"] >= max(6, int(personas_total * 0.6)):
        # ETFs, commodities and unlisted-statement micro-caps: the quant
        # analysts emit "bearish" on empty inputs; that is absence of evidence.
        action, score = "No data", 0.0
    elif score >= 0.4 and bull >= 6:
        action = "Strong Buy"
    elif score >= 0.15 and bull >= 4:
        action = "Buy"
    elif bear >= 8 and bull <= 1:
        action = "Strong Sell"
    elif score <= -0.2:
        action = "Sell"
    else:
        action = "Hold"
    conf = min(1.0, abs(score) + (0.15 if max(bull, bear) / total >= 0.7 else 0.0)) if total else 0.0
    bulls = [n for n, p in row["personas"].items() if p.get("signal") == "bullish"]
    bears = [n for n, p in row["personas"].items() if p.get("signal") == "bearish"]
    if action == "No data":
        reasoning = f"{row['no_data']} of {personas_total} analysts had no financial statements (ETF / commodity / unlisted data) - not scored"
    else:
        reasoning = f"{bull} bullish / {bear} bearish / {row['neutral']} neutral of {total} analysts"
    if action != "No data":
        if bulls:
            reasoning += f". Bull: {', '.join(b.replace('_', ' ').title() for b in bulls[:4])}"
        if bears:
            reasoning += f". Bear: {', '.join(b.replace('_', ' ').title() for b in bears[:4])}"
        if row["no_data"]:
            reasoning += f". {row['no_data']} analysts had no financial data"
    return {"action": action, "confidence": round(conf, 3), "score": round(score, 4), "reasoning": reasoning,
            "signal_breakdown": {"bullish": bull, "bearish": bear, "neutral": row["neutral"], "total": total,
                                 "bullish_pct": round(bull / total * 100, 1) if total else 0,
                                 "bearish_pct": round(bear / total * 100, 1) if total else 0},
            "analyst_signals": {n: {"signal": p.get("signal") or "no data", "confidence": p.get("confidence", round((p.get("score") or 0) / (p.get("max") or 1) * 100)),
                                    "reasoning": "; ".join(p.get("details") or [])[:400]} for n, p in row["personas"].items()},
            "source": "persona_scores"}
