"""Jev-based Tier 2 analyzer: regime classification + sector scoring."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.jev_client import JevClient, Choice, Noul, Score

log = logging.getLogger(__name__)

SECTORS = ["banking", "it", "pharma", "auto", "metal", "fmcg", "energy", "realty", "infra"]


def _build_regime_questions() -> dict:
    try:
        if Choice is None:
            return {}
    except Exception:
        return {}
    return {
        "regime": Choice(
            instructions="What is the current market regime based on the data?",
            criteria={
                "trending_up": "Broad uptrend — rising index, healthy breadth, institutional buying",
                "trending_down": "Broad downtrend — falling index, poor breadth, institutional selling",
                "range_bound": "Sideways — low directional conviction, mixed signals",
                "volatile": "High VIX, sharp intraday swings, uncertain direction",
                "low_vol_squeeze": "Compressed volatility, low VIX, narrow range — breakout likely",
            },
        ),
        "regime_confidence_level": Score(
            instructions="How clear is the market regime signal?",
            criteria=[
                "Low clarity — conflicting indicators, hard to classify",
                "Some signal — leans one way but not convincing",
                "Clear signal — most indicators agree",
                "Very strong signal — overwhelming agreement across indicators",
            ],
        ),
        "bias": Choice(
            instructions="What is the overall directional bias?",
            criteria={
                "bullish": "Net positive outlook — favor long trades",
                "bearish": "Net negative outlook — favor shorts or stay defensive",
                "neutral": "No clear directional edge",
            },
        ),
        "risk_appetite": Choice(
            instructions="What risk stance should trading take today?",
            criteria={
                "aggressive": "Strong signals, take full position sizes",
                "moderate": "Mixed signals, standard position sizes",
                "defensive": "Uncertain or adverse conditions, reduce size or sit out",
            },
        ),
        "trend_strength": Score(
            instructions="How strong is the prevailing directional trend?",
            criteria=[
                "No clear trend — choppy or flat",
                "Weak trend — some directional bias but fragile",
                "Moderate trend — clear direction with some counter-signals",
                "Strong trend — broad participation, aligned indicators",
            ],
        ),
        "institutional_sentiment": Score(
            instructions="How bullish is institutional flow (FII + DII combined)?",
            criteria=[
                "Strongly bearish — heavy net selling",
                "Mildly bearish — net selling but not extreme",
                "Neutral — mixed or minimal flow",
                "Mildly bullish — net buying",
                "Strongly bullish — heavy net buying from both",
            ],
        ),
    }


def _build_sector_questions() -> dict:
    try:
        if Noul is None:
            return {}
    except Exception:
        return {}
    questions: dict[str, Any] = {}
    for sector in SECTORS:
        questions[f"{sector}_momentum"] = Score(
            instructions=f"How strong is `{sector}` sector's momentum based on the data?",
            criteria=[
                "Weak — underperforming, declining, no institutional interest",
                "Below average — flat or lagging the market",
                "Average — in line with broader market",
                "Above average — outperforming with some catalysts",
                "Strong — leading sector with heavy flows and clear momentum",
            ],
        )
        questions[f"{sector}_rotation"] = Noul(
            instructions=f"Is money rotating INTO `{sector}` sector (vs rotating out)?",
        )
    return questions


class JevTier2Analyzer:
    """Replace Claude Tier 2 calls for regime and sectors with Jev."""

    def __init__(self, jev_client: JevClient) -> None:
        self._jev = jev_client

    async def analyze_regime(
        self,
        nifty: float,
        banknifty: float,
        vix: float,
        nifty_5d_change: float,
        fii_5d_net: float,
        dii_5d_net: float,
        advance_decline: float,
        sector_data: dict[str, float],
    ) -> dict[str, Any] | None:
        state = {
            "nifty_level": nifty,
            "banknifty_level": banknifty,
            "india_vix": vix,
            "nifty_5d_change_pct": nifty_5d_change,
            "fii_5d_net_crores": fii_5d_net,
            "dii_5d_net_crores": dii_5d_net,
            "advance_decline_ratio": advance_decline,
            "sector_changes": sector_data,
        }

        answers = self._jev.evaluate(state=state, questions=_build_regime_questions())
        if answers is None:
            return None

        try:
            regime = answers["regime"].choice
            conf = answers["regime_confidence_level"].score / 3.0
            bias = answers["bias"].choice
            risk = answers["risk_appetite"].choice

            reasoning = (
                f"jev: regime={regime}(conf={conf:.2f}), bias={bias}, "
                f"risk={risk}, trend={answers['trend_strength'].score / 3.0:.2f}, "
                f"institutional={answers['institutional_sentiment'].score / 4.0:.2f}"
            )

            return {
                "regime": regime,
                "regime_confidence": round(conf, 2),
                "bias": bias,
                "key_levels": {},
                "sectors_in_play": [],
                "sectors_to_avoid": [],
                "risk_appetite": risk,
                "reasoning": reasoning,
            }
        except Exception:
            log.warning("Jev regime answer parsing failed", exc_info=True)
            return None

    async def analyze_sectors(
        self,
        regime: dict,
        sector_data: dict,
        top_stocks_by_sector: dict,
    ) -> dict[str, Any] | None:
        state = {
            "market_regime": regime.get("regime", "unknown"),
            "sector_data": sector_data,
        }

        answers = self._jev.evaluate(state=state, questions=_build_sector_questions())
        if answers is None:
            return None

        try:
            scored = []
            for sector in SECTORS:
                mom_raw = answers[f"{sector}_momentum"].score
                mom = mom_raw / 4.0 if mom_raw == mom_raw else 0.0
                rot = answers[f"{sector}_rotation"].noul
                rot = rot if rot == rot else 0.0
                composite = 0.6 * mom + 0.4 * rot
                scored.append({"name": sector, "momentum": mom, "rotation": rot,
                               "composite": composite})

            scored.sort(key=lambda s: s["composite"], reverse=True)

            sectors_out = []
            for i, s in enumerate(scored):
                if i < 3:
                    bias = "bullish"
                elif i >= len(scored) - 3:
                    bias = "bearish"
                else:
                    bias = "neutral"
                sectors_out.append({
                    "name": s["name"],
                    "intraday_bias": bias,
                    "theme": "sector rotation",
                    "catalyst": f"jev: momentum={s['momentum']:.2f}, rotation={s['rotation']:.2f}",
                })

            return {
                "sectors": sectors_out,
                "reasoning": f"jev: {len(SECTORS)} sectors scored, ranked by composite",
            }
        except Exception:
            log.warning("Jev sector answer parsing failed", exc_info=True)
            return None
