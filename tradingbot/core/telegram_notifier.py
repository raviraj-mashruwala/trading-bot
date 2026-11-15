"""Telegram notification system for trading alerts."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def _pnl_str(pnl: float) -> str:
    """Format P&L with sign and emoji."""
    emoji = "\U0001f7e2" if pnl >= 0 else "\U0001f534"
    sign = "+" if pnl >= 0 else ""
    return f"{emoji} {sign}₹{pnl:,.0f}"


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


class TelegramNotifier:
    """Sends trading alerts via Telegram Bot API.

    Configure via environment variables:
        TELEGRAM_BOT_TOKEN — from @BotFather
        TELEGRAM_CHAT_ID — your personal chat ID
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)
        if not self._enabled:
            log.warning("Telegram notifier disabled — missing token or chat_id")

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def send(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self._enabled:
            return False
        try:
            import httpx
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                })
                if resp.status_code != 200:
                    log.warning("Telegram send failed: %s %s", resp.status_code, resp.text[:200])
                    return False
                return True
        except Exception as exc:
            log.warning("Telegram send error: %s", type(exc).__name__)
            return False

    def send_sync(self, text: str) -> bool:
        if not self._enabled:
            return False
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.send(text))
            return True
        except RuntimeError:
            return asyncio.run(self.send(text))

    # ----- Formatted alert methods -------------------------------------------

    def notify_critical(self, message: str) -> None:
        self.send_sync(
            f"{_sep()}\n"
            f"\U0001f6a8 <b>CRITICAL ALERT</b>\n"
            f"{_sep()}\n\n"
            f"{message}"
        )

    def notify_entry_filled(self, symbol: str, direction: str, qty: int, price: float) -> None:
        d_emoji = "📉" if direction.lower() == "short" else "📈"
        self.send_sync(
            f"{_sep()}\n"
            f"✅ <b>ENTRY FILLED</b>\n"
            f"{_sep()}\n\n"
            f"{d_emoji} <b>{symbol}</b>  •  {direction.upper()}\n\n"
            f"<code>"
            f"Entry    ₹{price:,.2f}\n"
            f"Qty      {qty} shares"
            f"</code>"
        )

    def notify_target_hit(self, symbol: str, target: int, pnl: float, price: float, qty: int) -> None:
        self.send_sync(
            f"{_sep()}\n"
            f"\U0001f3af <b>TARGET {target} HIT</b>\n"
            f"{_sep()}\n\n"
            f"<b>{symbol}</b>  •  {qty} shares @ ₹{price:,.2f}\n\n"
            f"P&amp;L  {_pnl_str(pnl)}"
        )

    def notify_stop_hit(self, symbol: str, pnl: float, price: float) -> None:
        self.send_sync(
            f"{_sep()}\n"
            f"\U0001f6d1 <b>STOP LOSS HIT</b>\n"
            f"{_sep()}\n\n"
            f"<b>{symbol}</b>  •  Exit @ ₹{price:,.2f}\n\n"
            f"P&amp;L  {_pnl_str(pnl)}"
        )

    def notify_kill_switch(self, reason: str, realised_pnl: float) -> None:
        self.send_sync(
            f"{_sep()}\n"
            f"\U0001f6a8 <b>KILL SWITCH ACTIVATED</b>\n"
            f"{_sep()}\n\n"
            f"{reason}\n\n"
            f"<code>Realised P&amp;L  ₹{realised_pnl:,.0f}</code>"
        )

    def notify_session_started(self, mode: str, legs: list[dict]) -> None:
        leg_lines = "\n".join(
            f"  {'📉' if l.get('direction', '?').lower() == 'short' else '📈'} "
            f"{l.get('symbol', '?')}  •  {l.get('direction', '?').upper()}"
            for l in legs[:6]
        )
        self.send_sync(
            f"▶️ <b>EXECUTION STARTED</b>\n\n"
            f"<code>Mode   {mode.upper()}\n"
            f"Legs   {len(legs)}</code>\n\n"
            f"{leg_lines}"
        )

    def notify_session_done(self, total_pnl: float, trades: int, mode: str) -> None:
        self.send_sync(
            f"{_sep()}\n"
            f"📊 <b>SESSION COMPLETE</b>\n"
            f"{_sep()}\n\n"
            f"<code>"
            f"Mode     {mode.upper()}\n"
            f"Trades   {trades}\n"
            f"P&amp;L      {'+'  if total_pnl >= 0 else ''}₹{total_pnl:,.0f}"
            f"</code>"
        )

    def notify_regime_shift(self, old: str, new: str, confidence: float) -> None:
        self.send_sync(
            f"⚠️ <b>REGIME SHIFT</b>\n\n"
            f"<code>"
            f"{old}  →  {new}\n"
            f"Confidence  {confidence:.0%}"
            f"</code>"
        )

    def notify_ticker_reconnect(self, stale_seconds: float) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>TICKER STALE</b>\n\n"
            f"<code>Stale for {stale_seconds:.0f}s — force reconnecting</code>"
        )

    def notify_margin_warning(self, available: float, net: float) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>MARGIN WARNING</b>\n\n"
            f"<code>"
            f"Available  ₹{available:,.0f}\n"
            f"Net        ₹{net:,.0f}"
            f"</code>"
        )

    def notify_entry_vetoed(self, symbol: str, reason: str) -> None:
        self.send_sync(
            f"⏭️ <b>{symbol}</b> — Skipped\n"
            f"<i>{reason}</i>"
        )

    def notify_jev_exit(self, symbol: str, reasoning: str) -> None:
        self.send_sync(
            f"\U0001f916 <b>AI EXIT — {symbol}</b>\n\n"
            f"<i>{reasoning}</i>"
        )

    def notify_market_fallback(self, symbol: str, reason: str) -> None:
        self.send_sync(
            f"\U0001f504 <b>MARKET ORDER — {symbol}</b>\n\n"
            f"<i>{reason}</i>"
        )

    def notify_scout_alert(self, symbol: str, direction: str, signal: str,
                           entry: float, target: float, stop: float, reasoning: str) -> None:
        d_emoji = "📉" if direction.lower() == "short" else "📈"
        self.send_sync(
            f"\U0001f52d <b>SCOUT SIGNAL</b>\n\n"
            f"{d_emoji} <b>{symbol}</b>  •  {direction.upper()}\n"
            f"<i>{signal.replace('_', ' ')}</i>\n\n"
            f"<code>"
            f"Entry   ₹{entry:,.2f}\n"
            f"Target  ₹{target:,.2f}\n"
            f"Stop    ₹{stop:,.2f}"
            f"</code>\n\n"
            f"<i>{reasoning}</i>"
        )

    def notify_scout_outcome(self, symbol: str, outcome: str, pnl_pct: float) -> None:
        emoji = "\U0001f3af" if outcome == "target_hit" else "\U0001f6d1" if outcome == "stop_hit" else "⏰"
        result = outcome.replace("_", " ").title()
        self.send_sync(
            f"\U0001f52d {emoji} <b>{symbol}</b>  •  {result}\n"
            f"<code>P&amp;L  {pnl_pct:+.2f}%</code>"
        )

    def notify_nightly_review(self, grade: str, total_pnl: float, summary: str) -> None:
        grade_emoji = {"A": "🏆", "B": "\U0001f7e2", "C": "🟡", "D": "\U0001f534", "F": "⛔"}.get(grade, "📋")
        self.send_sync(
            f"{_sep()}\n"
            f"📋 <b>NIGHTLY REVIEW</b>\n"
            f"{_sep()}\n\n"
            f"<code>"
            f"Grade   {grade_emoji} {grade}\n"
            f"P&amp;L     {'+'  if total_pnl >= 0 else ''}₹{total_pnl:,.0f}"
            f"</code>\n\n"
            f"<i>{summary[:300]}</i>"
        )

    def notify_plan_generated(self, trade_date: str, legs: list[dict]) -> None:
        leg_lines = "\n".join(
            f"  {'📉' if l.get('direction', '?').lower() == 'short' else '📈'} "
            f"{l.get('symbol', '?')}  •  {l.get('direction', '?').upper()}"
            f"  @ ₹{l.get('entry_price', 0):,.2f}"
            for l in legs[:6]
        )
        self.send_sync(
            f"\U0001f4dd <b>NEW PLAN — {trade_date}</b>\n\n"
            f"<code>Legs  {len(legs)}</code>\n\n"
            f"{leg_lines}"
        )

    def notify_sync_complete(self, stocks: int, rows: int) -> None:
        self.send_sync(
            f"\U0001f504 <b>DATA SYNC COMPLETE</b>\n\n"
            f"<code>"
            f"Stocks  {stocks}\n"
            f"Rows    {rows:,}"
            f"</code>"
        )

    def notify_squareoff_failed(self, symbol: str) -> None:
        self.send_sync(
            f"{_sep()}\n"
            f"\U0001f6a8 <b>SQUARE-OFF FAILED</b>\n"
            f"{_sep()}\n\n"
            f"<b>{symbol}</b> still open at 15:15\n\n"
            f"⚠️ <i>Manual intervention required</i>"
        )

    def notify_auto_start_failed(self, reason: str) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>AUTO-START FAILED</b>\n\n"
            f"<i>{reason}</i>"
        )

    def notify_sync_failed(self, reason: str) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>SYNC FAILED</b>\n\n"
            f"<i>{reason}</i>"
        )

    def notify_analysis_failed(self, reason: str) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>ANALYSIS FAILED</b>\n\n"
            f"<i>{reason}</i>"
        )

    def notify_analysis_progress(self, phase: str, detail: str) -> None:
        self.send_sync(
            f"\U0001f50d <b>ANALYSIS</b>  •  {phase}\n\n"
            f"<code>{detail}</code>"
        )

    def notify_analysis_complete(
        self, trade_date: str, scanned: int, tier1: int,
        shortlisted: int, proposed: int, approved: int,
        duration: float, regime: str,
    ) -> None:
        self.send_sync(
            f"✅ <b>ANALYSIS COMPLETE</b>\n\n"
            f"<code>"
            f"Date        {trade_date}\n"
            f"Regime      {regime}\n"
            f"Scanned     {scanned}\n"
            f"Tier 1      {tier1}\n"
            f"Shortlisted {shortlisted}\n"
            f"Proposed    {proposed}\n"
            f"Approved    {approved}\n"
            f"Duration    {duration:.0f}s"
            f"</code>"
        )


    def notify_catchup_summary(self, decisions: dict) -> None:
        lines = ["\U0001f504 <b>LATE-START CATCH-UP</b>\n"]
        for sym, d in decisions.items():
            emoji = "✅" if d.action == "proceed" else "❌"
            lines.append(f"{emoji} <b>{sym}</b>: {d.reason}")
        self.send_sync("\n".join(lines))


def build_notifier() -> TelegramNotifier:
    """Build from environment variables."""
    import os
    return TelegramNotifier(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
    )
