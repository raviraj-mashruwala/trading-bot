"""Read and write the TradePlan JSON artifact that decouples analysis from execution."""

from __future__ import annotations

import json
from pathlib import Path

from tradingbot.core.models import PLAN_SCHEMA_VERSION, TradePlan


class PlanNotFoundError(Exception):
    """Raised when the requested trade plan file does not exist."""


class PlanCorruptError(Exception):
    """Raised when a trade plan file exists but cannot be trusted."""


class PlanStore:
    """Trade plans live as one JSON file per trade date."""

    def __init__(self, plan_dir: Path) -> None:
        self.plan_dir = Path(plan_dir)
        self.plan_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, trade_date: str) -> Path:
        return self.plan_dir / f"{trade_date}.json"

    def save(self, plan: TradePlan) -> Path:
        path = self.path_for(plan.trade_date)
        path.write_text(json.dumps(plan.to_dict(), indent=2))
        return path

    def load(self, trade_date: str) -> TradePlan:
        path = self.path_for(trade_date)
        if not path.exists():
            raise PlanNotFoundError(f"no trade plan for {trade_date} at {path}")

        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise PlanCorruptError(f"{path} could not be parsed as JSON: {exc}") from exc

        version = raw.get("schema_version", PLAN_SCHEMA_VERSION)
        if version > PLAN_SCHEMA_VERSION:
            raise PlanCorruptError(
                f"{path} uses schema version {version}, but this build understands "
                f"version {PLAN_SCHEMA_VERSION}. Regenerate the plan with `tradingbot analyze`."
            )

        try:
            return TradePlan.from_dict(raw)
        except KeyError as exc:
            raise PlanCorruptError(f"{path} is missing required field {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise PlanCorruptError(f"{path} has an invalid field value: {exc}") from exc

    def load_latest(self) -> TradePlan:
        candidates = sorted(self.plan_dir.glob("*.json"))
        if not candidates:
            raise PlanNotFoundError(f"no trade plans found in {self.plan_dir}")
        return self.load(candidates[-1].stem)
