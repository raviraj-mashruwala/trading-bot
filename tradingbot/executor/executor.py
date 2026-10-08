"""The executor agent: reads a plan and follows it. No model, no judgement calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from tradingbot.core.broker import BrokerInterface, OrderStatus
from tradingbot.core.config import ExecutionConfig
from tradingbot.core.database import Database
from tradingbot.core.models import (
    Direction,
    ExecutedTrade,
    Mode,
    TradeLeg,
    TradePlan,
    TradeStatus,
    now_ist,
)
from tradingbot.core.risk_manager import RiskManager
from tradingbot.executor.adaptive_exit_manager import ExitDecision
from tradingbot.executor.exit_manager import ExitManager
from tradingbot.executor.order_manager import OrderManager
from tradingbot.executor.position_monitor import PositionMonitor

if TYPE_CHECKING:
    from tradingbot.executor.execution_intelligence import ExecutionIntelligence

logger = logging.getLogger(__name__)


@dataclass
class LegState:
    """Everything the executor knows about one leg right now."""

    leg: TradeLeg
    entry_order_id: str | None = None
    stop_order_id: str | None = None
    filled_quantity: int = 0
    entry_fill_price: float = 0.0
    current_stop: float = 0.0
    target_1_booked: bool = False
    cancelled: bool = False
    adopted: bool = False
    skipped_reason: str | None = None
    entered_at: datetime | None = None
    realised_pnl: float = 0.0
    waiting: bool = False

    def __post_init__(self) -> None:
        if self.current_stop == 0.0:
            self.current_stop = self.leg.stop_loss

    @property
    def is_finished(self) -> bool:
        return self.cancelled or self.skipped_reason is not None or (
            self.entered_at is not None and self.filled_quantity == 0
        )


class Executor:
    """Runs one trading session against one plan."""

    def __init__(
        self,
        broker: BrokerInterface,
        plan: TradePlan,
        risk_manager: RiskManager,
        database: Database,
        execution_config: ExecutionConfig,
        mode: Mode,
        clock=now_ist,
        event_bus=None,
        intelligence: ExecutionIntelligence | None = None,
        regime_monitor=None,
    ) -> None:
        self.broker = broker
        self.plan = plan
        self.risk_manager = risk_manager
        self.database = database
        self.config = execution_config
        self.mode = mode
        self.clock = clock
        self.event_bus = event_bus
        self._intelligence = intelligence
        self._regime_monitor = regime_monitor
        self._current_regime: str | None = None

        if intelligence is None:
            import warnings
            warnings.warn(
                "Executor without intelligence is deprecated — classic mode will be removed",
                DeprecationWarning,
                stacklevel=2,
            )

        self.orders = OrderManager(broker)
        self.monitor = PositionMonitor(broker)
        self.exits = ExitManager(execution_config.square_off_time)

        self.states: list[LegState] = []
        self.blocked = False
        self.kill_switch_tripped = False

    # ----- Lifecycle --------------------------------------------------------------

    def start(self) -> None:
        """Vet the plan, adopt anything already open, then submit entries."""
        now = self.clock()
        blockers = self.risk_manager.vet_plan_for_execution(
            self.plan, now=now, available_capital=self.broker.available_margin()
        )
        if blockers:
            for reason in blockers:
                logger.error("refusing to execute: %s", reason)
            self.blocked = True
            return

        if self.event_bus:
            self.event_bus.emit_sync("exec.started", {
                "trade_date": self.plan.trade_date,
                "mode": self.mode.value,
                "legs": [leg.to_dict() for leg in self.plan.legs],
            })

        if self._intelligence is not None:
            symbols = list({leg.symbol for leg in self.plan.legs})
            self._intelligence.start(symbols)

        open_positions = self.monitor.snapshot()

        for leg in self.plan.legs:
            state = LegState(leg=leg)
            self.states.append(state)

            existing = open_positions.get(leg.symbol)
            if existing is not None:
                self._adopt(state, existing)
                continue

            price = self.broker.get_ltp(leg.symbol)
            drift = self.risk_manager.vet_leg_at_open(leg, price)
            if drift is not None:
                logger.warning("skipping %s: %s", leg.symbol, drift)
                state.skipped_reason = drift
                continue

            if self._intelligence is not None:
                self._evaluate_entry(state, now)
            else:
                self._submit_entry(state)

    def tick(self) -> None:
        """One pass of the event loop. Safe to call as often as you like."""
        if self.blocked:
            return

        now = self.clock()

        if not self.kill_switch_tripped:
            # _close() writes every exit to the database as it happens, so the
            # database is the single source of truth here. Adding an in-memory
            # tally on top would double count each loss.
            realised = self.database.realised_pnl_for_date(self.plan.trade_date)
            if self.risk_manager.daily_loss_breached(realised):
                logger.error("daily loss limit breached at %.2f; halting", realised)
                self.kill_switch_tripped = True
                self._halt_everything(now)
                return

        if self._regime_monitor and self._regime_monitor.should_check(now):
            result = self._regime_monitor.check({}, self._current_regime or "unknown")
            if result.changed:
                self._current_regime = result.new_regime
                logger.warning("Regime shift to %s — monitoring positions", result.new_regime)

        for state in self.states:
            if state.is_finished:
                continue

            if state.filled_quantity == 0:
                # Re-evaluate WAIT legs through the guard on each heartbeat
                if state.waiting and not state.cancelled:
                    now_time = now.timetz().replace(tzinfo=None)
                    if now_time >= state.leg.max_entry_wait or now_time >= state.leg.entry_window_end:
                        state.skipped_reason = "Wait timeout — conditions never cleared"
                        state.cancelled = True
                        logger.info(
                            "%s wait timed out at %s", state.leg.symbol, now_time,
                        )
                        continue
                    if self._intelligence is not None:
                        self._evaluate_entry(state, now)
                        if state.waiting:
                            continue  # still waiting, skip poll
                self._poll_entry(state, now)
                continue

            self._manage_open_leg(state, now)

    @property
    def is_done(self) -> bool:
        """True once no leg can do anything further today."""
        if self.blocked:
            return True
        return all(state.is_finished for state in self.states)

    # ----- Entry handling ---------------------------------------------------------

    def _evaluate_entry(self, state: LegState, now: datetime) -> None:
        """Consult EntryGuard before placing an order. ENTER / WAIT / VETO."""
        intel = self._intelligence
        symbol_state = intel.scorer.get_state(state.leg.symbol)
        if symbol_state is None:
            current_1m = intel.aggregator.get_current(state.leg.symbol, "1min")
            if current_1m is not None:
                symbol_state = intel.scorer.update(
                    state.leg.symbol,
                    [current_1m],
                    intel.aggregator.get_candles(state.leg.symbol, "5min") or [],
                )
        if symbol_state is None:
            state.waiting = True
            logger.warning(
                "%s waiting: no candle data yet — will not enter without market data",
                state.leg.symbol,
            )
            return

        state_ts = symbol_state.timestamp
        if now.tzinfo is not None and state_ts.tzinfo is None:
            state_ts = state_ts.replace(tzinfo=now.tzinfo)
        elif now.tzinfo is None and state_ts.tzinfo is not None:
            state_ts = state_ts.replace(tzinfo=None)
        stale_seconds = (now - state_ts).total_seconds()
        if stale_seconds > 120:
            state.waiting = True
            logger.warning(
                "%s waiting: market data is %.0fs stale (>120s) — possible ticker disconnect",
                state.leg.symbol, stale_seconds,
            )
            return

        price = intel.aggregator.last_price(state.leg.symbol) or state.leg.entry_price
        verdict = intel.entry_guard.evaluate(state.leg, symbol_state, price, now)

        if verdict.action == "ENTER":
            if intel.is_degraded:
                state.waiting = True
                logger.warning(
                    "%s waiting: ticker degraded — blocking new entries until data recovers",
                    state.leg.symbol,
                )
                return
            if verdict.confidence < 0.4:
                # Gray zone: attempt LLM escalation (best-effort, async-safe)
                try:
                    import asyncio
                    coro = intel.escalator.evaluate_entry(
                        state.leg,
                        symbol_state,
                        intel.aggregator.get_candles(state.leg.symbol, "1min"),
                        intel.aggregator.get_candles(state.leg.symbol, "5min"),
                        ticker_degraded=intel.is_degraded,
                    )
                    try:
                        loop = asyncio.get_running_loop()
                        # API path: already in an async context
                        import concurrent.futures
                        future = asyncio.run_coroutine_threadsafe(coro, loop)
                        result = future.result(timeout=12)
                    except RuntimeError:
                        # CLI path: no running loop
                        result = asyncio.run(coro)

                    if result.action == "VETO":
                        state.skipped_reason = f"LLM veto: {result.reasoning}"
                        state.cancelled = True
                        logger.info(
                            "%s vetoed by LLM: %s", state.leg.symbol, result.reasoning
                        )
                        return
                    if result.action == "WAIT":
                        state.waiting = True
                        return
                except Exception:
                    logger.warning("LLM escalation failed — blocking entry for safety", exc_info=True)
                    state.waiting = True
                    return
            state.waiting = False
            self._submit_entry(state)

        elif verdict.action == "VETO":
            state.skipped_reason = verdict.reason
            state.cancelled = True
            logger.info(
                "%s vetoed by EntryGuard: %s", state.leg.symbol, verdict.reason
            )

        else:  # WAIT
            state.waiting = True
            logger.info(
                "%s waiting: %s (reassess in %ds)",
                state.leg.symbol, verdict.reason, verdict.reassess_after,
            )

    def _submit_entry(self, state: LegState) -> None:
        """Place the entry order via OrderManager."""
        state.entry_order_id = self.orders.submit_entry(state.leg)

    def _poll_entry(self, state: LegState, now: datetime) -> None:
        if state.entry_order_id is None:
            return

        status = self.orders.order_status(state.entry_order_id)

        if status is OrderStatus.COMPLETE:
            order = self.broker.get_order(state.entry_order_id)
            state.filled_quantity = order.quantity
            state.entry_fill_price = float(order.filled_price)
            state.entered_at = now
            state.current_stop = state.leg.stop_loss
            state.stop_order_id = self.orders.submit_stop(state.leg, state.filled_quantity)
            logger.info(
                "%s filled x%d at %.2f", state.leg.symbol, state.filled_quantity, state.entry_fill_price
            )
            if self.event_bus:
                self.event_bus.emit_sync("exec.entry_filled", {
                    "symbol": state.leg.symbol,
                    "fill_price": state.entry_fill_price,
                    "quantity": state.filled_quantity,
                })
            return

        if status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
            state.cancelled = True
            return

        cutoff = state.leg.max_entry_wait
        if now.timetz().replace(tzinfo=None) >= cutoff:
            logger.info("%s did not fill by %s; cancelling", state.leg.symbol, cutoff)
            self.orders.cancel(state.entry_order_id)
            state.cancelled = True

    # ----- Open position handling -------------------------------------------------

    def _manage_open_leg(self, state: LegState, now: datetime) -> None:
        if self._intelligence is not None:
            self._manage_open_leg_smart(state, now)
        else:
            self._manage_open_leg_classic(state, now)

    def _manage_open_leg_classic(self, state: LegState, now: datetime) -> None:
        """Original exit logic via ExitManager (no intelligence)."""
        from tradingbot.executor.exit_manager import ExitDecision as ClassicDecision

        price = self.broker.get_ltp(state.leg.symbol)
        decision = self.exits.decide(state, price, now)

        if decision is ClassicDecision.HOLD:
            return

        if decision is ClassicDecision.BOOK_TARGET_1:
            half = max(1, state.filled_quantity // 2)
            self._close(state, half, price, reason="target_1", now=now)
            state.target_1_booked = True
            state.current_stop = self.exits.trail_stop(state)
            self._replace_stop(state)
            return

        reason = {
            ClassicDecision.BOOK_TARGET_2: "target_2",
            ClassicDecision.STOP_HIT: "stop_hit",
            ClassicDecision.SQUARE_OFF: "square_off",
        }[decision]
        self._close(state, state.filled_quantity, price, reason=reason, now=now)

    def _manage_open_leg_smart(self, state: LegState, now: datetime) -> None:
        """Intelligence-driven exit logic via AdaptiveExitManager."""
        intel = self._intelligence
        symbol = state.leg.symbol

        # Price from tick stream first, REST fallback
        price = intel.aggregator.last_price(symbol)
        if price is None:
            price = self.broker.get_ltp(symbol)

        symbol_state = intel.scorer.get_state(symbol)
        if symbol_state is None:
            # No candle data — fall back to classic exit rules
            self._manage_open_leg_classic(state, now)
            return

        candles_5m = intel.aggregator.get_candles(symbol, "5min")
        candles_1m = intel.aggregator.get_candles(symbol, "1min")

        decision = intel.adaptive_exit.decide(
            state, symbol_state, price, now,
            candles_5m=candles_5m, candles_1m=candles_1m,
        )

        if decision is ExitDecision.HOLD:
            return

        if decision is ExitDecision.BOOK_TARGET_1:
            half = max(1, state.filled_quantity // 2)
            self._close(state, half, price, reason="target_1", now=now)
            state.target_1_booked = True
            # Use adaptive trail instead of old breakeven trail
            trail = intel.adaptive_exit.compute_trail_price(
                state, symbol_state, candles_5m or [], candles_1m or [],
            )
            if trail is not None:
                state.current_stop = trail
            else:
                state.current_stop = state.entry_fill_price  # breakeven floor
            self._replace_stop(state)
            return

        if decision is ExitDecision.TRAIL_STOP:
            new_stop = intel.adaptive_exit.compute_trail_price(
                state, symbol_state, candles_5m or [], candles_1m or [],
            )
            if new_stop is not None and new_stop != state.current_stop:
                state.current_stop = new_stop
                self._replace_stop(state)
            return

        reason_map = {
            ExitDecision.BOOK_TARGET_2: "target_2",
            ExitDecision.STOP_HIT: "stop_hit",
            ExitDecision.SQUARE_OFF: "square_off",
            ExitDecision.MOMENTUM_EXIT: "momentum_exit",
            ExitDecision.PATTERN_EXIT: "pattern_exit",
        }
        reason = reason_map.get(decision, decision.value)
        self._close(state, state.filled_quantity, price, reason=reason, now=now)

    def _replace_stop(self, state: LegState) -> None:
        if state.stop_order_id is not None:
            self.orders.cancel(state.stop_order_id)
        state.stop_order_id = self.orders.submit_stop(
            state.leg, state.filled_quantity, trigger_price=state.current_stop
        )

    def _close(self, state: LegState, quantity: int, price: float, reason: str, now: datetime) -> None:
        if quantity <= 0:
            return

        if state.stop_order_id is not None:
            self.orders.cancel(state.stop_order_id)
            state.stop_order_id = None

        order_id = self.orders.exit_at_market(state.leg, quantity)
        order = self.broker.get_order(order_id)
        fill_price = float(order.filled_price) if order and order.filled_price else price

        delta = fill_price - state.entry_fill_price
        if state.leg.direction is Direction.SHORT:
            delta = -delta
        pnl = delta * quantity
        state.realised_pnl += pnl
        state.filled_quantity -= quantity

        logger.info(
            "closed %s x%d at %.2f (%s), pnl %.2f",
            state.leg.symbol,
            quantity,
            fill_price,
            reason,
            pnl,
        )

        self.database.record_trade(
            ExecutedTrade(
                trade_date=self.plan.trade_date,
                symbol=state.leg.symbol,
                strategy=state.leg.strategy,
                direction=state.leg.direction,
                quantity=quantity,
                entry_price=state.entry_fill_price,
                exit_price=fill_price,
                stop_loss=state.current_stop,
                target_1=state.leg.target_1,
                target_2=state.leg.target_2,
                entered_at=state.entered_at or now,
                exited_at=now,
                pnl=pnl,
                exit_reason=reason,
                status=TradeStatus.CLOSED,
                mode=self.mode,
                setup_id=state.leg.setup_id,
            )
        )

        if state.filled_quantity > 0 and state.stop_order_id is None:
            self._replace_stop(state)

    # ----- Recovery and shutdown --------------------------------------------------

    def _adopt(self, state: LegState, position) -> None:
        """Take ownership of a position that already existed at startup."""
        state.adopted = True
        state.filled_quantity = position.quantity
        state.entry_fill_price = position.entry_price
        state.entered_at = position.entered_at
        state.current_stop = state.leg.stop_loss
        state.stop_order_id = self.orders.submit_stop(state.leg, state.filled_quantity)
        logger.warning(
            "adopted an existing %s position x%d at %.2f; no new entry will be placed",
            state.leg.symbol,
            state.filled_quantity,
            state.entry_fill_price,
        )

    def _halt_everything(self, now: datetime) -> None:
        for state in self.states:
            if state.entry_order_id is not None and state.filled_quantity == 0 and not state.cancelled:
                self.orders.cancel(state.entry_order_id)
                state.cancelled = True
            if state.filled_quantity > 0:
                price = self.broker.get_ltp(state.leg.symbol)
                self._close(state, state.filled_quantity, price, reason="kill_switch", now=now)
