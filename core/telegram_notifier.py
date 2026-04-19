"""Telegram notification module – sends trade alerts & receives commands via Telegram bot."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends trade alerts to a Telegram chat via Bot API."""

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        enabled: bool = False,
    ):
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = enabled and bool(self.bot_token) and bool(self.chat_id)
        self._base_url = f"https://api.telegram.org/bot{self.bot_token}"

        if self.enabled:
            logger.info(f"Telegram notifier enabled → chat {self.chat_id}")
        else:
            logger.info("Telegram notifier disabled")

    # ── Public API ──────────────────────────────────────────────
    def notify_open(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        entry_price: float,
        leverage: int,
        sl_pct: float,
        tp_pct: float,
        reason: str = "",
        slot_id: int | None = None,
    ):
        """Send a Telegram message when a position is opened."""
        slot_label = f" (Slot #{slot_id})" if slot_id is not None else ""
        emoji = "📈" if side == "LONG" else "📉"

        if side == "LONG":
            sl_price = entry_price * (1 - sl_pct / 100)
            tp_price = entry_price * (1 + tp_pct / 100)
        else:
            sl_price = entry_price * (1 + sl_pct / 100)
            tp_price = entry_price * (1 - tp_pct / 100)

        text = (
            f"{emoji} *{side} Opened*{slot_label}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"*Symbol:* `{symbol}`\n"
            f"*Entry:* `${entry_price:,.2f}`\n"
            f"*Size:* `${size_usd:,.2f}` @ `{leverage}x`\n"
            f"🔴 *SL:* `{sl_pct}%` → `${sl_price:,.2f}`\n"
            f"🟢 *TP:* `{tp_pct}%` → `${tp_price:,.2f}`\n"
            f"*Reason:* {reason}\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._send(text)

    def notify_close(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl: float | None = None,
        reason: str = "",
        slot_id: int | None = None,
    ):
        """Send a Telegram message when a position is closed."""
        slot_label = f" (Slot #{slot_id})" if slot_id is not None else ""
        pnl_str = f"${pnl:+,.2f}" if pnl is not None else "--"
        emoji = "✅" if (pnl or 0) >= 0 else "🔴"

        change_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
        if side == "SHORT":
            change_pct = -change_pct

        text = (
            f"{emoji} *Position Closed*{slot_label}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"*Symbol:* `{symbol}` ({side})\n"
            f"*Entry:* `${entry_price:,.2f}`\n"
            f"*Exit:* `${exit_price:,.2f}`\n"
            f"*Change:* `{change_pct:+.2f}%`\n"
            f"*P&L:* `{pnl_str}`\n"
            f"*Reason:* {reason}\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._send(text)

    def notify_trailing_sl_update(
        self,
        symbol: str,
        old_sl: float,
        new_sl: float,
        current_price: float,
        slot_id: int | None = None,
    ):
        """Notify when trailing stop loss is moved up."""
        slot_label = f" (Slot #{slot_id})" if slot_id is not None else ""
        text = (
            f"🔄 *Trailing SL Updated*{slot_label}\n"
            f"*{symbol}* @ `${current_price:,.2f}`\n"
            f"SL: `${old_sl:,.2f}` → `${new_sl:,.2f}`"
        )
        self._send(text)

    def send_test(self) -> tuple[bool, str]:
        """Send a test message. Returns (success, message)."""
        if not self.enabled:
            return False, "Telegram not configured"
        text = (
            "🤖 *Hyperliquid Bot — Test*\n"
            f"Telegram alerts are working\\!\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self._send(text, sync=True)

    # ── Internal ────────────────────────────────────────────────
    def _send(self, text: str, sync: bool = False) -> tuple[bool, str]:
        """Send a Telegram message. Runs async by default."""
        if not self.enabled:
            return False, "Disabled"

        def _worker():
            try:
                resp = requests.post(
                    f"{self._base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                    timeout=10,
                )
                data = resp.json()
                if data.get("ok"):
                    logger.info("Telegram message sent")
                else:
                    logger.error(f"Telegram API error: {data.get('description', data)}")
            except Exception as e:
                logger.error(f"Telegram send failed: {e}")

        if sync:
            try:
                resp = requests.post(
                    f"{self._base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                    timeout=10,
                )
                data = resp.json()
                if data.get("ok"):
                    return True, "Message sent!"
                return False, data.get("description", "Unknown error")
            except Exception as e:
                return False, str(e)

        t = threading.Thread(target=_worker, daemon=True, name="telegram-send")
        t.start()
        return True, "Sending..."


# ════════════════════════════════════════════════════════════════
#  Telegram Command Listener (long-polling)
# ════════════════════════════════════════════════════════════════
class TelegramCommandListener:
    """
    Polls the Telegram Bot API for incoming commands and dispatches them.

    Supported commands:
        /status  – show all positions, P&L, balance
        /stop    – stop the bot
        /start   – start the bot
        /close BTC   – close a specific symbol
        /close all   – close every open position
        /slots   – list active slot configs
    """

    POLL_INTERVAL = 2  # seconds between polls

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        notifier: TelegramNotifier,
    ):
        self._token = bot_token.strip()
        self._chat_id = chat_id.strip()
        self._notifier = notifier
        self._base_url = f"https://api.telegram.org/bot{self._token}"
        self._offset: int = 0  # tracks last processed update
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Callbacks – set by the dashboard
        self.on_status: Optional[Callable[[], str]] = None
        self.on_stop: Optional[Callable[[], str]] = None
        self.on_start: Optional[Callable[[], str]] = None
        self.on_close: Optional[Callable[[str], str]] = None   # arg = symbol or "all"
        self.on_slots: Optional[Callable[[], str]] = None

    # ── lifecycle ───────────────────────────────────────────────
    def start(self):
        """Flush old updates and begin polling in a daemon thread."""
        if self._running:
            return
        self._running = True
        # Flush pending updates so we don't replay old commands
        self._flush_pending_updates()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="tg-cmd-poll")
        self._thread.start()
        logger.info("Telegram command listener started")

    def stop(self):
        self._running = False
        logger.info("Telegram command listener stopped")

    # ── polling ─────────────────────────────────────────────────
    def _flush_pending_updates(self):
        """Read and discard all updates that arrived before the bot started."""
        try:
            resp = requests.get(
                f"{self._base_url}/getUpdates",
                params={"timeout": 0, "offset": -1},
                timeout=10,
            )
            data = resp.json()
            if data.get("ok") and data.get("result"):
                last = data["result"][-1]
                self._offset = last["update_id"] + 1
                logger.info(f"Flushed pending Telegram updates; offset={self._offset}")
        except Exception as e:
            logger.warning(f"Failed to flush Telegram updates: {e}")

    def _poll_loop(self):
        while self._running:
            try:
                resp = requests.get(
                    f"{self._base_url}/getUpdates",
                    params={"timeout": 15, "offset": self._offset},
                    timeout=25,
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.warning(f"Telegram getUpdates error: {data}")
                    time.sleep(self.POLL_INTERVAL)
                    continue

                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._handle_update(update)

            except requests.exceptions.Timeout:
                continue
            except Exception as e:
                logger.error(f"Telegram poll error: {e}")
                time.sleep(self.POLL_INTERVAL)

    # ── dispatch ────────────────────────────────────────────────
    def _handle_update(self, update: dict):
        msg = update.get("message")
        if not msg:
            return

        # Security: only respond to the authorised chat
        msg_chat_id = str(msg.get("chat", {}).get("id", ""))
        if msg_chat_id != self._chat_id:
            logger.warning(f"Telegram command from unauthorised chat {msg_chat_id}")
            return

        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return

        parts = text.split()
        cmd = parts[0].lower().split("@")[0]  # strip @botname suffix
        args = parts[1:]

        logger.info(f"Telegram command: {cmd} {args}")

        reply = self._dispatch(cmd, args)
        if reply:
            self._reply(reply)

    def _dispatch(self, cmd: str, args: list[str]) -> str:
        if cmd == "/status":
            return self.on_status() if self.on_status else "No handler"
        elif cmd == "/stop":
            return self.on_stop() if self.on_stop else "No handler"
        elif cmd == "/start":
            return self.on_start() if self.on_start else "No handler"
        elif cmd == "/close":
            target = args[0].upper() if args else "ALL"
            return self.on_close(target) if self.on_close else "No handler"
        elif cmd == "/slots":
            return self.on_slots() if self.on_slots else "No handler"
        elif cmd == "/help":
            return (
                "🤖 *Hyperliquid Bot Commands*\n"
                "━━━━━━━━━━━━━━━\n"
                "/status — positions, P&L, balance\n"
                "/stop — stop the bot\n"
                "/start — start the bot\n"
                "/close BTC — close one symbol\n"
                "/close all — close everything\n"
                "/slots — active slot configs\n"
                "/help — this message"
            )
        else:
            return f"Unknown command: {cmd}\nType /help for available commands."

    def _reply(self, text: str):
        """Send a reply back to the authorised chat."""
        try:
            requests.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Telegram reply failed: {e}")
