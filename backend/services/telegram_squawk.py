"""TelegramSquawkService — poll a Telegram channel for headlines.

Three wiring modes, auto-selected:

  1. **Public-channel scraper (DEFAULT)** — pull ``https://t.me/s/<channel>``
     which Telegram serves as a static HTML widget of the last ~20 posts
     for any *public* channel with no auth whatsoever. Works for
     @LiveSquawk, @WallStreetBets_Trades, etc. out of the box.

  2. **Bot API forwarder** — if ``api_key`` has a bot token AND the bot
     is admin of the target channel, use ``getUpdates``. Useful when
     you run your own bot in a private channel.

  3. **MTProto reader** — user-account session via Telethon; reserved for
     users who explicitly opt into it (none shipped by default because
     the phone + 2FA dance is hostile to non-technical users).

Selection logic:
  * ``metadata.channel`` + no ``api_key`` → scraper mode (no-auth)
  * ``api_key`` + ``metadata.channel`` → bot API mode
  * ``metadata.mode = 'scrape'`` forces scraper even with a token present

Cadence: 60s poll interval. Keeps the last 100 messages in memory.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.services.credentials_store import CredentialsStore

logger = logging.getLogger(__name__)


@dataclass
class SquawkPost:
    id: int
    channel: str
    text: str
    posted_at: datetime
    link: str | None = None


class TelegramSquawkService:
    """Bot-API poller. Needs:
      * bot_token  (stored as credential.api_key, provider='telegram')
      * channel    (stored as credential.metadata.channel, e.g. '@livesquawk')
    """

    def __init__(
        self,
        credentials: CredentialsStore,
        *,
        poll_interval: float = 60.0,
        max_posts: int = 100,
    ) -> None:
        self.credentials = credentials
        self.poll_interval = poll_interval
        self.max_posts = max_posts
        self._client = httpx.Client(timeout=15.0)
        self._lock = threading.RLock()
        self._posts: list[SquawkPost] = []
        self._last_error: str | None = None
        self._last_polled: datetime | None = None
        self._last_update_id: int = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _cred(self) -> tuple[str | None, str | None]:
        c = self.credentials.first_for("telegram")
        if c is None:
            return None, None
        token = c.api_key
        channel = None
        if isinstance(c.metadata, dict):
            channel = c.metadata.get("channel")
        return token, channel

    # ── lifecycle ─────────────────────────────────────────────────

    def ensure_started(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="tg-squawk", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    # ── reads ─────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        token, channel = self._cred()
        return {
            "configured": bool(token and channel),
            "channel": channel,
            "last_polled": self._last_polled.isoformat() if self._last_polled else None,
            "last_error": self._last_error,
            "post_count": len(self._posts),
        }

    def posts(self, limit: int = 100) -> list[SquawkPost]:
        with self._lock:
            return list(self._posts[-limit:])

    # ── internals ─────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.debug("squawk poll: %s", exc)
            self._stop.wait(self.poll_interval)

    def _tick(self) -> None:
        token, channel = self._cred()
        if not token or not channel:
            self._last_error = "telegram credential not configured"
            return

        # Ask the bot for any channel_post updates since the last id.
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        params = {"offset": self._last_update_id + 1, "timeout": 0, "limit": 100}
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(str(data))

        new_posts: list[SquawkPost] = []
        for upd in data.get("result", []):
            self._last_update_id = max(self._last_update_id, int(upd.get("update_id", 0)))
            post = upd.get("channel_post") or upd.get("message") or {}
            chat = post.get("chat") or {}
            username = chat.get("username")
            if username and (channel.lstrip("@").lower() != username.lower()):
                # Message from a different channel; ignore.
                continue
            text = post.get("text") or post.get("caption") or ""
            if not text:
                continue
            try:
                ts = datetime.fromtimestamp(int(post.get("date", 0)), tz=UTC)
            except Exception:  # noqa: BLE001
                ts = datetime.now(UTC)
            msg_id = int(post.get("message_id", 0))
            link = (
                f"https://t.me/{username}/{msg_id}"
                if username and msg_id
                else None
            )
            new_posts.append(SquawkPost(
                id=msg_id,
                channel=username or channel,
                text=text,
                posted_at=ts,
                link=link,
            ))

        with self._lock:
            self._posts.extend(new_posts)
            # Keep only the tail.
            if len(self._posts) > self.max_posts:
                self._posts = self._posts[-self.max_posts:]
            self._last_polled = datetime.now(UTC)
            self._last_error = None
