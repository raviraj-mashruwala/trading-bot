"""Tests for Jev shortlist pre-scorer — rank candidates before Claude."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _noul(v):
    return SimpleNamespace(noul=v)


def _score(v, c=0.8):
    return SimpleNamespace(score=v, confidence=c)


def _mock_jev(answers):
    client = MagicMock()
    client.available = True
    client.evaluate = MagicMock(return_value=answers)
    return client


def _candidate(symbol="RELIANCE", composite_score=75.0, sector="energy"):
    return {
        "symbol": symbol,
        "composite_score": composite_score,
        "sector": sector,
        "last_price": 2500.0,
        "factor_scores": {"volume_surge": 70.0, "relative_strength": 60.0},
    }


def _score_answers(quality=3.2, alignment=0.85, rr=0.78, volume=0.72):
    return {
        "setup_quality": _score(quality),
        "regime_alignment": _noul(alignment),
        "risk_reward_attractive": _noul(rr),
        "volume_conviction": _noul(volume),
    }


def test_scores_and_ranks_candidates():
    from tradingbot.analysis.jev_shortlist_scorer import score_candidates
    answers_high = _score_answers(quality=3.5, alignment=0.9)
    answers_low = _score_answers(quality=1.0, alignment=0.3)

    jev = MagicMock()
    jev.available = True
    jev.evaluate = MagicMock(side_effect=[answers_low, answers_high])

    candidates = [_candidate("WEAK", 60.0), _candidate("STRONG", 80.0)]
    result = score_candidates(jev, candidates, "trending_up")

    assert len(result) == 2
    assert result[0]["symbol"] == "STRONG"  # higher Jev composite (sorted)
    assert result[0]["jev_composite"] > result[1]["jev_composite"]


def test_filters_low_confidence():
    from tradingbot.analysis.jev_shortlist_scorer import score_candidates
    answers = _score_answers(quality=1.0)
    answers["setup_quality"] = _score(1.0, 0.2)  # low confidence

    jev = _mock_jev(answers)
    candidates = [_candidate("WEAK")]
    result = score_candidates(jev, candidates, "trending_up", min_confidence=0.4)

    assert len(result) == 0  # filtered out


def test_jev_failure_returns_original_order():
    from tradingbot.analysis.jev_shortlist_scorer import score_candidates
    jev = _mock_jev(None)
    candidates = [_candidate("A", 80.0), _candidate("B", 70.0)]
    result = score_candidates(jev, candidates, "trending_up")

    assert len(result) == 2
    assert result[0]["symbol"] == "A"  # original order preserved


def test_composite_formula():
    from tradingbot.analysis.jev_shortlist_scorer import score_candidates
    jev = _mock_jev(_score_answers(quality=4.0, alignment=1.0, rr=1.0, volume=1.0))
    candidates = [_candidate("PERFECT")]
    result = score_candidates(jev, candidates, "trending_up")

    composite = result[0]["jev_composite"]
    # 0.35 × (4/4) + 0.25 × 1.0 + 0.25 × 1.0 + 0.15 × 1.0 = 1.0
    assert abs(composite - 1.0) < 0.01


def test_returns_jev_details():
    from tradingbot.analysis.jev_shortlist_scorer import score_candidates
    jev = _mock_jev(_score_answers())
    candidates = [_candidate()]
    result = score_candidates(jev, candidates, "trending_up")

    assert "jev_composite" in result[0]
    assert "jev_setup_confidence" in result[0]
