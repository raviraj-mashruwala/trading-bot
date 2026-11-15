"""RuleExecutor: a slimmed copy of tradingbot.executor.Executor for one fixed rule.

Kept from the original: the broker contract (paper and live are the same code path), the
limit-with-buffer order style Kite accepts, a resting stop order at the broker, square-off
before the close, Telegram alerts, and adoption of an open position after a restart.

Removed for rule trading: the LLM plan, the EntryGuard momentum checks, targets and partial
booking, trailing stops, momentum/pattern/Jev exits and LLM escalation. The rule decides,
the executor only carries it out.

Fixed in this copy (the original is unchanged):
  * prices sent to the broker are rounded to the exchange tick;
  * a stop order that fills at the broker is detected and recorded, instead of the executor
    sending a second exit order;
  * the exit order is polled until it fills and retried if it rests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol

from tradingbot.core.broker import BrokerError, BrokerInterface, OrderSide, OrderStatus, OrderType
from tradingbot.core.models import Direction, now_ist
from tradingbot.rule_executor.kec_rule import (
    DailyBar,
    KecRuleConfig,
    RuleSignal,
    Sizing,
    evaluate_signal,
    stop_price,
)
from tradingbot.rule_executor.store import RuleStore

logger = logging.getLogger(__name__)

TICK = 0.05
LIMIT_BUFFER = 0.01          # marketable limit: 1% through the market, as the plan executor does
ENTRY_TIMEOUT_S = 60
EXIT_RETRY_S = 30
MAX_EXIT_ATTEMPTS = 4
STOP_BACKUP_PCT = 0.005      # if price is 0.5% past the stop and the stop order has not filled, exit


class MarketData(Protocol):
    def completed_daily_bars(self, symbol: str, before: datetime, count: int) -> list[DailyBar]: ...
    def today_open(self, symbol: str) -> float | None: ...
    def size_short(self, symbol: str, price: float, buffer: float) -> Sizing: ...


def tick_down(price: float) -> float:
    return round(int(price / TICK + 1e-9) * TICK, 2)


def tick_up(price: float) -> float:
    return round(int(price / TICK + 0.999999) * TICK, 2)


@dataclass
class RuleState:
    phase: str = "waiting_signal"   # waiting_signal, waiting_entry, entry_pending, in_position, exiting, done, error
    signal: RuleSignal | None = None
    entry_order_id: str | None = None
    entry_submitted_at: datetime | None = None
    stop_order_id: str | None = None
    exit_order_id: str | None = None
    exit_submitted_at: datetime | None = None
    exit_attempts: int = 0
    exit_reason: str = ""
    trade_id: int | None = None
    quantity: int = 0
    entry_price: float = 0.0
    stop: float = 0.0
    entered_at: datetime | None = None
    last_price: float | None = None
    result: dict = field(default_factory=dict)
    sizing: dict = field(default_factory=dict)
    note: str = ""


class RuleExecutor:
    """Runs one session of the KEC short rule. tick() is synchronous and safe to call often."""

    def __init__(self, broker: BrokerInterface, market: MarketData, store: RuleStore, mode: str,
                 config: KecRuleConfig | None = None, clock: Callable[[], datetime] = now_ist,
                 telegram=None) -> None:
        self.broker = broker
        self.market = market
        self.store = store
        self.mode = mode
        self.cfg = config or KecRuleConfig()
        self.clock = clock
        self._telegram = telegram
        self.state = RuleState()
        self.trade_date = self.clock().date().isoformat()
        self.stopped = False

    # ----- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        """Resume today's trade if one exists for this mode, otherwise wait for the signal."""
        existing = self.store.trade_for_day(self.trade_date, self.mode)
        if existing is None:
            self._event("START", f"{self.mode} session started for {self.cfg.symbol}")
            if self.clock().time() > self.cfg.entry_deadline:
                self._finish(f"started after the entry window ({self.cfg.entry_deadline:%H:%M}); nothing to do today")
            return
        if existing["status"] == "closed":
            self.state.phase = "done"
            self.state.note = "already traded today"
            self._event("START", "today's trade is already closed; nothing to do")
            return
        self._resume(existing)

    def stop(self) -> None:
        """Stop the loop. An open position keeps its resting stop order at the broker."""
        self.stopped = True
        if self.state.phase in ("waiting_signal", "waiting_entry"):
            self.state.phase = "done"
        self._event("STOP", "stopped by user" + (
            "; open position left with its stop order at the broker" if self.state.phase == "in_position" else ""))

    @property
    def is_done(self) -> bool:
        return self.stopped or self.state.phase in ("done", "error")

    def tick(self) -> None:
        if self.is_done:
            return
        now = self.clock()
        t = now.time()
        try:
            if hasattr(self.broker, "advance"):
                self.broker.advance()  # paper only: let resting orders fill against the latest price
            phase = self.state.phase
            if phase == "waiting_signal" and t >= self.cfg.signal_time:
                self._evaluate(now)
            elif phase == "waiting_entry":
                if t > self.cfg.entry_deadline:
                    self._finish(f"entry window missed (started after {self.cfg.entry_deadline:%H:%M})")
                elif t >= self.cfg.entry_time:
                    self._submit_entry(now)
            elif phase == "entry_pending":
                self._poll_entry(now)
            elif phase == "in_position":
                self._manage(now)
            elif phase == "exiting":
                self._poll_exit(now)
        except Exception as exc:  # noqa: BLE001 - one failed tick (network, broker) must not end the session
            logger.warning("rule executor tick error: %s", exc, exc_info=True)
            self._event("TICK_ERROR", f"{type(exc).__name__}: {exc}; retrying next tick")

    # ----- steps ---------------------------------------------------------------------

    def _evaluate(self, now: datetime) -> None:
        bars = self.market.completed_daily_bars(self.cfg.symbol, now, self.cfg.adr_days + 5)
        today_open = self.market.today_open(self.cfg.symbol) or 0.0
        signal = evaluate_signal(bars, today_open, self.cfg)
        self.state.signal = signal
        if not signal.trade:
            self._event("SIGNAL", f"no trade: {signal.note}; gap {signal.gap_pct * 100:+.2f}%, "
                                  f"previous close at {signal.prev_close_pos * 100:.0f}% of range")
            self._finish("no signal today")
            return
        self._event("SIGNAL", "short: " + "; ".join(signal.reasons))
        self._notify(f"KEC rule ({self.mode}): short signal, " + "; ".join(signal.reasons))
        self.state.phase = "waiting_entry"

    def _submit_entry(self, now: datetime) -> None:
        ltp = self.broker.get_ltp(self.cfg.symbol)
        try:
            sizing = self.market.size_short(self.cfg.symbol, ltp, self.cfg.balance_buffer)
        except Exception as exc:  # noqa: BLE001 - never trade on a guessed size
            self._fail(f"could not size from Kite balance: {exc}")
            return
        adr = self.state.signal.adr_pct * self.cfg.stop_adr_mult if self.state.signal else None  # stop distance
        self.state.sizing = sizing.to_dict(ltp, adr)
        self._event("SIZING", (
            f"balance {sizing.available:,.0f} - buffer {self.cfg.balance_buffer:,.0f}; margin/share "
            f"{sizing.margin_per_share:.2f}; qty {sizing.quantity}; position {sizing.quantity * ltp:,.0f}"
            + (f"; loss at stop ~{sizing.quantity * ltp * adr:,.0f}" if adr else "")))
        qty = sizing.quantity
        if qty <= 0:
            self._fail("Kite balance after the buffer does not cover the margin for 1 share")
            return
        limit = tick_down(ltp * (1 - LIMIT_BUFFER))
        try:
            self.state.entry_order_id = self.broker.place_order(
                self.cfg.symbol, OrderSide.SELL, OrderType.LIMIT, qty, price=limit)
        except BrokerError as exc:
            self._fail(f"entry order rejected: {exc}")
            return
        self.state.entry_submitted_at = now
        self.state.quantity = qty
        self.state.phase = "entry_pending"
        self._event("ENTRY_SUBMITTED", f"SELL {qty} at limit {limit:.2f} (LTP {ltp:.2f})")

    def _poll_entry(self, now: datetime) -> None:
        order = self.broker.get_order(self.state.entry_order_id)
        if order is None:
            return
        filled = order.filled_quantity or 0
        if order.status is OrderStatus.COMPLETE:
            self._on_entry_filled(order.filled_quantity or order.quantity, float(order.filled_price), now)
        elif order.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
            if order.status is OrderStatus.CANCELLED and filled > 0 and order.filled_price:
                self._on_entry_filled(filled, float(order.filled_price), now)
            else:
                self._fail(f"entry order {order.status.value.lower()}")
        elif (now - self.state.entry_submitted_at).total_seconds() > ENTRY_TIMEOUT_S:
            self.broker.cancel_order(self.state.entry_order_id)
            self._event("ENTRY_TIMEOUT", "entry did not fill in 60s; cancel sent")

    def _on_entry_filled(self, qty: int, price: float, now: datetime) -> None:
        st = self.state
        st.quantity, st.entry_price, st.entered_at = qty, price, now
        st.stop = stop_price(price, st.signal.adr_pct if st.signal else 0.02, self.cfg, TICK)
        st.trade_id = self.store.open_trade(self.trade_date, self.mode, self.cfg.symbol, "short", qty,
                                            price, st.stop, now, st.signal.to_dict() if st.signal else {})
        self._place_stop()
        st.phase = "in_position"
        self._event("ENTRY_FILLED", f"short {qty} at {price:.2f}, stop {st.stop:.2f}")
        self._notify(f"KEC rule ({self.mode}): short {qty} @ {price:.2f}, stop {st.stop:.2f}")

    def _place_stop(self) -> None:
        st = self.state
        try:
            st.stop_order_id = self.broker.place_order(
                self.cfg.symbol, OrderSide.BUY, OrderType.SL, st.quantity,
                price=tick_up(st.stop * (1 + LIMIT_BUFFER)), trigger_price=st.stop)
            self.store.set_stop_order(st.trade_id, st.stop_order_id)
        except BrokerError as exc:
            st.stop_order_id = None
            self._event("STOP_REJECTED", f"stop order rejected, watching price instead: {exc}")
            self._critical(f"KEC rule ({self.mode}): stop order rejected ({exc}). Executor is watching the price; check Kite.")

    def _manage(self, now: datetime) -> None:
        st = self.state
        if st.stop_order_id is not None:
            order = self.broker.get_order(st.stop_order_id)
            if order is not None and order.status is OrderStatus.COMPLETE:
                self._record_exit(float(order.filled_price), "stop", now)
                return
            if order is not None and order.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
                self._event("STOP_LOST", f"stop order {order.status.value.lower()} at the broker; re-placing")
                self._place_stop()
        price = self.broker.get_ltp(self.cfg.symbol)
        st.last_price = price
        if now.time() >= self.cfg.exit_time:
            self._begin_exit("square_off", now)
        elif price >= st.stop * (1 + (STOP_BACKUP_PCT if st.stop_order_id else 0)):
            self._begin_exit("stop" if st.stop_order_id is None else "stop_backup", now)

    def _begin_exit(self, reason: str, now: datetime) -> None:
        st = self.state
        if st.stop_order_id is not None:
            try:
                self.broker.cancel_order(st.stop_order_id)
            except BrokerError:
                pass
            order = self.broker.get_order(st.stop_order_id)
            if order is not None and order.status is OrderStatus.COMPLETE:  # filled while cancelling
                self._record_exit(float(order.filled_price), "stop", now)
                return
            st.stop_order_id = None
        st.exit_reason = reason
        st.phase = "exiting"
        self._send_exit(now)

    def _send_exit(self, now: datetime) -> None:
        st = self.state
        ltp = self.broker.get_ltp(self.cfg.symbol)
        limit = tick_up(ltp * (1 + LIMIT_BUFFER))
        st.exit_attempts += 1
        try:
            st.exit_order_id = self.broker.place_order(
                self.cfg.symbol, OrderSide.BUY, OrderType.LIMIT, st.quantity, price=limit)
            st.exit_submitted_at = now
            self._event("EXIT_SUBMITTED", f"BUY {st.quantity} at limit {limit:.2f} ({st.exit_reason})")
        except BrokerError as exc:
            self._event("EXIT_REJECTED", str(exc))
            if st.exit_attempts >= MAX_EXIT_ATTEMPTS:
                self._critical(f"KEC rule ({self.mode}): could not close the short ({exc}). CLOSE IT MANUALLY in Kite.")
                st.phase = "error"
            else:
                st.exit_order_id = None
                st.exit_submitted_at = now

    def _poll_exit(self, now: datetime) -> None:
        st = self.state
        if st.exit_order_id is not None:
            order = self.broker.get_order(st.exit_order_id)
            if order is not None and order.status is OrderStatus.COMPLETE:
                self._record_exit(float(order.filled_price), st.exit_reason, now)
                return
            if order is not None and order.status is OrderStatus.REJECTED:
                st.exit_order_id = None
        if st.exit_submitted_at and (now - st.exit_submitted_at).total_seconds() < EXIT_RETRY_S and st.exit_order_id:
            return
        if st.exit_order_id is not None:
            try:
                self.broker.cancel_order(st.exit_order_id)
            except BrokerError:
                pass
            order = self.broker.get_order(st.exit_order_id)
            if order is not None and order.status is OrderStatus.COMPLETE:
                self._record_exit(float(order.filled_price), st.exit_reason, now)
                return
        if st.exit_attempts >= MAX_EXIT_ATTEMPTS:
            self._critical(f"KEC rule ({self.mode}): exit not filled after {st.exit_attempts} attempts. CLOSE IT MANUALLY in Kite.")
            st.phase = "error"
            return
        self._send_exit(now)

    def _record_exit(self, price: float, reason: str, now: datetime) -> None:
        st = self.state
        st.result = self.store.close_trade(st.trade_id, price, now, reason)
        st.phase = "done"
        net = st.result["net_pnl"]
        self._event("EXIT_FILLED", f"covered {st.quantity} at {price:.2f} ({reason}); net {net:+.0f} after est. charges")
        self._notify(f"KEC rule ({self.mode}): covered @ {price:.2f} ({reason}), net ₹{net:+,.0f}")

    def _resume(self, trade: dict) -> None:
        """Pick up an open trade recorded earlier today (restart mid-session)."""
        st = self.state
        st.trade_id, st.quantity = trade["id"], trade["quantity"]
        st.entry_price, st.stop = trade["entry_price"], trade["stop_price"]
        st.entered_at = datetime.fromisoformat(trade["entered_at"])
        if hasattr(self.broker, "seed_position"):  # paper: the virtual book was lost with the process
            self.broker.seed_position(self.cfg.symbol, Direction.SHORT, st.quantity, st.entry_price, st.entered_at)
            st.phase = "in_position"
            self._place_stop()
            self._event("RESUME", f"resumed paper short {st.quantity} at {st.entry_price:.2f}")
            return
        held = {p.symbol: p for p in self.broker.get_positions()}.get(self.cfg.symbol)
        if held is None or held.direction is not Direction.SHORT:
            old = trade.get("stop_order_id")
            order = self.broker.get_order(old) if old else None
            if order is not None and order.status is OrderStatus.COMPLETE:
                self._record_exit(float(order.filled_price), "stop", self.clock())
            else:
                ltp = self.broker.get_ltp(self.cfg.symbol)
                self._record_exit(ltp, "closed_outside_app", self.clock())
                self._critical("KEC rule: today's short is no longer open at Kite. Recorded at current price; "
                               "check the real exit price in Kite.")
            return
        st.phase = "in_position"
        old = trade.get("stop_order_id")
        order = self.broker.get_order(old) if old else None
        if order is not None and order.status is OrderStatus.OPEN:
            st.stop_order_id = old
        else:
            self._place_stop()
        self._event("RESUME", f"resumed live short {st.quantity} at {st.entry_price:.2f}")

    # ----- helpers -------------------------------------------------------------------

    def _finish(self, note: str) -> None:
        self.state.phase = "done"
        self.state.note = note
        self._event("DONE", note)

    def _fail(self, note: str) -> None:
        self.state.phase = "done"
        self.state.note = note
        self._event("ENTRY_FAILED", note)
        self._critical(f"KEC rule ({self.mode}): {note}")

    def _event(self, kind: str, message: str) -> None:
        logger.info("[rule %s %s] %s: %s", self.cfg.symbol, self.mode, kind, message)
        self.store.event(self.trade_date, self.mode, kind, message, self.clock())

    def _notify(self, text: str) -> None:
        if self._telegram is not None:
            try:
                self._telegram.send_sync(text)
            except Exception:  # noqa: BLE001
                logger.warning("telegram send failed", exc_info=True)

    def _critical(self, text: str) -> None:
        if self._telegram is not None:
            try:
                self._telegram.notify_critical(text)
            except Exception:  # noqa: BLE001
                logger.warning("telegram alert failed", exc_info=True)

    def status(self) -> dict:
        st = self.state
        unreal = None
        if st.phase in ("in_position", "exiting") and st.last_price is not None:
            unreal = (st.entry_price - st.last_price) * st.quantity
        return {
            "phase": st.phase,
            "mode": self.mode,
            "trade_date": self.trade_date,
            "note": st.note,
            "signal": st.signal.to_dict() if st.signal else None,
            "position": None if st.trade_id is None else {
                "quantity": st.quantity, "entry_price": st.entry_price, "stop": st.stop,
                "last_price": st.last_price, "unrealised_pnl": unreal,
                "entered_at": st.entered_at.isoformat() if st.entered_at else None,
            },
            "result": st.result or None,
            "sizing": st.sizing or None,
        }
