"""Telegram notification system for trading alerts."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

_LEVEL_EMOJI = {
    "critical": "\U0001f6a8",   # 🚨
    "trade": "✅",          # ✅
    "target": "\U0001f3af",     # 🎯
    "stop": "\U0001f6d1",       # 🛑
    "info": "ℹ️",     # ℹ️
    "scout": "\U0001f52d",      # 🔭
    "session": "▶️",  # ▶️
    "review": "\U0001f4cb",     # 📋
}


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
        self.send_sync(f"\U0001f6a8 <b>CRITICAL</b>\n{message}")

    def notify_entry_filled(self, symbol: str, direction: str, qty: int, price: float) -> None:
        self.send_sync(
            f"✅ <b>ENTERED</b>: {symbol} {direction.upper()} {qty} @ {price:.2f}"
        )

    def notify_target_hit(self, symbol: str, target: int, pnl: float, price: float, qty: int) -> None:
        sign = "+" if pnl >= 0 else ""
        self.send_sync(
            f"\U0001f3af <b>T{target} HIT</b>: {symbol} {sign}₹{pnl:.0f} ({qty} shares @ {price:.2f})"
        )

    def notify_stop_hit(self, symbol: str, pnl: float, price: float) -> None:
        self.send_sync(
            f"\U0001f6d1 <b>STOPPED</b>: {symbol} ₹{pnl:.0f} @ {price:.2f}"
        )

    def notify_kill_switch(self, reason: str, realised_pnl: float) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>KILL SWITCH</b>\n{reason}\nRealised P&L: ₹{realised_pnl:.0f}"
        )

    def notify_session_started(self, mode: str, legs: list[dict]) -> None:
        leg_lines = "\n".join(
            f"  {l.get('symbol', '?')} {l.get('direction', '?').upper()}"
            for l in legs[:6]
        )
        self.send_sync(
            f"▶️ <b>Execution started</b>: {mode.upper()} mode\n"
            f"{len(legs)} legs:\n{leg_lines}"
        )

    def notify_session_done(self, total_pnl: float, trades: int, mode: str) -> None:
        sign = "+" if total_pnl >= 0 else ""
        self.send_sync(
            f"\U0001f4ca <b>Session done</b> ({mode})\n"
            f"P&L: {sign}₹{total_pnl:.0f} | Trades: {trades}"
        )

    def notify_regime_shift(self, old: str, new: str, confidence: float) -> None:
        self.send_sync(
            f"⚠️ <b>Regime shift</b>: {old} → {new} (conf={confidence:.2f})"
        )

    def notify_ticker_reconnect(self, stale_seconds: float) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>Ticker stale {stale_seconds:.0f}s</b> — force reconnecting"
        )

    def notify_margin_warning(self, available: float, net: float) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>Margin critical</b>\n"
            f"Available: ₹{available:,.0f} | Net: ₹{net:,.0f}"
        )

    def notify_entry_vetoed(self, symbol: str, reason: str) -> None:
        self.send_sync(f"⏭️ <b>SKIPPED</b>: {symbol} — {reason}")

    def notify_jev_exit(self, symbol: str, reasoning: str) -> None:
        self.send_sync(f"\U0001f916 <b>JEV EXIT</b>: {symbol} — {reasoning}")

    def notify_market_fallback(self, symbol: str, reason: str) -> None:
        self.send_sync(f"\U0001f504 <b>MARKET ORDER</b>: {symbol} — {reason}")

    def notify_scout_alert(self, symbol: str, direction: str, signal: str,
                           entry: float, target: float, stop: float, reasoning: str) -> None:
        self.send_sync(
            f"\U0001f52d <b>SCOUT</b>: {symbol} {direction.upper()}\n"
            f"Signal: {signal}\n"
            f"Entry: {entry:.2f} | T: {target:.2f} | S: {stop:.2f}\n"
            f"{reasoning}"
        )

    def notify_scout_outcome(self, symbol: str, outcome: str, pnl_pct: float) -> None:
        emoji = "\U0001f3af" if outcome == "target_hit" else "\U0001f6d1" if outcome == "stop_hit" else "⏰"
        self.send_sync(f"\U0001f52d {emoji} SCOUT {symbol}: {outcome} ({pnl_pct:+.2f}%)")

    def notify_nightly_review(self, grade: str, total_pnl: float, summary: str) -> None:
        sign = "+" if total_pnl >= 0 else ""
        self.send_sync(
            f"\U0001f4cb <b>Nightly Review</b>: Grade {grade}\n"
            f"P&L: {sign}₹{total_pnl:.0f}\n"
            f"{summary[:300]}"
        )

    def notify_plan_generated(self, trade_date: str, legs: list[dict]) -> None:
        leg_lines = "\n".join(
            f"  {l.get('symbol', '?')} {l.get('direction', '?').upper()} @ {l.get('entry_price', 0):.2f}"
            for l in legs[:6]
        )
        self.send_sync(
            f"\U0001f4dd <b>Plan for {trade_date}</b>\n{len(legs)} legs:\n{leg_lines}"
        )

    def notify_sync_complete(self, stocks: int, rows: int) -> None:
        self.send_sync(f"\U0001f504 Sync complete: {stocks} stocks, {rows:,} rows")

    def notify_squareoff_failed(self, symbol: str) -> None:
        self.send_sync(
            f"\U0001f6a8 <b>SQUARE-OFF FAILED</b>: {symbol} still open at 15:15!\n"
            f"Manual intervention required."
        )

    def notify_auto_start_failed(self, reason: str) -> None:
        self.send_sync(f"\U0001f6a8 <b>Auto-start failed</b>: {reason}")


def build_notifier() -> TelegramNotifier:
    """Build from environment variables."""
    import os
    return TelegramNotifier(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
    )
