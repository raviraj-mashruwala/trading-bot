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
    stop_adr_mult: float = 0.65        # set from the page; backtested 0.25-1.0, all similar net of costs
    adr_days: int = 14
    signal_time: time = time(9, 16)    # 09:15 open is known once the first minute prints
    entry_time: time = time(9, 20)
    entry_deadline: time = time(9, 30)  # no entry after this; the backtest entered at 09:20
    exit_time: time = time(15, 15)      # before Zerodha's MIS auto square-off (~15:20)
    balance_buffer: float = 2_500.0     # Kite balance left unused; quantity uses the rest as MIS margin


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


@dataclass(frozen=True)
class Sizing:
    """Position size from the Kite balance and the broker's intraday margin per share."""

    available: float
    margin_per_share: float
    quantity: int

    def to_dict(self, price: float, stop_pct: float | None = None) -> dict:
        out = {
            "available": round(self.available, 2),
            "margin_per_share": round(self.margin_per_share, 2),
            "quantity": self.quantity,
            "position_value": round(self.quantity * price, 2),
            "margin_used": round(self.quantity * self.margin_per_share, 2),
        }
        if stop_pct is not None:
            loss = self.quantity * price * stop_pct
            out["stop_pct"] = round(stop_pct * 100, 3)
            out["loss_at_stop"] = round(loss, 2)
            out["loss_at_stop_pct_of_balance"] = round(loss / self.available * 100, 2) if self.available > 0 else None
        return out


def margin_quantity(available: float, margin_per_share: float, buffer: float) -> int:
    """Shares whose intraday margin fits in (available - buffer)."""
    usable = available - buffer
    if usable <= 0 or margin_per_share <= 0:
        return 0
    return int(usable // margin_per_share)
