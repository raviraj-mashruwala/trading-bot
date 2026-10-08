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

DEFAULT_PLAN_MAX_AGE_HOURS = 14.0
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
        plan_max_age_hours: float = DEFAULT_PLAN_MAX_AGE_HOURS,
        max_entry_price_drift_pct: float = DEFAULT_MAX_ENTRY_DRIFT_PCT,
        margin_fetcher: Any = None,
    ) -> None:
        self.risk = risk_config
        self.strategy = strategy_config
        self.capital = capital
        self.plan_max_age_hours = plan_max_age_hours
        self.max_entry_price_drift_pct = max_entry_price_drift_pct
        self._margin_fetcher = margin_fetcher

    # ----- Layer 1: analysis time -------------------------------------------------

    def position_size(self, setup: TradeSetup) -> int:
        """Shares to trade, from the risk budget, capped by deployable margin."""
        stop_distance = abs(setup.entry_price - setup.stop_loss)
        if stop_distance < MIN_STOP_DISTANCE:
            raise InvalidSetupError(
                f"{setup.symbol}: stop loss equals entry price "
                f"({setup.stop_loss} vs {setup.entry_price}); cannot size the position"
            )

        risk_budget = self.capital * self.risk.max_risk_per_trade_pct
        by_risk = math.floor(risk_budget / stop_distance)

        deployable = self.capital * self.risk.max_capital_deployed_pct
        margin_per_share = self._get_margin_per_share(setup)
        by_capital = math.floor(deployable / margin_per_share) if margin_per_share > 0 else 0

        return max(0, min(by_risk, by_capital))

    def _get_margin_per_share(self, setup: TradeSetup) -> float:
        """Get margin required per share — uses Kite API if available, else full price."""
        if self._margin_fetcher is not None:
            try:
                margin = self._margin_fetcher(setup)
                if margin > 0:
                    return margin
            except Exception:
                pass
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
        """Rank by confidence, size each survivor, stop at the exposure ceiling."""
        ranked = sorted(setups, key=lambda setup: setup.confidence, reverse=True)
        max_legs = min(self.strategy.max_trades_per_day, self.risk.max_concurrent_positions)
        exposure_ceiling = self.capital * self.risk.max_capital_deployed_pct

        legs: list[TradeLeg] = []
        deployed = 0.0

        for setup in ranked:
            if len(legs) >= max_legs:
                break

            reason = self.vet_setup(setup)
            if reason is not None:
                logger.info("dropping %s: %s", setup.symbol, reason)
                continue

            quantity = self.position_size(setup)
            if quantity <= 0:
                logger.info("dropping %s: position sizes to zero shares", setup.symbol)
                continue

            margin_per_share = self._get_margin_per_share(setup)
            margin_needed = quantity * margin_per_share
            remaining = exposure_ceiling - deployed
            if margin_needed > remaining:
                quantity = math.floor(remaining / margin_per_share) if margin_per_share > 0 else 0
                margin_needed = quantity * margin_per_share
            if quantity <= 0:
                logger.info("dropping %s: no room in exposure ceiling", setup.symbol)
                continue

            legs.append(
                setup.to_leg(
                    quantity=quantity,
                    risk_amount=self.risk_amount_for(setup, quantity),
                    max_entry_wait=max_entry_wait,
                    exit_before=exit_before,
                )
            )
            deployed += margin_needed

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

        age = plan.age_hours(now)
        if age > self.plan_max_age_hours:
            blockers.append(
                f"plan is stale: generated {age:.1f}h ago, limit is {self.plan_max_age_hours:.0f}h"
            )

        required = sum(leg.notional for leg in plan.legs)
        if required > available_capital:
            blockers.append(
                f"insufficient capital: plan needs {required:,.0f} but {available_capital:,.0f} is available"
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
