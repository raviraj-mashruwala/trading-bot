"""Read-only store that joins trades + setups into scorecards and stats."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from tradingbot.core.db_factory import DatabaseKind, create_connection
from tradingbot.core.models import (
    PerformanceStats,
    StrategyStats,
    TradeScorecard,
)

_SCORECARD_SQL = """
SELECT t.id AS trade_id, t.setup_id, t.symbol, t.strategy, t.direction,
       t.trade_date, t.entry_price AS actual_entry, t.exit_price AS actual_exit,
       t.pnl, t.exit_reason, t.quantity,
       s.entry_price AS predicted_entry, s.stop_loss AS predicted_stop,
       s.target_1 AS predicted_target_1, s.target_2 AS predicted_target_2,
       s.confidence, s.confluence_count, s.regime_at_generation,
       s.thesis, s.invalidation_condition, s.bear_case
FROM trades t
JOIN analysis.setups s ON t.setup_id = s.id
"""

_SCORECARD_SQL_LOCAL = """
SELECT t.id AS trade_id, t.setup_id, t.symbol, t.strategy, t.direction,
       t.trade_date, t.entry_price AS actual_entry, t.exit_price AS actual_exit,
       t.pnl, t.exit_reason, t.quantity,
       s.entry_price AS predicted_entry, s.stop_loss AS predicted_stop,
       s.target_1 AS predicted_target_1, s.target_2 AS predicted_target_2,
       s.confidence, s.confluence_count, s.regime_at_generation,
       s.thesis, s.invalidation_condition, s.bear_case
FROM trades t
JOIN setups s ON t.setup_id = s.id
"""


class TradeReviewStore:
    """Join trades and setups to produce scorecards and aggregated stats.

    The trades table lives in tradingbot.db and the setups table lives in
    analysis.db. We ATTACH analysis.db so the JOIN can cross databases.
    """

    def __init__(self, db_path: Path):
        import sqlite3 as _sqlite3

        trading_path = Path(db_path)
        analysis_path = trading_path.parent / "analysis.db"

        conn = _sqlite3.connect(str(trading_path))
        conn.row_factory = _sqlite3.Row
        if analysis_path.exists():
            conn.execute(f"ATTACH DATABASE ? AS analysis", (str(analysis_path),))
        self._conn = conn
        self._has_analysis = analysis_path.exists()

    @property
    def _sql(self) -> str:
        return _SCORECARD_SQL if self._has_analysis else _SCORECARD_SQL_LOCAL

    def get_scorecard(self, trade_id: int) -> TradeScorecard | None:
        row = self._conn.execute(
            self._sql + " WHERE t.id = ?", (trade_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_scorecard(row)

    def get_scorecards_for_date(self, trade_date: str) -> list[TradeScorecard]:
        rows = self._conn.execute(
            self._sql + " WHERE t.trade_date = ? AND t.setup_id IS NOT NULL ORDER BY t.id",
            (trade_date,),
        ).fetchall()
        return [self._row_to_scorecard(r) for r in rows]

    def get_performance_stats(self, lookback_days: int = 30) -> PerformanceStats:
        cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
        try:
            rows = self._conn.execute(
                self._sql + " WHERE t.trade_date >= ? AND t.setup_id IS NOT NULL",
                (cutoff,),
            ).fetchall()
        except Exception:
            rows = []

        scorecards = [self._row_to_scorecard(r) for r in rows]
        return self._aggregate(scorecards, lookback_days)

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_scorecard(row) -> TradeScorecard:
        return TradeScorecard(
            trade_id=row["trade_id"],
            setup_id=row["setup_id"],
            symbol=row["symbol"],
            strategy=row["strategy"],
            direction=row["direction"],
            trade_date=row["trade_date"],
            predicted_entry=float(row["predicted_entry"]),
            predicted_stop=float(row["predicted_stop"]),
            predicted_target_1=float(row["predicted_target_1"]),
            predicted_target_2=float(row["predicted_target_2"]) if row["predicted_target_2"] else None,
            confidence=float(row["confidence"]),
            confluence_count=int(row["confluence_count"] or 0),
            regime_at_generation=row["regime_at_generation"] or "",
            thesis=row["thesis"] or "",
            invalidation_condition=row["invalidation_condition"] or "",
            bear_case=row["bear_case"] or "",
            actual_entry=float(row["actual_entry"]),
            actual_exit=float(row["actual_exit"]),
            pnl=float(row["pnl"]),
            exit_reason=row["exit_reason"],
            quantity=int(row["quantity"]),
        )

    @staticmethod
    def _aggregate(scorecards: list[TradeScorecard], period_days: int) -> PerformanceStats:
        total = len(scorecards)
        if total == 0:
            return PerformanceStats(
                period_days=period_days, total_trades=0, win_rate=0.0,
                avg_r_multiple=0.0, total_pnl=0.0,
                by_strategy={}, by_regime={}, by_strategy_regime={},
                confluence_buckets={"low": 0.0, "mid": 0.0, "high": 0.0},
                confidence_calibration={},
            )

        wins = sum(1 for sc in scorecards if sc.pnl > 0)
        total_pnl = sum(sc.pnl for sc in scorecards)
        avg_r = sum(sc.r_multiple for sc in scorecards) / total

        def _bucket_stats(items: list[TradeScorecard]) -> StrategyStats:
            n = len(items)
            if n == 0:
                return StrategyStats(trades=0, win_rate=0.0, avg_r=0.0, total_pnl=0.0)
            w = sum(1 for s in items if s.pnl > 0)
            return StrategyStats(
                trades=n, win_rate=w / n,
                avg_r=sum(s.r_multiple for s in items) / n,
                total_pnl=sum(s.pnl for s in items),
            )

        by_strat: dict[str, list[TradeScorecard]] = {}
        for sc in scorecards:
            by_strat.setdefault(sc.strategy, []).append(sc)

        by_reg: dict[str, list[TradeScorecard]] = {}
        for sc in scorecards:
            by_reg.setdefault(sc.regime_at_generation or "unknown", []).append(sc)

        by_sr: dict[str, list[TradeScorecard]] = {}
        for sc in scorecards:
            key = f"{sc.strategy}|{sc.regime_at_generation or 'unknown'}"
            by_sr.setdefault(key, []).append(sc)

        conf_low = [sc for sc in scorecards if sc.confluence_count <= 2]
        conf_mid = [sc for sc in scorecards if sc.confluence_count == 3]
        conf_high = [sc for sc in scorecards if sc.confluence_count >= 4]

        def _win_rate(items: list) -> float:
            if not items:
                return 0.0
            return sum(1 for s in items if s.pnl > 0) / len(items)

        cal: dict[str, list[TradeScorecard]] = {}
        for sc in scorecards:
            lower = int(sc.confidence * 10) / 10
            upper = min(1.0, lower + 0.1)
            if lower >= 1.0:
                lower, upper = 0.9, 1.0
            bucket = f"{lower:.1f}-{upper:.1f}"
            cal.setdefault(bucket, []).append(sc)

        return PerformanceStats(
            period_days=period_days,
            total_trades=total,
            win_rate=wins / total,
            avg_r_multiple=avg_r,
            total_pnl=total_pnl,
            by_strategy={k: _bucket_stats(v) for k, v in by_strat.items()},
            by_regime={k: _bucket_stats(v) for k, v in by_reg.items()},
            by_strategy_regime={k: _bucket_stats(v) for k, v in by_sr.items()},
            confluence_buckets={
                "low": _win_rate(conf_low),
                "mid": _win_rate(conf_mid),
                "high": _win_rate(conf_high),
            },
            confidence_calibration={k: _win_rate(v) for k, v in sorted(cal.items())},
        )
