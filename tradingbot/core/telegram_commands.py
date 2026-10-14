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
ALLOWED_COMMANDS = {"/status", "/plan", "/scout", "/stats", "/health", "/stop", "/approve", "/login", "/help", "/start", "/analyze"}


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


def _pnl(val: float) -> str:
    emoji = "\U0001f7e2" if val >= 0 else "\U0001f534"
    sign = "+" if val >= 0 else ""
    return f"{emoji} {sign}₹{val:,.0f}"


def _status_dot(ok: bool) -> str:
    return "\U0001f7e2" if ok else "\U0001f534"


class TelegramCommandHandler:
    """Long-polls Telegram for commands from the authorized chat."""

    def __init__(self, bot_token: str, chat_id: str, app_state: Any) -> None:
        self._token = bot_token
        self._chat_id = str(chat_id)
        self._state = app_state
        self._offset = 0
        self._running = False
        self._ensure_kite_auth()

    def _ensure_kite_auth(self) -> None:
        """Load saved Kite token from disk if not already authenticated."""
        s = self._state
        if s.kite_auth and s.kite_auth.is_authenticated():
            return
        try:
            from tradingbot.execution.kite_auth import KiteAuth
            saved_token = KiteAuth.load_saved_token()
            if not saved_token:
                return
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=s.config.secrets.kite_api_key)
            kite.set_access_token(saved_token)
            kite.profile()
            if s.kite_auth is None:
                s.kite_auth = KiteAuth(
                    api_key=s.config.secrets.kite_api_key,
                    api_secret=s.config.secrets.kite_api_secret,
                )
            s.kite_auth._access_token = saved_token
            s.kite_auth._kite = kite
            log.info("Loaded saved Kite token on startup")
        except Exception:
            log.info("No valid saved Kite token")

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
            "/execute": self._cmd_execute,
            "/analyze": self._cmd_analyze,
            "/approve": self._cmd_approve,
            "/login": self._cmd_login,
            "/token": self._cmd_token,
            "/deploy": self._cmd_deploy,
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
            f"{_sep()}\n"
            f"\U0001f916 <b>TRADING BOT</b>\n"
            f"{_sep()}\n\n"
            f"<code>"
            f"/status       Positions &amp; P&amp;L\n"
            f"/plan         Trading plan\n"
            f"/scout        Scout signals\n"
            f"/stats        Strategy stats\n"
            f"/health       System health\n"
            f"/analyze      Run analysis\n"
            f"/analyze stop Cancel analysis\n"
            f"/execute      Start execution\n"
            f"/stop confirm Emergency stop\n"
            f"/approve      Approve plan\n"
            f"/deploy       Deploy updates\n"
            f"/login        Kite login URL\n"
            f"/token        Complete login\n"
            f"/help         This message"
            f"</code>"
        )

    async def _cmd_status(self, args: list[str]) -> str:
        s = self._state
        status = s.executor_status.upper()
        mode = f"  •  {s.executor_mode}" if s.executor_mode else ""
        status_dot = _status_dot(status == "RUNNING")

        lines = [
            f"┌─ <b>TRADING BOT</b> ─────────┐",
            f"│  {status_dot} {status}{mode}",
            f"└────────────────────────────┘",
        ]

        # Margin
        if s.kite_auth and s.kite_auth.is_authenticated():
            try:
                cap = s.capital
                lines.append(f"\n💰 <b>Margin</b>  <code>₹{cap:,.0f}</code>")
            except Exception:
                lines.append(f"\n💰 Margin  \U0001f534 fetch failed")
        else:
            lines.append(f"\n💰 Margin  \U0001f534 not authenticated — /login")

        # Positions
        executor = s.executor_ref
        if executor and hasattr(executor, "states"):
            open_pos = [st for st in executor.states if st.filled_quantity > 0]
            if open_pos:
                lines.append(f"\n📊 <b>Positions ({len(open_pos)})</b>")
                for st in open_pos:
                    d_emoji = "📉" if st.leg.direction.value == "short" else "📈"
                    try:
                        price = executor.broker.get_ltp(st.leg.symbol)
                        delta = price - st.entry_fill_price
                        if st.leg.direction.value == "short":
                            delta = -delta
                        pnl = delta * st.filled_quantity
                        lines.append(
                            f"  {d_emoji} <b>{st.leg.symbol}</b> {st.leg.direction.value.upper()} "
                            f"{st.filled_quantity} @ {st.entry_fill_price:.2f}\n"
                            f"     LTP <code>₹{price:.2f}</code>  •  {_pnl(pnl)}"
                        )
                    except Exception:
                        lines.append(f"  {d_emoji} <b>{st.leg.symbol}</b> {st.leg.direction.value.upper()} {st.filled_quantity}")
            else:
                waiting = [st for st in executor.states if st.waiting and not st.cancelled]
                if waiting:
                    lines.append(f"\n📊 No positions  •  {len(waiting)} waiting")
                else:
                    lines.append(f"\n📊 No open positions")

        # Ticker
        intel = getattr(executor, "_intelligence", None) if executor else None
        if intel:
            h = intel.health
            t_dot = _status_dot(h.status == "healthy")
            lines.append(f"\n⚡ Ticker  {t_dot} {h.status}  •  {h.reconnect_count} reconnects")

        return "\n".join(lines)

    async def _cmd_plan(self, args: list[str]) -> str:
        try:
            plan = self._state.plan_store.load_latest()
        except Exception:
            return "\U0001f534 No plan found"

        regime = getattr(plan.market_regime, "value", "unknown")
        lines = [
            f"{_sep()}",
            f"\U0001f4dd <b>PLAN — {plan.trade_date}</b>",
            f"{_sep()}",
            f"",
            f"<code>Regime  {regime}\nLegs    {len(plan.legs)}</code>",
        ]

        for leg in plan.legs:
            d_emoji = "📉" if leg.direction.value == "short" else "📈"
            conf_bar = "█" * int(leg.confidence * 10) + "░" * (10 - int(leg.confidence * 10))
            lines.append(
                f"\n{d_emoji} <b>{leg.symbol}</b>  •  {leg.direction.value.upper()}\n"
                f"<code>"
                f"Entry  ₹{leg.entry_price:,.2f}   SL  ₹{leg.stop_loss:,.2f}\n"
                f"T1     ₹{leg.target_1:,.2f}   T2  ₹{leg.target_2:,.2f}\n"
                f"Qty    {leg.quantity}         Conf {leg.confidence:.0%}\n"
                f"{conf_bar}"
                f"</code>"
            )

        try:
            reviewed = self._state.database.is_plan_reviewed(plan.trade_date)
            lines.append(f"\n{'✅ <i>Reviewed</i>' if reviewed else '⚠️ <i>Not reviewed — /approve</i>'}")
        except Exception:
            pass

        return "\n".join(lines)

    async def _cmd_scout(self, args: list[str]) -> str:
        db = self._state.database
        if db is None:
            return "\U0001f534 No database available"

        stats = db.scout_alert_stats()
        from tradingbot.core.models import now_ist
        today = now_ist().strftime("%Y-%m-%d")
        recent = db.get_scout_alerts(trade_date=today, limit=5)

        lines = [
            f"{_sep()}",
            f"\U0001f52d <b>SCOUT SIGNALS</b>",
            f"{_sep()}",
        ]

        if stats["total"] > 0:
            wr = stats["win_rate"]
            wr_dot = _status_dot(wr >= 50)
            lines.append(
                f"\n<code>"
                f"Total    {stats['total']} alerts\n"
                f"Win rate {wr_dot} {wr:.0f}%\n"
                f"Avg P&amp;L  {stats['avg_pnl_pct']:+.2f}%"
                f"</code>"
            )
        else:
            lines.append("\n<i>No graded alerts yet</i>")

        if recent:
            lines.append(f"\n<b>Today ({len(recent)})</b>")
            for a in recent[:5]:
                ts = a.get("timestamp", "")[-8:-3]
                outcome = a.get("outcome", "pending")
                emoji = "\U0001f3af" if outcome == "target_hit" else "\U0001f6d1" if outcome == "stop_hit" else "⏳"
                lines.append(
                    f"  {emoji} <code>{ts}</code>  {a['symbol']} {a['direction'].upper()}"
                    f"  •  <i>{outcome}</i>"
                )
        else:
            lines.append(f"\n<i>No alerts today</i>")

        return "\n".join(lines)

    async def _cmd_stats(self, args: list[str]) -> str:
        db = self._state.database
        if db is None:
            return "\U0001f534 No database available"

        strats = db.strategy_stats()
        if not strats:
            return "📊 <i>No trades recorded yet</i>"

        total_pnl = sum(s["total_pnl"] for s in strats)
        total_trades = sum(s["total"] for s in strats)
        total_wins = sum(s["wins"] for s in strats)
        wr = total_wins / total_trades * 100 if total_trades > 0 else 0

        lines = [
            f"{_sep()}",
            f"📊 <b>TRADING STATS</b>",
            f"{_sep()}",
            f"",
            f"<code>"
            f"P&amp;L       {_pnl(total_pnl)}\n"
            f"Trades    {total_trades}\n"
            f"Win rate  {wr:.0f}%"
            f"</code>",
            f"",
            f"<b>By Strategy</b>",
        ]

        for s in strats:
            swr = s["wins"] / s["total"] * 100 if s["total"] > 0 else 0
            dot = _status_dot(s["total_pnl"] > 0)
            sign = "+" if s["total_pnl"] >= 0 else ""
            lines.append(
                f"  {dot} {s['strategy']}  •  {s['total']} trades  •  "
                f"{swr:.0f}% WR  •  {sign}₹{s['total_pnl']:,.0f}"
            )

        return "\n".join(lines)

    async def _cmd_health(self, args: list[str]) -> str:
        s = self._state

        # Kite
        kite_ok = False
        if s.kite_auth:
            kite_ok = s.kite_auth.is_authenticated()
        kite_label = "authenticated" if kite_ok else "not authenticated"

        # Margin
        margin_str = "—"
        if s.kite_auth and s.kite_auth.is_authenticated():
            try:
                cap = s.capital
                margin_str = f"₹{cap:,.0f}"
            except Exception:
                margin_str = "fetch failed"

        # Ticker
        executor = s.executor_ref
        intel = getattr(executor, "_intelligence", None) if executor else None
        ticker_ok = False
        ticker_label = "not active"
        if intel:
            h = intel.health
            ticker_ok = h.status == "healthy"
            tick_ago = ""
            if h.last_tick_at:
                secs = (datetime.now() - h.last_tick_at).total_seconds()
                tick_ago = f" ({secs:.0f}s ago)"
            ticker_label = f"{h.status}{tick_ago}"

        db_ok = s.database is not None

        lines = [
            f"┌─ <b>SYSTEM HEALTH</b> ─────────┐",
            f"│                              │",
            f"│  Server    {_status_dot(True)} running         │",
            f"│  Executor  🟡 {s.executor_status:<14}│",
            f"│  Kite      {_status_dot(kite_ok)} {kite_label:<14}│",
            f"│  Margin    {margin_str:<18}│",
            f"│  Ticker    {_status_dot(ticker_ok)} {ticker_label:<14}│",
            f"│  Database  {_status_dot(db_ok)} {'ok' if db_ok else 'unavailable':<14}│",
            f"│                              │",
            f"└──────────────────────────────┘",
        ]

        sync = s.sync_status or {}
        if sync.get("freshness"):
            lines.append(f"\n<code>Data freshness  {sync['freshness'].get('day', '—')}</code>")

        return "\n".join(lines)

    async def _cmd_analyze(self, args: list[str]) -> str:
        s = self._state

        if args and args[0].lower() == "stop":
            if s.analysis_status != "running":
                return "No analysis running."
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post("http://localhost:8000/api/analyze/cancel")
                    data = resp.json()
                    return f"\U0001f6d1 Analysis {data.get('status', 'cancelled')}."
            except Exception as exc:
                return f"❌ Cancel failed: {type(exc).__name__}"

        if args and args[0].lower() == "status":
            if s.analysis_status != "running":
                return f"Analysis status: {s.analysis_status or 'idle'}"
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get("http://localhost:8000/api/analyze/status")
                    data = resp.json()
                    step = data.get("current_step", "?")
                    elapsed = data.get("elapsed_sec", 0)
                    return (
                        f"\U0001f50d <b>Analysis Running</b>\n\n"
                        f"<code>Step     {step}\n"
                        f"Elapsed  {elapsed}s</code>"
                    )
            except Exception as exc:
                return f"❌ Status check failed: {type(exc).__name__}"

        if s.analysis_status == "running":
            return "⚠️ Analysis already running. Send /analyze status to check."

        try:
            import httpx
            trade_date_arg = args[0] if args else None
            body = {"trade_date": trade_date_arg} if trade_date_arg else {}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "http://localhost:8000/api/analyze",
                    json=body,
                )
                data = resp.json()
                if resp.status_code != 200:
                    return f"❌ {data.get('detail', 'Failed to start analysis')}"
                return (
                    f"\U0001f50d <b>Analysis Started</b>\n\n"
                    f"<code>Date  {data.get('trade_date', '?')}</code>\n\n"
                    f"Progress updates will follow.\n"
                    f"Send <code>/analyze stop</code> to cancel."
                )
        except Exception as exc:
            return f"❌ Failed to start: {type(exc).__name__}"

    async def _cmd_execute(self, args: list[str]) -> str:
        s = self._state
        if s.executor_status == "running":
            return "⚠️ Executor already running. Send /status to check."

        mode = args[0] if args else "live"
        if mode not in ("live", "paper"):
            return "Usage: <code>/execute [live|paper]</code>\nDefault: live"

        try:
            plan = s.plan_store.load_latest()
            if not plan.legs:
                return "❌ No legs in plan. Run analysis first."
        except Exception:
            return "❌ No plan found. Run analysis first."

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "http://localhost:8000/api/execute",
                    json={"mode": mode},
                )
                data = resp.json()
                if resp.status_code == 409:
                    return "⚠️ Executor already running."
                if resp.status_code != 200:
                    return f"❌ Failed: {data.get('detail', 'unknown error')}"
                return (
                    f"━━━ EXECUTION STARTED ━━━\n\n"
                    f"<b>Mode</b>  {mode.upper()}\n"
                    f"<b>Date</b>  {data.get('trade_date', '?')}\n"
                    f"<b>Legs</b>  {len(plan.legs)}\n\n"
                    f"Send /status to monitor."
                )
        except Exception as exc:
            return f"❌ Failed to start: {type(exc).__name__}"

    async def _cmd_stop(self, args: list[str]) -> str:
        if args and args[0].lower() == "confirm":
            executor = self._state.executor_ref
            if executor:
                executor.kill_switch_tripped = True
                return (
                    f"{_sep()}\n"
                    f"\U0001f6d1 <b>KILL SWITCH TRIGGERED</b>\n"
                    f"{_sep()}\n\n"
                    f"All positions being squared off."
                )
            elif self._state.executor_task and not self._state.executor_task.done():
                self._state.executor_task.cancel()
                self._state.executor_status = "idle"
                return "\U0001f6d1 Execution stopped."
            else:
                return "No execution running."

        return (
            f"⚠️ <b>EMERGENCY STOP</b>\n\n"
            f"This will trigger the kill switch and\n"
            f"square off <b>ALL</b> open positions.\n\n"
            f"Send <code>/stop confirm</code> to proceed."
        )

    async def _cmd_approve(self, args: list[str]) -> str:
        db = self._state.database
        if db is None:
            return "\U0001f534 No database available"

        try:
            plan = self._state.plan_store.load_latest()
            db.approve_plan(plan.trade_date)
            return (
                f"✅ <b>Plan Approved</b>\n\n"
                f"<code>"
                f"Date   {plan.trade_date}\n"
                f"Legs   {len(plan.legs)}"
                f"</code>"
            )
        except Exception as exc:
            return f"\U0001f534 Failed to approve: {type(exc).__name__}"

    async def _cmd_deploy(self, args: list[str]) -> str:
        import subprocess
        try:
            result = subprocess.run(
                ["git", "pull", "origin", "master"],
                capture_output=True, text=True, timeout=30,
                cwd="/home/ubuntu/trading-bot",
            )
            if result.returncode != 0:
                return f"\U0001f534 Git pull failed:\n<code>{result.stderr[:200]}</code>"

            if "Already up to date" in result.stdout:
                return "✅ Already up to date. No restart needed."

            commit = subprocess.run(
                ["git", "log", "-1", "--format=%h %s"],
                capture_output=True, text=True, timeout=5,
                cwd="/home/ubuntu/trading-bot",
            ).stdout.strip()

            subprocess.Popen(
                ["bash", "-c", "sleep 3 && sudo systemctl restart tradingbot"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

            return (
                f"✅ <b>Deployed</b>\n\n"
                f"<code>{commit}</code>\n\n"
                f"<i>Service restarting in 3s...</i>"
            )
        except subprocess.TimeoutExpired:
            return "\U0001f534 Deploy timed out"
        except Exception as exc:
            return f"\U0001f534 Deploy failed: {type(exc).__name__}"

    async def _cmd_token(self, args: list[str]) -> str:
        if not args:
            return (
                f"<b>Usage</b>\n"
                f"<code>/token YOUR_REQUEST_TOKEN</code>\n\n"
                f"<i>Copy the token from the URL bar after Kite login.</i>"
            )

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

            from pathlib import Path
            token_path = Path.home() / ".tradingbot" / "kite_token"
            token_path.parent.mkdir(parents=True, exist_ok=True)
            access_token = s.kite_auth.kite.access_token
            if access_token:
                token_path.write_text(access_token)
                token_path.chmod(0o600)

            try:
                profile = s.kite_auth.kite.profile()
                name = profile.get("user_name", user_id)
            except Exception:
                name = user_id

            return (
                f"✅ <b>KITE AUTHENTICATED</b>\n\n"
                f"<code>"
                f"User    {name}\n"
                f"Status  Token saved to disk"
                f"</code>\n\n"
                f"<i>Bot ready for trading. Send /health to verify.</i>"
            )
        except Exception as exc:
            return (
                f"\U0001f534 <b>Token exchange failed</b>\n\n"
                f"<code>{type(exc).__name__}</code>\n\n"
                f"<i>Make sure you copied the full request_token from the URL.</i>"
            )

    async def _cmd_login(self, args: list[str]) -> str:
        s = self._state

        if s.kite_auth and s.kite_auth.is_authenticated():
            try:
                s.kite_auth.kite.profile()
                return "✅ Kite already authenticated. No login needed."
            except Exception:
                pass

        try:
            from tradingbot.execution.kite_auth import KiteAuth
            if s.kite_auth is None:
                s.kite_auth = KiteAuth(
                    api_key=s.config.secrets.kite_api_key,
                    api_secret=s.config.secrets.kite_api_secret,
                )
            login_url = s.kite_auth.get_login_url()
            return (
                f"\U0001f511 <b>KITE LOGIN</b>\n\n"
                f"<b>1.</b> <a href=\"{login_url}\">Tap here to login</a>\n"
                f"<b>2.</b> Login with your credentials\n"
                f"<b>3.</b> Browser shows 'can't be reached' — OK\n"
                f"<b>4.</b> Copy <code>request_token</code> from URL bar\n"
                f"<b>5.</b> Send:\n\n"
                f"<code>/token PASTE_TOKEN_HERE</code>"
            )
        except Exception as exc:
            return f"\U0001f534 Failed to generate login URL: {type(exc).__name__}"
