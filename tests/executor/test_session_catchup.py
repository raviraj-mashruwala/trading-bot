"""Tests for SessionCatchup — late-start morning context fetch and decisions."""

import pytest
from datetime import date, datetime, time
from unittest.mock import MagicMock

from tradingbot.executor.session_catchup import SessionCatchup, MorningContext


def _make_candles(n: int, base_price: float = 500.0, trend: str = "up"):
    rows = []
    price = base_price
    for i in range(n):
        delta = 0.5 if trend == "up" else -0.5 if trend == "down" else 0
        price += delta
        rows.append({
            "date": datetime(2026, 10, 15, 9, 15 + i),
            "open": price - 0.2,
            "high": price + 0.3,
            "low": price - 0.4,
            "close": price,
            "volume": 10000 + i * 100,
        })
    return rows


def test_compute_morning_context_uptrend():
    candles = _make_candles(30, base_price=500.0, trend="up")
    ctx = SessionCatchup._compute_context(candles, 498.0)
    assert isinstance(ctx, MorningContext)
    assert ctx.gap_pct == pytest.approx((candles[0]["open"] - 498.0) / 498.0 * 100, abs=0.1)
    assert ctx.trend == "up"
    assert ctx.vwap > 0
    assert ctx.candle_count == 30


def test_compute_morning_context_empty_candles():
    ctx = SessionCatchup._compute_context([], 500.0)
    assert ctx is None


def test_should_run_before_market():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    assert catchup.should_run(time(8, 55)) is False


def test_should_run_just_after_open():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    assert catchup.should_run(time(9, 20)) is False


def test_should_run_late_start():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    assert catchup.should_run(time(10, 0)) is True


def test_should_run_after_market():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    assert catchup.should_run(time(15, 35)) is False


def test_fetch_morning_context_kite_failure():
    kite = MagicMock()
    kite.fetch_historical.side_effect = Exception("API error")
    cache = MagicMock()
    cache.get_token.return_value = 12345
    catchup = SessionCatchup(kite_client=kite, instrument_cache=cache)
    result = catchup.fetch_morning_context(["BADSTOCK"])
    assert result == {}


# --- Task 2: Deterministic decision tests ---

from tradingbot.executor.session_catchup import CatchupDecision, apply_catchup_decisions
from tradingbot.core.models import TradeLeg, Direction, StrategyName, EntryType


def _make_leg(symbol: str, entry: float, direction: str = "long") -> TradeLeg:
    return TradeLeg(
        symbol=symbol,
        exchange="NSE",
        strategy=StrategyName.MOMENTUM,
        direction=Direction(direction),
        entry_price=entry,
        entry_type=EntryType.LIMIT,
        stop_loss=entry * 0.98,
        target_1=entry * 1.03,
        target_2=entry * 1.05,
        quantity=100,
        risk_amount=entry * 0.02 * 100,
        entry_window_start=time(9, 15),
        entry_window_end=time(14, 0),
        max_entry_wait=time(12, 0),
        exit_before=time(15, 10),
        confidence=0.7,
        reasoning="test",
    )


def _make_context(symbol: str, current: float, gap: float = 0.5, trend: str = "up") -> MorningContext:
    return MorningContext(
        symbol=symbol, prev_close=current - 5, open_price=current - 3,
        gap_pct=gap, high=current + 2, low=current - 4,
        current_price=current, vwap=current - 1, volume_total=500000,
        volume_vs_avg=1.2, trend=trend, candle_count=30, minutes_elapsed=30,
    )


def test_deterministic_fallback_skip_large_gap():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    ctx = _make_context("TEST", 520.0, gap=4.0)
    leg = _make_leg("TEST", 500.0)
    decision = catchup._deterministic_decision(ctx, leg)
    assert decision.action == "skip"
    assert "gap" in decision.reason.lower()


def test_deterministic_fallback_skip_price_drift():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    ctx = _make_context("TEST", 550.0)
    leg = _make_leg("TEST", 500.0)
    decision = catchup._deterministic_decision(ctx, leg)
    assert decision.action == "skip"
    assert "drift" in decision.reason.lower()


def test_deterministic_fallback_proceed():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    ctx = _make_context("TEST", 502.0, gap=0.5, trend="up")
    leg = _make_leg("TEST", 500.0)
    decision = catchup._deterministic_decision(ctx, leg)
    assert decision.action == "proceed"


def test_deterministic_short_against_uptrend():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    ctx = _make_context("TEST", 502.0, trend="up")
    leg = _make_leg("TEST", 500.0, direction="short")
    decision = catchup._deterministic_decision(ctx, leg)
    assert decision.action == "skip"


def test_catchup_skips_invalidated_legs():
    class FakeLegState:
        def __init__(self, symbol):
            self.leg = _make_leg(symbol, 500.0)
            self.waiting = True
            self.skipped_reason = None
            self.cancelled = False

    states = [FakeLegState("SKIP_ME"), FakeLegState("KEEP_ME")]
    decisions = {
        "SKIP_ME": CatchupDecision("SKIP_ME", "skip", "gap too large", 0.2),
        "KEEP_ME": CatchupDecision("KEEP_ME", "proceed", "OK", 0.7),
    }
    apply_catchup_decisions(states, decisions)
    assert states[0].skipped_reason is not None
    assert states[0].waiting is False
    assert states[1].waiting is True
    assert states[1].skipped_reason is None


class _FakeJev:
    """Stands in for JevClient: same evaluate(state, questions) -> answers | None surface."""

    def __init__(self, answers=None, available: bool = True):
        self.available = available
        self._answers = answers
        self.calls: list[tuple[dict, dict]] = []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        return self._answers


def _jev_answers(proceed: float, invalidated: float) -> dict:
    from types import SimpleNamespace
    return {
        "should_proceed": SimpleNamespace(noul=proceed),
        "invalidated": SimpleNamespace(noul=invalidated),
    }


def _catchup_with(jev) -> SessionCatchup:
    return SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock(), jev_client=jev)


def test_jev_proceed_answer_is_used():
    catchup = _catchup_with(_FakeJev(_jev_answers(proceed=0.8, invalidated=0.1)))
    decisions = catchup.evaluate({"TEST": _make_context("TEST", 502.0)}, [_make_leg("TEST", 500.0)])
    d = decisions["TEST"]
    assert d.action == "proceed"
    assert d.reason.startswith("Jev:")
    assert d.confidence == 0.8


def test_jev_invalidated_answer_skips_the_leg():
    catchup = _catchup_with(_FakeJev(_jev_answers(proceed=0.6, invalidated=0.9)))
    decisions = catchup.evaluate({"TEST": _make_context("TEST", 502.0)}, [_make_leg("TEST", 500.0)])
    assert decisions["TEST"].action == "skip"
    assert "invalidated" in decisions["TEST"].reason


def test_jev_low_confidence_answer_skips_the_leg():
    catchup = _catchup_with(_FakeJev(_jev_answers(proceed=0.3, invalidated=0.2)))
    decisions = catchup.evaluate({"TEST": _make_context("TEST", 502.0)}, [_make_leg("TEST", 500.0)])
    assert decisions["TEST"].action == "skip"
    assert decisions["TEST"].reason.startswith("Jev:")


def test_jev_receives_setup_facts_and_both_questions():
    jev = _FakeJev(_jev_answers(proceed=0.8, invalidated=0.1))
    leg = _make_leg("TEST", 500.0, "short")
    _catchup_with(jev).evaluate({"TEST": _make_context("TEST", 502.0, gap=-1.3, trend="down")}, [leg])

    state, questions = jev.calls[0]
    assert state["symbol"] == "TEST"
    assert state["direction"] == "short"
    assert state["planned_entry"] == 500.0
    assert state["gap_pct"] == -1.3
    assert state["trend"] == "down"
    assert set(questions) == {"should_proceed", "invalidated"}


def test_no_jev_answer_falls_back_to_deterministic_rules():
    catchup = _catchup_with(_FakeJev(answers=None))
    decisions = catchup.evaluate({"TEST": _make_context("TEST", 550.0)}, [_make_leg("TEST", 500.0)])
    assert decisions["TEST"].action == "skip"
    assert "drift" in decisions["TEST"].reason.lower()


def test_unavailable_jev_is_not_called():
    jev = _FakeJev(_jev_answers(0.9, 0.0), available=False)
    decisions = _catchup_with(jev).evaluate({"TEST": _make_context("TEST", 502.0)}, [_make_leg("TEST", 500.0)])
    assert jev.calls == []
    assert not decisions["TEST"].reason.startswith("Jev:")


def test_no_jev_client_decides_by_rules_without_warning_noise(caplog):
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    with caplog.at_level("WARNING"):
        decisions = catchup.evaluate({"TEST": _make_context("TEST", 502.0)}, [_make_leg("TEST", 500.0)])
    assert decisions["TEST"].action == "proceed"
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []
