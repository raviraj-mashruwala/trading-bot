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


@router.post("/scorecards/{trade_id}/grade")
async def grade_scorecard(request: Request, trade_id: int):
    state: AppState = request.app.state.app_state
    if not getattr(state.config, "jev", None) or not state.config.jev.enabled:
        raise HTTPException(status_code=400, detail="Jev not enabled")

    from tradingbot.core.jev_client import JevClient
    jev = JevClient(state.config.jev)
    if not jev.available:
        raise HTTPException(status_code=503, detail="Jev service unavailable")

    rs = _get_review_store(state)
    try:
        card = rs.get_scorecard(trade_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Trade not found")

        from tradingbot.analysis.jev_trade_grader import grade_trade
        grade = await grade_trade(jev, _serialize_scorecard(card))
        return {"trade_id": trade_id, **grade}
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


@router.post("/nightly")
async def run_nightly_review(request: Request, date: str | None = None):
    import logging
    state: AppState = request.app.state.app_state

    from tradingbot.core.llm.anthropic_provider import build_provider
    llm = build_provider(state.config.llm, state.config.secrets)

    from tradingbot.analysis.nightly_reviewer import run_nightly_review as _run
    from tradingbot.core.database import Database

    db = Database(Path(state.data_dir) / "tradingbot.db")
    db.initialise()
    try:
        review = await _run(
            db, llm, trade_date=date,
            setup_store=getattr(state, "setup_store", None),
            candle_store=getattr(state, "candle_store", None),
        )
        return review
    except Exception as exc:
        logging.getLogger(__name__).error("Nightly review failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Nightly review failed")
    finally:
        db.close()


@router.get("/nightly")
async def get_nightly_review(request: Request, date: str | None = None):
    state: AppState = request.app.state.app_state
    from tradingbot.core.database import Database

    db = Database(Path(state.data_dir) / "tradingbot.db")
    db.initialise()
    try:
        if date:
            review = db.get_nightly_review(date)
        else:
            reviews = db.get_recent_reviews(limit=1)
            review = reviews[0] if reviews else None
        if review is None:
            raise HTTPException(status_code=404, detail="No review found")
        return review
    finally:
        db.close()


@router.get("/nightly/history")
async def get_nightly_history(request: Request, limit: int = 10):
    state: AppState = request.app.state.app_state
    from tradingbot.core.database import Database

    db = Database(Path(state.data_dir) / "tradingbot.db")
    db.initialise()
    try:
        return db.get_recent_reviews(limit=limit)
    finally:
        db.close()
