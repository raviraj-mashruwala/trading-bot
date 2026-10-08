"""Tests for nightly reviewer module."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tradingbot.analysis.nightly_reviewer import run_nightly_review, _build_prompt
from tradingbot.core.models import (
    Direction, ExecutedTrade, Mode, StrategyName, TradeStatus,
)


def _make_trade(**overrides):
    defaults = dict(
        trade_date="2026-10-08", symbol="GLAND", strategy=StrategyName.BREAKOUT,
        direction=Direction.SHORT, quantity=54, entry_price=3154.0,
        exit_price=3122.0, stop_loss=3172.5, target_1=3122.0, target_2=3090.0,
        entered_at=datetime(2026, 10, 8, 9, 16, 11),
        exited_at=datetime(2026, 10, 8, 9, 25, 1),
        pnl=1728.0, exit_reason="target_1", status=TradeStatus.CLOSED, mode=Mode.LIVE,
    )
    defaults.update(overrides)
    return ExecutedTrade(**defaults)


def test_build_prompt_includes_trade_data():
    trades = [_make_trade()]
    decisions = [
        {"timestamp": "2026-10-08T09:16:01", "symbol": "GLAND",
         "decision_type": "ENTRY_ENTER", "reason": "Momentum aligned",
         "escalated": 0, "outcome": "target_1|pnl=+1728.00"},
    ]
    prompt = _build_prompt("2026-10-08", trades, decisions)

    assert "GLAND" in prompt
    assert "3154" in prompt
    assert "1728" in prompt
    assert "ENTRY_ENTER" in prompt


def test_build_prompt_no_trades():
    prompt = _build_prompt("2026-10-08", [], [])
    assert "No trades" in prompt


@pytest.mark.asyncio
async def test_run_nightly_review_saves_result():
    db = MagicMock()
    db.trades_for_date.return_value = [_make_trade()]
    db.get_decisions_for_date.return_value = []

    llm = AsyncMock()
    llm.analyze.return_value = {
        "summary": "Good day. GLAND short hit T1.",
        "lessons": ["Entry timing was excellent"],
        "improvements": ["Tighten trail stop after T1"],
        "grade": "B",
        "_usage": MagicMock(cost_usd=MagicMock(return_value=0.003)),
    }

    result = await run_nightly_review(db, llm, trade_date="2026-10-08")

    assert result["grade"] == "B"
    assert result["trades_count"] == 1
    assert result["wins"] == 1
    assert result["total_pnl"] == 1728.0
    db.save_nightly_review.assert_called_once()


@pytest.mark.asyncio
async def test_run_nightly_review_skips_empty_day():
    db = MagicMock()
    db.trades_for_date.return_value = []
    db.get_decisions_for_date.return_value = []

    llm = AsyncMock()

    result = await run_nightly_review(db, llm, trade_date="2026-10-08")

    assert result["skipped"] is True
    llm.analyze.assert_not_called()
