"""
Gate 0, manual-reasoning v2: a more genuinely reasoned judgment rule than
apply_llm_rubric_judgment.py, incorporating a signal that version ignored
entirely: whether TODAY's gap agrees or disagrees with the prevailing 5-day
trend (rs_excess).

Trading logic:
  - Gap AGREES with rs_excess sign (today's move confirms the 5-day trend):
    genuine continuation -> trade WITH rs_excess direction.
  - Gap DISAGREES with rs_excess sign (today contradicts the 5-day trend —
    e.g. gapping down after a 5-day run-up): exhaustion/distribution
    signature -> trade AGAINST rs_excess direction (fade).
  - candlestick_pattern score > 60 (a real pattern was detected — this
    factor does NOT saturate, unlike most others) adds conviction and is
    used to prioritize among qualifying candidates.
  - |rs_excess| must exceed MIN_MAGNITUDE to qualify at all — below this,
    no information either way.

This replaces v1's single "always fade if extended" rule, which ignored
whether the extension was fresh (still building, agreement) or stalling
(contradicted by today's own gap). It still doesn't have real regime/
sector LLM calls or signed candlestick direction (same limitation
production's actual LLM has for candlestick — score_candlestick only
returns magnitude) — but it uses every signal available in the dossier,
unlike v1.
"""

from __future__ import annotations

import json
from pathlib import Path

DOSSIERS_PATH = Path(__file__).parent / "output" / "llm_dossiers.json"
OUT_PATH = Path(__file__).parent / "output" / "llm_replay_candidates_v2.json"

MIN_MAGNITUDE = 8.0
EXTREME_MAGNITUDE = 25.0
PATTERN_CONVICTION_THRESHOLD = 60.0
MAX_PER_DAY = 10


def judge(candidate: dict) -> dict | None:
    rs = candidate["signed_rs_excess"]
    gap = candidate["signed_gap_pct"]
    candle = candidate["factor_scores"]["candlestick_pattern"]
    abs_rs = abs(rs)

    if abs_rs <= MIN_MAGNITUDE:
        return None

    gap_agrees = (gap > 0 and rs > 0) or (gap < 0 and rs < 0)
    # Degenerate case: gap is ~0 (no real signal from today) — fall back to
    # pure extension read, same as agreement (can't confirm disagreement).
    if abs(gap) < 0.3:
        gap_agrees = True

    if gap_agrees:
        direction = "long" if rs > 0 else "short"
        regime_tag = "trend_continuation"
    else:
        direction = "short" if rs > 0 else "long"
        regime_tag = "exhaustion_reversal"

    has_pattern = candle > PATTERN_CONVICTION_THRESHOLD
    conviction = abs_rs + (20.0 if has_pattern else 0.0)

    return {
        "symbol": candidate["symbol"],
        "direction": direction,
        "rs_excess": rs,
        "gap_agrees": gap_agrees,
        "candle_score": candle,
        "conviction_rank": conviction,
        "regime_tag": regime_tag,
    }


def main():
    with open(DOSSIERS_PATH) as f:
        dossiers = json.load(f)

    all_picks = []
    for day in dossiers:
        judged = []
        for c in day["candidates"]:
            j = judge(c)
            if j is not None:
                judged.append(j)

        judged.sort(key=lambda j: j["conviction_rank"], reverse=True)
        top = judged[:MAX_PER_DAY]

        for t in top:
            all_picks.append({
                "date": day["date"],
                "symbol": t["symbol"],
                "direction": t["direction"],
                "regime_tag": t["regime_tag"],
            })

        continuation = sum(1 for t in top if t["regime_tag"] == "trend_continuation")
        reversal = sum(1 for t in top if t["regime_tag"] == "exhaustion_reversal")
        longs = sum(1 for t in top if t["direction"] == "long")
        shorts = sum(1 for t in top if t["direction"] == "short")
        print(f"  {day['date']} ({day['split']}): {len(top)} picks "
              f"({continuation} continuation, {reversal} reversal | {longs}L/{shorts}S) "
              f"of {len(day['candidates'])} candidates")

    OUT_PATH.write_text(json.dumps(all_picks, indent=2))

    print(f"\nDone. {len(all_picks)} candidates across {len(dossiers)} days.")
    print(f"Saved to: {OUT_PATH}")

    longs = sum(1 for p in all_picks if p["direction"] == "long")
    shorts = sum(1 for p in all_picks if p["direction"] == "short")
    cont = sum(1 for p in all_picks if p["regime_tag"] == "trend_continuation")
    rev = sum(1 for p in all_picks if p["regime_tag"] == "exhaustion_reversal")
    print(f"Direction split: {longs} long, {shorts} short")
    print(f"Logic split: {cont} continuation, {rev} exhaustion-reversal")


if __name__ == "__main__":
    main()
