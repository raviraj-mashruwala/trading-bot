"""One Claude call per day: review all trades, extract lessons, suggest improvements.

Collects all proposed setups (traded or not), their intraday candle data,
execution decisions, and trade outcomes to give a complete picture of the day.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date, datetime

from tradingbot.core.database import Database
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import now_ist

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert intraday equity trader reviewing today's automated trading session on the Indian NSE market.

You have deep knowledge of:
- Price action, momentum, and volume analysis
- VWAP, support/resistance, and candle patterns
- Risk management (position sizing, stop losses, R-multiples)
- Execution quality (entry timing, slippage, drift)
- Behavioral finance (discipline, overtrading, revenge trading)

You are given:
1. All proposed setups for the day (traded and not traded)
2. Intraday candle data (15m, 5m, 1m) for each proposed stock
3. Execution decisions (ENTER/WAIT/VETO and their reasons)
4. Trade outcomes (entry, exit, P&L)

For each stock, study what actually happened during the day using the candle data.
For traded stocks, evaluate: was the entry well-timed? Did we exit too early or hold too long?
For untaken setups, evaluate: would the setup have worked? Did the bot correctly skip it?

Be specific and actionable. Reference actual prices, times, and candle patterns.
Don't give generic advice."""

REVIEW_SCHEMA = {
    "type": "object",
    "required": ["summary", "lessons", "improvements", "grade"],
    "properties": {
        "summary": {
            "type": "string",
            "description": "2-3 sentence summary of the day. Include total P&L, win rate, and the key story.",
        },
        "lessons": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 specific lessons. Reference actual symbols, prices, candle patterns, and timing. For untaken setups, say whether the skip was correct. Example: 'GLAND short entry at 3154 was well-timed — 15m candles show consistent lower highs from 9:15 to 9:25, and the 3122 target hit cleanly at 09:25.'",
        },
        "improvements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 concrete improvements. Be specific about parameters or rules. Example: 'EntryGuard vetoed NELCAST due to drift, but 5m candles show price returned to entry within 10 minutes — consider a 15-minute WAIT instead of immediate VETO for drift between 3-5%.'",
        },
        "grade": {
            "type": "string",
            "enum": ["A", "B", "C", "D", "F"],
            "description": "A=excellent execution, B=good with minor issues, C=mixed, D=poor execution, F=significant losses",
        },
    },
}


def _format_trade(trade) -> str:
    d = asdict(trade)
    pnl_sign = "+" if d["pnl"] >= 0 else ""
    stop_dist = abs(d["entry_price"] - d["stop_loss"])
    r_mult = d["pnl"] / (stop_dist * d["quantity"]) if d["quantity"] > 0 and stop_dist > 0 else 0
    return (
        f"  {d['symbol']} {d['direction'].upper()} x{d['quantity']}: "
        f"entry={d['entry_price']:.2f} exit={d['exit_price']:.2f} "
        f"SL={d['stop_loss']:.2f} T1={d['target_1']:.2f} T2={d['target_2']:.2f} "
        f"P&L={pnl_sign}{d['pnl']:.2f} ({pnl_sign}{r_mult:.1f}R) "
        f"exit_reason={d['exit_reason']} "
        f"entered={d['entered_at']} exited={d['exited_at']}"
    )


def _format_decision(dec: dict) -> str:
    parts = [f"  {dec['timestamp'][:19]} {dec['symbol']} {dec['decision_type']}"]
    if dec.get("reason"):
        parts.append(f": {dec['reason']}")
    if dec.get("escalated"):
        parts.append(" [AI]")
    if dec.get("outcome"):
        parts.append(f" → {dec['outcome']}")
    return "".join(parts)


def _format_setup(s: dict) -> str:
    return (
        f"  {s['symbol']} {s['direction'].upper()} ({s['strategy']}): "
        f"entry={s['entry_price']} SL={s['stop_loss']} T1={s['target_1']} "
        f"confidence={s.get('confidence', '?')} status={s['status']} "
        f"reasoning={s.get('reasoning', '')[:120]}"
    )


def _format_candles(df, interval: str, max_rows: int = 40) -> str:
    if df is None or df.empty:
        return f"  No {interval} data available"
    rows = df.tail(max_rows)
    lines = [f"  {interval} candles ({len(df)} total, showing last {len(rows)}):"]
    lines.append("  time        | open     | high     | low      | close    | volume")
    for _, r in rows.iterrows():
        ts = str(r["timestamp"])[11:16] if len(str(r["timestamp"])) > 11 else str(r["timestamp"])
        lines.append(
            f"  {ts:>5} | {r['open']:>8.2f} | {r['high']:>8.2f} | {r['low']:>8.2f} | {r['close']:>8.2f} | {int(r['volume']):>8}"
        )
    return "\n".join(lines)


def _build_prompt(
    trade_date: str,
    trades,
    decisions: list[dict],
    setups: list[dict],
    candle_data: dict[str, dict[str, object]],
) -> str:
    total_pnl = sum(t.pnl for t in trades) if trades else 0
    wins = sum(1 for t in trades if t.pnl > 0) if trades else 0
    losses = sum(1 for t in trades if t.pnl <= 0) if trades else 0
    traded_symbols = {t.symbol for t in trades}

    lines = [
        f"## Trading Day: {trade_date}",
        f"Total P&L: ₹{total_pnl:+,.2f} | Trades: {len(trades)} | Wins: {wins} | Losses: {losses}",
        f"Proposed setups: {len(setups)} | Traded: {len(traded_symbols)}",
    ]

    if setups:
        lines.append("")
        lines.append("## Proposed Setups")
        for s in setups:
            tag = " [TRADED]" if s["symbol"] in traded_symbols else " [NOT TAKEN]"
            lines.append(_format_setup(s) + tag)

    if trades:
        lines.append("")
        lines.append("## Executed Trades")
        for t in trades:
            lines.append(_format_trade(t))

    if decisions:
        entry_decs = [d for d in decisions if d["decision_type"].startswith("ENTRY_")]
        exit_decs = [d for d in decisions if not d["decision_type"].startswith("ENTRY_")]
        if entry_decs:
            lines.append("")
            lines.append(f"## Entry Decisions ({len(entry_decs)})")
            for d in entry_decs:
                lines.append(_format_decision(d))
        if exit_decs:
            lines.append("")
            lines.append(f"## Exit Decisions ({len(exit_decs)})")
            for d in exit_decs:
                lines.append(_format_decision(d))

    # Candle data per symbol
    all_symbols = sorted({s["symbol"] for s in setups} | traded_symbols)
    if candle_data and all_symbols:
        lines.append("")
        lines.append("## Intraday Candle Data")
        for sym in all_symbols:
            sym_data = candle_data.get(sym, {})
            if not sym_data:
                lines.append(f"\n### {sym} — no candle data")
                continue
            lines.append(f"\n### {sym}")
            for interval in ["15m", "5m", "1m"]:
                df = sym_data.get(interval)
                lines.append(_format_candles(df, interval))

    if not trades and not setups:
        return f"No trades or setups for {trade_date}. Review decisions to understand why."

    return "\n".join(lines)


def _load_candle_data(
    candle_store,
    symbols: list[str],
    trade_date: str,
) -> dict[str, dict]:
    if candle_store is None:
        return {}

    from datetime import date as _date
    td = _date.fromisoformat(trade_date)
    result: dict[str, dict] = {}

    for sym in symbols:
        sym_data = {}
        for interval in ["15m", "5m", "1m"]:
            try:
                df = candle_store.read(sym, interval, from_date=td, to_date=td)
                sym_data[interval] = df if not df.empty else None
            except Exception:
                sym_data[interval] = None
        result[sym] = sym_data

    return result


async def _pre_grade_trades(trades, jev_client) -> dict[str, dict]:
    """Run Jev trade grader on each trade before Claude review."""
    if jev_client is None or not trades:
        return {}

    from tradingbot.analysis.jev_trade_grader import grade_trade
    from dataclasses import asdict

    grades: dict[str, dict] = {}
    for trade in trades:
        try:
            d = asdict(trade)
            stop_dist = abs(d["entry_price"] - d["stop_loss"])
            r_mult = d["pnl"] / (stop_dist * d["quantity"]) if d["quantity"] > 0 and stop_dist > 0 else 0
            scorecard = {
                "predicted_entry": d["entry_price"],
                "predicted_stop": d["stop_loss"],
                "predicted_target_1": d["target_1"],
                "strategy": d.get("strategy", ""),
                "direction": d.get("direction", ""),
                "actual_entry": d["entry_price"],
                "actual_exit": d["exit_price"],
                "pnl": d["pnl"],
                "exit_reason": d["exit_reason"],
                "r_multiple": r_mult,
            }
            grade = await grade_trade(jev_client, scorecard)
            grades[trade.symbol] = grade
            logger.info("Jev pre-grade %s: exec=%.2f plan=%.2f notable=%s",
                        trade.symbol, grade["execution_grade"], grade["plan_quality"], grade["notable"])
        except Exception:
            logger.warning("Jev pre-grade failed for %s", trade.symbol, exc_info=True)
    return grades


def _format_jev_grades(grades: dict[str, dict]) -> str:
    if not grades:
        return ""
    lines = ["\n## Jev Pre-Grades (AI quantitative assessment)"]
    for sym, g in grades.items():
        exec_pct = int(g["execution_grade"] * 100)
        plan_pct = int(g["plan_quality"] * 100)
        notable = " ★ NOTABLE" if g.get("notable") else ""
        lines.append(f"  {sym}: execution={exec_pct}% plan_quality={plan_pct}%{notable}")
    return "\n".join(lines)


async def run_nightly_review(
    database: Database,
    llm: LLMProvider,
    trade_date: str | None = None,
    setup_store=None,
    candle_store=None,
    jev_client=None,
) -> dict:
    if trade_date is None:
        trade_date = now_ist().strftime("%Y-%m-%d")

    trades = database.trades_for_date(trade_date)
    decisions = database.get_decisions_for_date(trade_date)

    setups: list[dict] = []
    if setup_store is not None:
        try:
            setups = setup_store.get_all_for_date(date.fromisoformat(trade_date))
        except Exception:
            logger.warning("Failed to load setups for %s", trade_date, exc_info=True)

    if not trades and not decisions and not setups:
        logger.info("No activity for %s — skipping review", trade_date)
        return {"trade_date": trade_date, "skipped": True, "reason": "no activity"}

    jev_grades = await _pre_grade_trades(trades, jev_client)

    # Collect symbols from both setups and trades
    all_symbols = sorted({s["symbol"] for s in setups} | {t.symbol for t in trades})
    candle_data = _load_candle_data(candle_store, all_symbols, trade_date)

    prompt = _build_prompt(trade_date, trades, decisions, setups, candle_data)
    if jev_grades:
        prompt += _format_jev_grades(jev_grades)
    logger.info(
        "Running nightly review for %s (%d trades, %d decisions, %d setups, %d symbols with candles)",
        trade_date, len(trades), len(decisions), len(setups), len(candle_data),
    )

    result = await llm.analyze(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        tool_name="nightly_review",
        tool_description="Structured review of today's trading session",
        input_schema=REVIEW_SCHEMA,
    )

    usage = result.pop("_usage", None)
    cost = usage.cost_usd() if usage else 0

    total_pnl = sum(t.pnl for t in trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl <= 0)

    review = {
        "trade_date": trade_date,
        "reviewed_at": datetime.now().isoformat(),
        "total_pnl": total_pnl,
        "trades_count": len(trades),
        "wins": wins,
        "losses": losses,
        "summary": result.get("summary", ""),
        "lessons": json.dumps(result.get("lessons", [])),
        "improvements": json.dumps(result.get("improvements", [])),
        "grade": result.get("grade", "C"),
        "raw_response": json.dumps(result),
        "llm_cost_usd": cost,
    }

    database.save_nightly_review(review)
    logger.info("Nightly review saved for %s (grade=%s, cost=$%.4f)", trade_date, review["grade"], cost)

    return review
