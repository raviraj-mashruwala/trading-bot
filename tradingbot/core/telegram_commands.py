"""Telegram command handler — control the trading bot from your phone.

Polls for incoming messages and responds to commands by querying
the same internal state the API server uses.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

POLL_INTERVAL = 2
ALLOWED_COMMANDS = {"/status", "/plan", "/scout", "/stats", "/health", "/stop", "/approve", "/login", "/help", "/start"}


class TelegramCommandHandler:
    """Long-polls Telegram for commands from the authorized chat."""

    def __init__(self, bot_token: str, chat_id: str, app_state: Any) -> None:
        self._token = bot_token
        self._chat_id = str(chat_id)
        self._state = app_state
        self._offset = 0
        self._running = False

    async def start(self) -> None:
        self._running = True
        log.info("Telegram command handler started")
        while self._running:
            try:
                await self._poll()
            except Exception:
                log.debug("Telegram poll error", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False

    async def _poll(self) -> None:
        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params={
                "offset": self._offset,
                "timeout": 20,
                "allowed_updates": '["message"]',
            })
            if resp.status_code != 200:
                return
            data = resp.json()
            for update in data.get("result", []):
                self._offset = update["update_id"] + 1
                await self._handle_update(update)

    async def _handle_update(self, update: dict) -> None:
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()

        if chat_id != self._chat_id:
            return
        if not text.startswith("/"):
            return

        cmd = text.split()[0].split("@")[0].lower()
        args = text.split()[1:] if len(text.split()) > 1 else []

        handler = {
            "/status": self._cmd_status,
            "/plan": self._cmd_plan,
            "/scout": self._cmd_scout,
            "/stats": self._cmd_stats,
            "/health": self._cmd_health,
            "/stop": self._cmd_stop,
            "/approve": self._cmd_approve,
            "/login": self._cmd_login,
            "/token": self._cmd_token,
            "/help": self._cmd_help,
            "/start": self._cmd_help,
        }.get(cmd)

        if handler:
            try:
                reply = await handler(args)
            except Exception as exc:
                reply = f"⚠️ Command failed: {type(exc).__name__}"
        else:
            reply = f"Unknown command: {cmd}\nUse /help for available commands."

        await self._reply(reply)

    async def _reply(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })

    # ----- Command handlers --------------------------------------------------

    async def _cmd_help(self, args: list[str]) -> str:
        return (
            "\U0001f916 <b>Trading Bot Commands</b>\n\n"
            "/status — Positions, P&L, margin\n"
            "/plan — Today's trading plan\n"
            "/scout — Recent scout signals + stats\n"
            "/stats — Trading stats & strategy breakdown\n"
            "/health — System health check\n"
            "/login — Kite login URL\n"
            "/token &lt;code&gt; — Complete Kite login with request_token\n"
            "/stop — Emergency kill switch\n"
            "/approve — Approve pending plan\n"
            "/help — This message"
        )

    async def _cmd_status(self, args: list[str]) -> str:
        s = self._state
        lines = [f"\U0001f4ca <b>Status: {s.executor_status.upper()}</b>"]

        if s.executor_mode:
            lines[0] += f" ({s.executor_mode})"

        # Capital (live from Kite only)
        if s.kite_auth and s.kite_auth.is_authenticated():
            try:
                cap = s.capital
                lines.append(f"Margin: ₹{cap:,.0f}")
            except Exception:
                lines.append("Margin: ❌ fetch failed")
        else:
            lines.append("Margin: ❌ Kite not authenticated (/login)")

        # Positions
        executor = s.executor_ref
        if executor and hasattr(executor, "states"):
            open_pos = [st for st in executor.states if st.filled_quantity > 0]
            if open_pos:
                lines.append(f"\n<b>{len(open_pos)} position(s):</b>")
                for st in open_pos:
                    try:
                        price = executor.broker.get_ltp(st.leg.symbol)
                        delta = price - st.entry_fill_price
                        if st.leg.direction.value == "short":
                            delta = -delta
                        pnl = delta * st.filled_quantity
                        sign = "+" if pnl >= 0 else ""
                        lines.append(
                            f"  {st.leg.symbol} {st.leg.direction.value.upper()} "
                            f"{st.filled_quantity} @ {st.entry_fill_price:.2f}\n"
                            f"  LTP: {price:.2f} | P&L: {sign}₹{pnl:.0f}"
                        )
                    except Exception:
                        lines.append(f"  {st.leg.symbol} {st.leg.direction.value.upper()} {st.filled_quantity}")
            else:
                waiting = [st for st in executor.states if st.waiting and not st.cancelled]
                if waiting:
                    lines.append(f"\nNo positions | {len(waiting)} waiting for entry")
                else:
                    lines.append("\nNo open positions")

        # Ticker health
        intel = getattr(executor, "_intelligence", None) if executor else None
        if intel:
            h = intel.health
            lines.append(f"\nTicker: {h.status} | Reconnects: {h.reconnect_count}")

        return "\n".join(lines)

    async def _cmd_plan(self, args: list[str]) -> str:
        from tradingbot.core.models import now_ist
        today = now_ist().strftime("%Y-%m-%d")

        try:
            plan = self._state.plan_store.load_latest()
        except Exception:
            return "❌ No plan found"

        lines = [f"\U0001f4dd <b>Plan for {plan.trade_date}</b>"]
        lines.append(f"Regime: {getattr(plan.market_regime, 'value', 'unknown')}")
        lines.append(f"Legs: {len(plan.legs)}\n")

        for leg in plan.legs:
            conf_bar = "█" * int(leg.confidence * 10)
            lines.append(
                f"<b>{leg.symbol}</b> {leg.direction.value.upper()} ({leg.strategy.value})\n"
                f"  Entry: {leg.entry_price:.2f} | SL: {leg.stop_loss:.2f}\n"
                f"  T1: {leg.target_1:.2f} | T2: {leg.target_2:.2f}\n"
                f"  Qty: {leg.quantity} | Conf: {leg.confidence:.0%} {conf_bar}"
            )

        # Review status
        try:
            reviewed = self._state.database.is_plan_reviewed(plan.trade_date)
            lines.append(f"\n{'✅ Reviewed' if reviewed else '⚠️ NOT reviewed — /approve to review'}")
        except Exception:
            pass

        return "\n".join(lines)

    async def _cmd_scout(self, args: list[str]) -> str:
        db = self._state.database
        if db is None:
            return "No database available"

        stats = db.scout_alert_stats()
        from tradingbot.core.models import now_ist
        today = now_ist().strftime("%Y-%m-%d")
        recent = db.get_scout_alerts(trade_date=today, limit=5)

        lines = ["\U0001f52d <b>Scout Signals</b>\n"]

        if stats["total"] > 0:
            lines.append(
                f"All time: {stats['total']} alerts | "
                f"Win: {stats['win_rate']:.0f}% | "
                f"Avg: {stats['avg_pnl_pct']:+.2f}%"
            )
        else:
            lines.append("No graded alerts yet")

        if recent:
            lines.append(f"\n<b>Today ({len(recent)}):</b>")
            for a in recent[:5]:
                ts = a.get("timestamp", "")[-8:-3]
                outcome = a.get("outcome", "pending")
                emoji = "\U0001f3af" if outcome == "target_hit" else "\U0001f6d1" if outcome == "stop_hit" else "⏳"
                lines.append(
                    f"  {emoji} {ts} {a['symbol']} {a['direction'].upper()} "
                    f"({a['signal']}) — {outcome}"
                )
        else:
            lines.append("\nNo alerts today")

        return "\n".join(lines)

    async def _cmd_stats(self, args: list[str]) -> str:
        db = self._state.database
        if db is None:
            return "No database available"

        # Strategy breakdown
        strats = db.strategy_stats()
        if not strats:
            return "\U0001f4ca No trades recorded yet"

        total_pnl = sum(s["total_pnl"] for s in strats)
        total_trades = sum(s["total"] for s in strats)
        total_wins = sum(s["wins"] for s in strats)
        wr = total_wins / total_trades * 100 if total_trades > 0 else 0
        sign = "+" if total_pnl >= 0 else ""

        lines = [
            f"\U0001f4ca <b>Trading Stats</b>\n",
            f"Total P&L: {sign}₹{total_pnl:,.0f}",
            f"Trades: {total_trades} | Win rate: {wr:.0f}%\n",
            "<b>By strategy:</b>",
        ]

        for s in strats:
            swr = s["wins"] / s["total"] * 100 if s["total"] > 0 else 0
            sign = "+" if s["total_pnl"] >= 0 else ""
            emoji = "\U0001f7e2" if s["total_pnl"] > 0 else "\U0001f534"
            lines.append(
                f"  {emoji} {s['strategy']}: {s['total']} trades | "
                f"{swr:.0f}% WR | {sign}₹{s['total_pnl']:,.0f}"
            )

        return "\n".join(lines)

    async def _cmd_health(self, args: list[str]) -> str:
        s = self._state
        lines = ["\U0001f3e5 <b>System Health</b>\n"]

        # Server
        lines.append(f"Server: \U0001f7e2 running")
        lines.append(f"Executor: {s.executor_status}")

        # Kite auth
        if s.kite_auth:
            authed = s.kite_auth.is_authenticated()
            lines.append(f"Kite: {'✅ authenticated' if authed else '❌ not authenticated'}")
        else:
            lines.append("Kite: not configured")

        # Margin (live from Kite only)
        if s.kite_auth and s.kite_auth.is_authenticated():
            try:
                cap = s.capital
                lines.append(f"Margin: ✅ ₹{cap:,.0f}")
            except Exception:
                lines.append("Margin: ❌ fetch failed")
        else:
            lines.append("Margin: ❌ not authenticated (/login)")

        # Ticker
        executor = s.executor_ref
        intel = getattr(executor, "_intelligence", None) if executor else None
        if intel:
            h = intel.health
            tick_ago = ""
            if h.last_tick_at:
                secs = (datetime.now() - h.last_tick_at).total_seconds()
                tick_ago = f" ({secs:.0f}s ago)"
            lines.append(f"Ticker: {h.status}{tick_ago} | Reconnects: {h.reconnect_count}")
        else:
            lines.append("Ticker: not active")

        # Database
        lines.append(f"Database: \U0001f7e2 ok" if s.database else "Database: ❌ unavailable")

        # Sync freshness
        sync = s.sync_status or {}
        if sync.get("freshness"):
            lines.append(f"Data freshness: {sync['freshness'].get('day', 'unknown')}")

        return "\n".join(lines)

    async def _cmd_stop(self, args: list[str]) -> str:
        if args and args[0].lower() == "confirm":
            executor = self._state.executor_ref
            if executor:
                executor.kill_switch_tripped = True
                return "\U0001f6d1 <b>KILL SWITCH TRIGGERED</b>\nAll positions being squared off."
            elif self._state.executor_task and not self._state.executor_task.done():
                self._state.executor_task.cancel()
                self._state.executor_status = "idle"
                return "\U0001f6d1 Execution stopped."
            else:
                return "No execution running."

        return (
            "⚠️ <b>Emergency Stop</b>\n\n"
            "This will trigger the kill switch and square off ALL open positions.\n\n"
            "Send <code>/stop confirm</code> to proceed."
        )

    async def _cmd_approve(self, args: list[str]) -> str:
        db = self._state.database
        if db is None:
            return "No database available"

        try:
            plan = self._state.plan_store.load_latest()
            db.approve_plan(plan.trade_date)
            return f"✅ Plan for {plan.trade_date} approved ({len(plan.legs)} legs)"
        except Exception as exc:
            return f"❌ Failed to approve: {type(exc).__name__}"

    async def _cmd_token(self, args: list[str]) -> str:
        if not args:
            return "Usage: <code>/token YOUR_REQUEST_TOKEN</code>\n\nGet the token from the URL bar after Kite login."

        request_token = args[0].strip()
        s = self._state

        try:
            from tradingbot.execution.kite_auth import KiteAuth
            if s.kite_auth is None:
                s.kite_auth = KiteAuth(
                    api_key=s.config.secrets.kite_api_key,
                    api_secret=s.config.secrets.kite_api_secret,
                )

            data = s.kite_auth.generate_session(request_token)
            user_id = data.get("user_id", "unknown")

            # Verify it works
            try:
                profile = s.kite_auth.kite.profile()
                name = profile.get("user_name", user_id)
            except Exception:
                name = user_id

            return (
                f"✅ <b>Kite Authenticated</b>\n\n"
                f"User: {name}\n"
                f"Token saved. Bot ready for trading.\n\n"
                f"Send /health to verify."
            )
        except Exception as exc:
            return f"❌ Token exchange failed: {type(exc).__name__}\n\nMake sure you copied the full request_token from the URL."

    async def _cmd_login(self, args: list[str]) -> str:
        s = self._state

        # Check if already authenticated
        if s.kite_auth and s.kite_auth.is_authenticated():
            try:
                s.kite_auth.kite.profile()
                return "✅ Kite already authenticated. No login needed."
            except Exception:
                pass

        # Generate login URL
        try:
            from tradingbot.execution.kite_auth import KiteAuth
            if s.kite_auth is None:
                s.kite_auth = KiteAuth(
                    api_key=s.config.secrets.kite_api_key,
                    api_secret=s.config.secrets.kite_api_secret,
                )
            login_url = s.kite_auth.get_login_url()
            return (
                "\U0001f511 <b>Kite Login</b>\n\n"
                f"1. <a href=\"{login_url}\">Tap here to login</a>\n"
                "2. Login with your Kite credentials\n"
                "3. Browser shows 'site can't be reached' — that's OK\n"
                "4. Copy the <b>request_token</b> from the URL bar\n"
                "   (everything after <code>request_token=</code>)\n"
                "5. Send: <code>/token PASTE_TOKEN_HERE</code>\n\n"
                "Example: <code>/token abc123xyz</code>"
            )
        except Exception as exc:
            return f"❌ Failed to generate login URL: {type(exc).__name__}"
