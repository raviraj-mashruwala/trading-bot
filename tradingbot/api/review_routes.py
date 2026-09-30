"""Review and performance analysis endpoints."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.models import TradeScorecard
from tradingbot.persistence.review_store import TradeReviewStore

router = APIRouter(prefix="/api/review")


def _serialize_scorecard(sc: TradeScorecard) -> dict:
    d = asdict(sc)
    d["r_multiple"] = sc.r_multiple
    d["hit_target"] = sc.hit_target
    d["invalidation_fired"] = sc.invalidation_fired
    d["entry_slippage"] = sc.entry_slippage
    d["predicted_rr"] = sc.predicted_rr
    d["actual_rr"] = sc.actual_rr
    return d


def _get_review_store(state: AppState) -> TradeReviewStore:
    return TradeReviewStore(Path(state.data_dir) / "tradingbot.db")


@router.get("/scorecards")
async def get_scorecards(request: Request, date: str | None = None):
    state: AppState = request.app.state.app_state
    rs = _get_review_store(state)
    try:
        if date:
            cards = rs.get_scorecards_for_date(date)
        else:
            from datetime import date as d
            cards = rs.get_scorecards_for_date(str(d.today()))
        return [_serialize_scorecard(c) for c in cards]
    finally:
        rs.close()


@router.get("/scorecards/{trade_id}")
async def get_scorecard(request: Request, trade_id: int):
    state: AppState = request.app.state.app_state
    rs = _get_review_store(state)
    try:
        card = rs.get_scorecard(trade_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Trade not found or not linked to a setup")
        return _serialize_scorecard(card)
    finally:
        rs.close()


@router.get("/stats")
async def get_stats(request: Request, days: int = 30):
    state: AppState = request.app.state.app_state
    rs = _get_review_store(state)
    try:
        stats = rs.get_performance_stats(lookback_days=days)
        return asdict(stats)
    finally:
        rs.close()
