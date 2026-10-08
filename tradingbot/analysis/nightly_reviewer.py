"""One Claude call per day: review all trades, extract lessons, suggest improvements."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime

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

Review the provided trades and execution decisions. Be specific and actionable.
Reference actual numbers from the data. Don't give generic advice."""

REVIEW_SCHEMA = {
    "type": "object",
    "required": ["summary", "lessons", "improvements", "grade"],
    "properties": {
        "summary": {
            "type": "string",
            "description": "2-3 sentence summary of the day. Include total P&L, win rate, and the key story of the day.",
        },
        "lessons": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 specific lessons from today's trades. Reference actual symbols, prices, and decisions. Example: 'GLAND short entry at 3154 was well-timed — momentum was -45 and VWAP rejection confirmed the move.'",
        },
        "improvements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 concrete improvements for the bot or the trader. Be specific about what parameter to change or what behavior to add. Example: 'EntryGuard should WAIT when 5m momentum is between -30 and -60 for shorts — today this gray zone caused a late entry on NELCAST.'",
        },
        "grade": {
            "type": "string",
            "enum": ["A", "B", "C", "D", "F"],
            "description": "A=excellent execution and P&L, B=good with minor issues, C=mixed results, D=poor execution, F=significant losses or failures",
        },
    },
}


def _format_trade(trade) -> str:
    d = asdict(trade)
    pnl_sign = "+" if d["pnl"] >= 0 else ""
    r_mult = d["pnl"] / abs(d["entry_price"] - d["stop_loss"]) / d["quantity"] if d["quantity"] > 0 else 0
    return (
        f"  {d['symbol']} {d['direction'].upper()} x{d['quantity']}: "
        f"entry={d['entry_price']:.2f} exit={d['exit_price']:.2f} "
        f"SL={d['stop_loss']:.2f} T1={d['target_1']:.2f} "
        f"P&L={pnl_sign}{d['pnl']:.2f} ({pnl_sign}{r_mult:.1f}R) "
        f"exit_reason={d['exit_reason']} strategy={d['strategy'].value}"
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


def _build_prompt(trade_date: str, trades, decisions: list[dict]) -> str:
    if not trades:
        return f"No trades were executed on {trade_date}. Review the decisions to understand why."

    total_pnl = sum(t.pnl for t in trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl <= 0)

    lines = [
        f"## Trading Day: {trade_date}",
        f"Total P&L: ₹{total_pnl:+,.2f} | Trades: {len(trades)} | Wins: {wins} | Losses: {losses}",
        "",
        "## Trades",
    ]
    for t in trades:
        lines.append(_format_trade(t))

    if decisions:
        entry_decisions = [d for d in decisions if d["decision_type"].startswith("ENTRY_")]
        exit_decisions = [d for d in decisions if not d["decision_type"].startswith("ENTRY_")]

        if entry_decisions:
            lines.append("")
            lines.append(f"## Entry Decisions ({len(entry_decisions)})")
            for d in entry_decisions:
                lines.append(_format_decision(d))

        if exit_decisions:
            lines.append("")
            lines.append(f"## Exit Decisions ({len(exit_decisions)})")
            for d in exit_decisions:
                lines.append(_format_decision(d))

    return "\n".join(lines)


async def run_nightly_review(
    database: Database,
    llm: LLMProvider,
    trade_date: str | None = None,
) -> dict:
    if trade_date is None:
        trade_date = now_ist().strftime("%Y-%m-%d")

    trades = database.trades_for_date(trade_date)
    decisions = database.get_decisions_for_date(trade_date)

    if not trades and not decisions:
        logger.info("No trades or decisions for %s — skipping review", trade_date)
        return {"trade_date": trade_date, "skipped": True, "reason": "no activity"}

    prompt = _build_prompt(trade_date, trades, decisions)
    logger.info("Running nightly review for %s (%d trades, %d decisions)", trade_date, len(trades), len(decisions))

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
