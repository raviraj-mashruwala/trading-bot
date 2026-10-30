"""Three layers of risk control: sizing at analysis time, gates before the open,
and a kill switch during the session."""

from __future__ import annotations

import logging
import math
from datetime import datetime, time

from tradingbot.core.config import RiskConfig, StrategyConfig
from tradingbot.core.models import Direction, TradeLeg, TradePlan, TradeSetup

logger = logging.getLogger(__name__)

# A stop this close to entry is a data error, not a tight stop: sizing against it
# would produce an absurd quantity.
MIN_STOP_DISTANCE = 0.01

DEFAULT_MAX_ENTRY_DRIFT_PCT = 2.0


class InvalidSetupError(Exception):
    """Raised when a setup cannot be sized because its numbers are nonsensical."""


class RiskManager:
    """Owns every number that decides how much money is at risk."""

    def __init__(
        self,
        risk_config: RiskConfig,
        strategy_config: StrategyConfig,
        capital: float,
        max_entry_price_drift_pct: float = DEFAULT_MAX_ENTRY_DRIFT_PCT,
        margin_fetcher: Any = None,
    ) -> None:
        self.risk = risk_config
        self.strategy = strategy_config
        self.capital = capital
        self.max_entry_price_drift_pct = max_entry_price_drift_pct
        self._margin_fetcher = margin_fetcher

    # ----- Layer 1: analysis time -------------------------------------------------

    def position_size(self, setup: TradeSetup) -> int:
        """Shares to trade, from the risk budget. Used as standalone sizing."""
        stop_distance = abs(setup.entry_price - setup.stop_loss)
        if stop_distance < MIN_STOP_DISTANCE:
            raise InvalidSetupError(
                f"{setup.symbol}: stop loss equals entry price "
                f"({setup.stop_loss} vs {setup.entry_price}); cannot size the position"
            )

        risk_budget = self.capital * self.risk.max_risk_per_trade_pct
        by_risk = math.floor(risk_budget / stop_distance)

        return max(0, by_risk)

    def _get_margin_per_share(self, setup: TradeSetup) -> float:
        """Get margin required per share — uses Kite API if available, else full price."""
        if self._margin_fetcher is not None:
            try:
                margin = self._margin_fetcher(setup)
                if margin > 0:
                    return margin
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "Margin fetch failed for %s, using full price", setup.symbol, exc_info=True
                )
        return setup.entry_price

    def risk_amount_for(self, setup: TradeSetup, quantity: int) -> float:
        return abs(setup.entry_price - setup.stop_loss) * quantity

    def vet_setup(self, setup: TradeSetup) -> str | None:
        """Return why this setup is unacceptable, or None when it is fine."""
        if abs(setup.entry_price - setup.stop_loss) < MIN_STOP_DISTANCE:
            return "stop loss equals entry price"

        if setup.direction is Direction.LONG:
            if setup.stop_loss >= setup.entry_price:
                return "stop loss on the wrong side of entry"
            if setup.target_1 <= setup.entry_price:
                return "target on the wrong side of entry"
        else:
            if setup.stop_loss <= setup.entry_price:
                return "stop loss on the wrong side of entry"
            if setup.target_1 >= setup.entry_price:
                return "target on the wrong side of entry"

        if setup.confidence < self.strategy.min_confidence:
            return "confidence below minimum"
        if setup.reward_risk < self.strategy.min_reward_risk:
            return "reward:risk below minimum"
        return None

    def select_legs(
        self,
        setups: list[TradeSetup],
        max_entry_wait: time,
        exit_before: time,
    ) -> list[TradeLeg]:
        """Size positions weighted by confidence, using 95% of available margin."""
        max_legs = min(self.strategy.max_trades_per_day, self.risk.max_concurrent_positions)
        total_margin = self.capital * 0.95

        eligible = []
        for setup in setups:
            reason = self.vet_setup(setup)
            if reason is not None:
                logger.info("dropping %s: %s", setup.symbol, reason)
                continue
            eligible.append(setup)

        eligible = sorted(eligible, key=lambda s: s.confidence, reverse=True)[:max_legs]

        if not eligible:
            return []

        total_confidence = sum(s.confidence for s in eligible)
        if total_confidence <= 0:
            total_confidence = len(eligible)

        legs: list[TradeLeg] = []
        for setup in eligible:
            weight = setup.confidence / total_confidence
            allocated_margin = total_margin * weight

            stop_distance = abs(setup.entry_price - setup.stop_loss)
            risk_budget = self.capital * self.risk.max_risk_per_trade_pct
            by_risk = math.floor(risk_budget / stop_distance) if stop_distance > 0.01 else 0

            margin_per_share = self._get_margin_per_share(setup)
            by_margin = math.floor(allocated_margin / margin_per_share) if margin_per_share > 0 else 0

            quantity = max(0, min(by_risk, by_margin))
            if quantity <= 0:
                logger.info("dropping %s: position sizes to zero shares", setup.symbol)
                continue

            logger.info(
                "%s: weight=%.0f%% allocated=%.0f margin/share=%.0f qty=%d",
                setup.symbol, weight * 100, allocated_margin, margin_per_share, quantity,
            )

            legs.append(
                setup.to_leg(
                    quantity=quantity,
                    risk_amount=self.risk_amount_for(setup, quantity),
                    max_entry_wait=max_entry_wait,
                    exit_before=exit_before,
                )
            )

        return legs

    # ----- Layer 2: before the open -----------------------------------------------

    def vet_plan_for_execution(
        self,
        plan: TradePlan,
        now: datetime,
        available_capital: float,
    ) -> list[str]:
        """Return every reason this plan must not be executed. Empty means go."""
        blockers: list[str] = []

        # A plan is valid for its own trade date however long ago it was generated.
        today = now.date().isoformat()
        if plan.trade_date != today:
            blockers.append(f"plan is for {plan.trade_date}, not today ({today})")

        required_margin = 0.0
        for leg in plan.legs:
            setup = TradeSetup(
                symbol=leg.symbol, strategy=leg.strategy,
                direction=leg.direction, entry_price=leg.entry_price,
                entry_type=leg.entry_type, stop_loss=leg.stop_loss,
                target_1=leg.target_1, target_2=leg.target_2,
                entry_window_start=leg.entry_window_start,
                entry_window_end=leg.entry_window_end,
                confidence=leg.confidence, reasoning="",
            )
            required_margin += self._get_margin_per_share(setup) * leg.quantity
        if required_margin > available_capital:
            blockers.append(
                f"insufficient capital: margin needs {required_margin:,.0f} but {available_capital:,.0f} is available"
            )

        if len(plan.legs) > self.risk.max_concurrent_positions:
            blockers.append(
                f"plan has {len(plan.legs)} legs, above the {self.risk.max_concurrent_positions} position limit"
            )

        return blockers

    def vet_leg_at_open(self, leg: TradeLeg, current_price: float) -> str | None:
        """Reject a leg whose market price has run away from the planned entry."""
        if leg.entry_price <= 0:
            return "planned entry price is not positive"

        drift_pct = abs(current_price - leg.entry_price) / leg.entry_price * 100.0
        if drift_pct > self.max_entry_price_drift_pct:
            return (
                f"price drifted {drift_pct:.2f}% from the planned entry "
                f"({leg.entry_price:.2f} -> {current_price:.2f})"
            )
        return None

    # ----- Layer 3: during the session --------------------------------------------

    def daily_loss_breached(self, realised_pnl: float) -> bool:
        """True once the day's realised loss reaches the configured cap."""
        limit = self.capital * self.risk.max_daily_loss_pct
        return realised_pnl <= -limit
