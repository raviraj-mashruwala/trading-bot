"""
Gate 0, manual-reasoning variant: applies a single, consistent, mean-reversion-
aware judgment rule to the dossiers prepared by prepare_llm_dossiers.py.

This is NOT a per-stock bespoke LLM call — at 325 stock-days across 13
dossiers, freehand reasoning over each row individually isn't tractable in
one session. Instead, this implements the SHORTLIST_SYSTEM prompt's own
explicit guidance (tradingbot/analysis/prompts.py) as a calibrated rule:

  "In trending_down, a stock up 15% with RSI>70 may be a high-conviction
   SHORT (mean-reversion/pullback) rather than a long... Evaluate where the
   NEXT move is, not where the stock has been."

The RS-sign proxy tested in backtest_replay_holdout.py had ZERO mean-reversion
logic (positive 5d excess -> always long, negative -> always short). That is
the specific gap this closes:

  - |rs_excess| > EXTENDED_THRESHOLD: stock is overextended relative to the
    market -> bet on reversal (fade), not continuation.
  - MODERATE_MIN < |rs_excess| <= EXTENDED_THRESHOLD: stock is in a healthy,
    not-yet-exhausted trend -> bet on continuation.
  - |rs_excess| <= MODERATE_MIN: no clear edge -> excluded (real production
    requires 10-15 picks; this version allows fewer per day when the signal
    is genuinely weak, which is itself a judgment call worth flagging).

This is honest middle ground between the naive proxy and a full per-stock
LLM call: real trading judgment, applied consistently, at zero marginal
API cost.
"""

from __future__ import annotations

import json
from pathlib import Path

DOSSIERS_PATH = Path(__file__).parent / "output" / "llm_dossiers.json"
OUT_PATH = Path(__file__).parent / "output" / "llm_replay_candidates.json"

EXTENDED_THRESHOLD = 12.0
MODERATE_MIN = 3.0
MAX_PER_DAY = 10


def judge(candidate: dict) -> dict | None:
    rs = candidate["signed_rs_excess"]
    abs_rs = abs(rs)

    if abs_rs <= MODERATE_MIN:
        return None  # no clear edge

    if abs_rs > EXTENDED_THRESHOLD:
        # Overextended -> fade (mean reversion)
        direction = "short" if rs > 0 else "long"
        regime_tag = "overextended_fade"
    else:
        # Healthy trend -> continuation
        direction = "long" if rs > 0 else "short"
        regime_tag = "trend_continuation"

    return {
        "symbol": candidate["symbol"],
        "direction": direction,
        "rs_excess": rs,
        "conviction_rank": abs_rs,
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

        fades = sum(1 for t in top if t["regime_tag"] == "overextended_fade")
        trends = sum(1 for t in top if t["regime_tag"] == "trend_continuation")
        print(f"  {day['date']} ({day['split']}): {len(top)} picks "
              f"({fades} fade, {trends} continuation) of {len(day['candidates'])} candidates")

    OUT_PATH.write_text(json.dumps(all_picks, indent=2))

    print(f"\nDone. {len(all_picks)} candidates across {len(dossiers)} days.")
    print(f"Saved to: {OUT_PATH}")

    longs = sum(1 for p in all_picks if p["direction"] == "long")
    shorts = sum(1 for p in all_picks if p["direction"] == "short")
    fades = sum(1 for p in all_picks if p["regime_tag"] == "overextended_fade")
    trends = sum(1 for p in all_picks if p["regime_tag"] == "trend_continuation")
    print(f"Direction split: {longs} long, {shorts} short")
    print(f"Logic split: {fades} overextended-fade, {trends} trend-continuation")


if __name__ == "__main__":
    main()
