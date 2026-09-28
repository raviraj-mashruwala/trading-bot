"""Cross-run daily plan builder with confidence x consistency ranking."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore


class DailyPlanBuilder:
    """Aggregate setups across multiple runs and rank by quality signal."""

    def __init__(self, run_store: RunStore, setup_store: SetupStore):
        self._runs = run_store
        self._setups = setup_store

    def build(self, trade_date: date) -> dict[str, Any]:
        runs = self._runs.list_for_date(trade_date)

        # Mark stale setups based on latest run's regime
        if runs:
            latest_regime = runs[-1].get("market_regime", "range_bound")
            self._setups.mark_stale(
                latest_regime,
                datetime.now(tz=ZoneInfo("Asia/Kolkata")),
            )

        active = self._setups.get_active(trade_date)
        all_setups_today = self._setups.get_all_for_date(trade_date)

        by_symbol: dict[str, list[dict]] = defaultdict(list)
        for s in all_setups_today:
            by_symbol[s["symbol"]].append(s)

        ranked: list[dict[str, Any]] = []
        for symbol, setups in by_symbol.items():
            approved = [
                s for s in setups if s["status"] in ("approved", "active")
            ]
            if not approved:
                continue
            best = max(approved, key=lambda s: s["confidence"])
            run_ids = {s["run_id"] for s in approved}
            total_runs = len(runs) if runs else 1
            consistency = len(run_ids) / total_runs

            directions = {s["direction"] for s in approved}
            recommendation = "execute"
            if len(directions) > 1:
                recommendation = "conflicting"
            elif consistency < 0.5:
                recommendation = "watch"

            ranked.append({
                "rank": 0,
                "symbol": symbol,
                "direction": best["direction"],
                "confidence": best["confidence"],
                "consistency": consistency,
                "best_setup": best,
                "run_count": len(run_ids),
                "recommendation": recommendation,
            })

        ranked.sort(
            key=lambda s: s["confidence"] * (1 + s["consistency"]), reverse=True
        )
        for i, s in enumerate(ranked):
            s["rank"] = i + 1

        return {
            "date": str(trade_date),
            "runs": runs,
            "total_runs": len(runs),
            "active_setups": active,
            "ranked_suggestions": ranked,
        }
