"""Read and write the TradePlan JSON artifact that decouples analysis from execution."""

from __future__ import annotations

import json
from pathlib import Path

from tradingbot.core.models import PLAN_SCHEMA_VERSION, TradePlan


class PlanNotFoundError(Exception):
    """Raised when the requested trade plan file does not exist."""


class PlanCorruptError(Exception):
    """Raised when a trade plan file exists but cannot be trusted."""


PLAN_FILENAME_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json"


class PlanStore:
    """Trade plans live as one JSON file per trade date.

    The directory may also hold scratch artifacts from research scripts
    (not managed by this store), so lookups must only match genuine
    trade-date filenames rather than globbing every `*.json`.
    """

    def __init__(self, plan_dir: Path) -> None:
        self.plan_dir = Path(plan_dir)
        self.plan_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, trade_date: str) -> Path:
        return self.plan_dir / f"{trade_date}.json"

    def iter_plan_paths(self):
        return sorted(self.plan_dir.glob(PLAN_FILENAME_GLOB))

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

        if not isinstance(raw, dict):
            raise PlanCorruptError(f"{path} does not contain a JSON object (got {type(raw).__name__})")

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
        candidates = self.iter_plan_paths()
        if not candidates:
            raise PlanNotFoundError(f"no trade plans found in {self.plan_dir}")
        return self.load(candidates[-1].stem)
