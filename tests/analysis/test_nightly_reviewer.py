"""Tests for nightly reviewer module."""

import json
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
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


def _make_setup(**overrides):
    defaults = dict(
        symbol="GLAND", direction="short", strategy="breakout",
        entry_price=3154, stop_loss=3172.5, target_1=3122, target_2=3090,
        confidence=0.78, status="approved", reasoning="VWAP rejection + momentum",
    )
    defaults.update(overrides)
    return defaults


def test_build_prompt_includes_trade_data():
    trades = [_make_trade()]
    decisions = [
        {"timestamp": "2026-10-08T09:16:01", "symbol": "GLAND",
         "decision_type": "ENTRY_ENTER", "reason": "Momentum aligned",
         "escalated": 0, "outcome": "target_1|pnl=+1728.00"},
    ]
    setups = [_make_setup()]
    prompt = _build_prompt("2026-10-08", trades, decisions, setups, {})

    assert "GLAND" in prompt
    assert "3154" in prompt
    assert "1728" in prompt
    assert "ENTRY_ENTER" in prompt
    assert "[TRADED]" in prompt


def test_build_prompt_shows_untaken_setups():
    setups = [
        _make_setup(symbol="GLAND"),
        _make_setup(symbol="NELCAST", status="rejected"),
    ]
    prompt = _build_prompt("2026-10-08", [], [], setups, {})

    assert "GLAND" in prompt
    assert "NELCAST" in prompt
    assert "[NOT TAKEN]" in prompt


def test_build_prompt_includes_candle_data():
    trades = [_make_trade()]
    setups = [_make_setup()]
    candles = {
        "GLAND": {
            "15m": pd.DataFrame({
                "timestamp": [datetime(2026, 10, 8, 9, 15)],
                "open": [3160.0], "high": [3165.0], "low": [3148.0],
                "close": [3154.0], "volume": [50000],
            }),
            "5m": None,
            "1m": None,
        }
    }
    prompt = _build_prompt("2026-10-08", trades, [], setups, candles)

    assert "Intraday Candle Data" in prompt
    assert "3160" in prompt
    assert "15m candles" in prompt


def test_build_prompt_no_activity():
    prompt = _build_prompt("2026-10-08", [], [], [], {})
    assert "No trades or setups" in prompt


@pytest.mark.asyncio
async def test_run_nightly_review_saves_result():
    db = MagicMock()
    db.trades_for_date.return_value = [_make_trade()]
    db.get_decisions_for_date.return_value = []

    setup_store = MagicMock()
    setup_store.get_all_for_date.return_value = [_make_setup()]

    candle_store = MagicMock()
    candle_store.read.return_value = pd.DataFrame()

    llm = AsyncMock()
    llm.analyze.return_value = {
        "summary": "Good day. GLAND short hit T1.",
        "lessons": ["Entry timing was excellent"],
        "improvements": ["Tighten trail stop after T1"],
        "grade": "B",
        "_usage": MagicMock(cost_usd=MagicMock(return_value=0.003)),
    }

    result = await run_nightly_review(
        db, llm, trade_date="2026-10-08",
        setup_store=setup_store, candle_store=candle_store,
    )

    assert result["grade"] == "B"
    assert result["trades_count"] == 1
    assert result["wins"] == 1
    assert result["total_pnl"] == 1728.0
    db.save_nightly_review.assert_called_once()
    setup_store.get_all_for_date.assert_called_once_with(date(2026, 10, 8))


@pytest.mark.asyncio
async def test_run_nightly_review_skips_empty_day():
    db = MagicMock()
    db.trades_for_date.return_value = []
    db.get_decisions_for_date.return_value = []

    llm = AsyncMock()

    result = await run_nightly_review(db, llm, trade_date="2026-10-08")

    assert result["skipped"] is True
    llm.analyze.assert_not_called()


@pytest.mark.asyncio
async def test_run_nightly_review_runs_with_setups_only():
    """Review should run if setups exist even without trades."""
    db = MagicMock()
    db.trades_for_date.return_value = []
    db.get_decisions_for_date.return_value = []

    setup_store = MagicMock()
    setup_store.get_all_for_date.return_value = [_make_setup()]

    candle_store = MagicMock()
    candle_store.read.return_value = pd.DataFrame()

    llm = AsyncMock()
    llm.analyze.return_value = {
        "summary": "No trades taken despite valid setup.",
        "lessons": ["GLAND setup was correct — should have traded"],
        "improvements": ["Reduce entry drift threshold"],
        "grade": "D",
        "_usage": MagicMock(cost_usd=MagicMock(return_value=0.002)),
    }

    result = await run_nightly_review(
        db, llm, trade_date="2026-10-08",
        setup_store=setup_store, candle_store=candle_store,
    )

    assert result["grade"] == "D"
    assert result["trades_count"] == 0
    llm.analyze.assert_called_once()
