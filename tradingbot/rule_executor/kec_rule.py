"""KEC intraday short rule, exactly as backtested on 2019-2026 1-minute data.

Short at 09:20 when either condition holds:
  * gap up: today's 09:15 open >= previous close x (1 + gap_min)
  * weak prior close: previous close in the bottom `weak_close_max` of the previous day's range
Stop: entry x (1 + stop_adr_mult x ADR), ADR = mean of (high - low) / close over the last
`adr_days` completed sessions. No target. Cover at exit_time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass(frozen=True)
class KecRuleConfig:
    symbol: str = "KEC"
    gap_min: float = 0.01
    weak_close_max: float = 0.20
    stop_adr_mult: float = 1.0
    adr_days: int = 14
    signal_time: time = time(9, 16)    # 09:15 open is known once the first minute prints
    entry_time: time = time(9, 20)
    entry_deadline: time = time(9, 30)  # no entry after this; the backtest entered at 09:20
    exit_time: time = time(15, 15)      # before Zerodha's MIS auto square-off (~15:20)
    notional: float = 100_000.0


@dataclass(frozen=True)
class DailyBar:
    day: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class RuleSignal:
    trade: bool
    reasons: list[str] = field(default_factory=list)
    gap_pct: float = 0.0
    prev_close_pos: float = 0.0
    adr_pct: float = 0.0
    prev_close: float = 0.0
    today_open: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "trade": self.trade,
            "reasons": list(self.reasons),
            "gap_pct": round(self.gap_pct * 100, 3),
            "prev_close_pos": round(self.prev_close_pos, 3),
            "adr_pct": round(self.adr_pct * 100, 3),
            "prev_close": self.prev_close,
            "today_open": self.today_open,
            "note": self.note,
        }


def evaluate_signal(history: list[DailyBar], today_open: float, cfg: KecRuleConfig) -> RuleSignal:
    """Decide today's trade from completed daily bars (oldest first, today excluded)."""
    if len(history) < cfg.adr_days:
        return RuleSignal(trade=False, note=f"need {cfg.adr_days} completed sessions, have {len(history)}")
    if today_open <= 0:
        return RuleSignal(trade=False, note="today's open not available yet")

    prev = history[-1]
    rng = prev.high - prev.low
    prev_pos = (prev.close - prev.low) / rng if rng > 0 else 0.5
    gap = today_open / prev.close - 1
    window = history[-cfg.adr_days:]
    adr = sum((b.high - b.low) / b.close for b in window) / len(window)

    reasons = []
    if gap >= cfg.gap_min:
        reasons.append(f"gap up {gap * 100:.2f}% >= {cfg.gap_min * 100:.2f}%")
    if prev_pos <= cfg.weak_close_max:
        reasons.append(f"previous close at {prev_pos * 100:.0f}% of its range <= {cfg.weak_close_max * 100:.0f}%")
    if abs(gap) > 0.2:
        return RuleSignal(False, [], gap, prev_pos, adr, prev.close, today_open,
                          note="gap above 20%: likely corporate action, skipped")
    return RuleSignal(bool(reasons), reasons, gap, prev_pos, adr, prev.close, today_open,
                      note="" if reasons else "no condition met")


def stop_price(entry: float, adr_pct: float, cfg: KecRuleConfig, tick: float = 0.05) -> float:
    """Stop above a short entry, rounded up to the exchange tick."""
    raw = entry * (1 + cfg.stop_adr_mult * adr_pct)
    ticks = int(raw / tick + 0.999999)
    return round(ticks * tick, 2)


def quantity_for(entry: float, cfg: KecRuleConfig) -> int:
    return int(cfg.notional // entry) if entry > 0 else 0
