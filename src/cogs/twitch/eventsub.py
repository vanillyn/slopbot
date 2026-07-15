from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import aiohttp

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.cogs.twitch.api import TwitchClient

log = get_logger("twitch.eventsub")

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"
_SESSION_READY_TIMEOUT = 5.0

NotifyCallback = Callable[[str], Awaitable[None]]


class EventSubWebSocket:
    """Twitch EventSub delivered over a plain outbound websocket.

    Twitch pushes events *to* this connection instead of us hosting a public
    HTTPS callback — there's nothing to expose to the internet, no DuckDNS,
    no reverse proxy, no webhook secret. This connects the same way whether
    the bot runs on your laptop or a $5 VPS.

    Caveat vs. the old webhook approach: a websocket-transport subscription
    lives as long as this connection does (Twitch gives ~10 minutes grace on
    a dropped connection before it revokes subscriptions), so we re-subscribe
    everything on reconnect. `subscribe()` remembers broadcaster ids for
    exactly that reason.
    """

    def __init__(self, client: "TwitchClient", notify_callback: NotifyCallback) -> None:
        self._client = client
        self._notify = notify_callback
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session_id: str | None = None
        self._session_ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._subscribed: set[str] = set()
        self._closing = False

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()

    async def subscribe(self, broadcaster_id: str) -> str | None:
        """subscribe to stream.online for a broadcaster. safe to call before the
        websocket session is fully established — it'll wait briefly, and the id
        is remembered for automatic re-subscription on reconnect either way."""
        self._subscribed.add(broadcaster_id)
        try:
            await asyncio.wait_for(self._session_ready.wait(), timeout=_SESSION_READY_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning(
                "eventsub session not ready yet for %s — will subscribe once connected",
                broadcaster_id,
            )
            return None
        assert self._session_id is not None
        return await self._client.subscribe_to_stream_online_ws(broadcaster_id, self._session_id)

    async def _run(self) -> None:
        url = EVENTSUB_WS_URL
        while not self._closing:
            try:
                url = await self._connect_and_listen(url) or EVENTSUB_WS_URL
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("eventsub websocket dropped, reconnecting in 5s")
                self._session_ready.clear()
                await asyncio.sleep(5)
                url = EVENTSUB_WS_URL

    async def _connect_and_listen(self, url: str) -> str | None:
        assert self._session is not None
        next_url: str | None = None
        async with self._session.ws_connect(url) as ws:
            self._ws = ws
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                next_url = await self._handle_message(data)
                if next_url:
                    break
        return next_url

    async def _handle_message(self, data: dict[str, Any]) -> str | None:
        metadata = data.get("metadata", {})
        msg_type = metadata.get("message_type")
        payload = data.get("payload", {})

        if msg_type == "session_welcome":
            self._session_id = payload["session"]["id"]
            self._session_ready.set()
            log.info("eventsub websocket session established (%s)", self._session_id)
            for broadcaster_id in list(self._subscribed):
                await self._client.subscribe_to_stream_online_ws(broadcaster_id, self._session_id)
            return None

        if msg_type == "session_keepalive":
            return None

        if msg_type == "session_reconnect":
            log.info("eventsub asked us to reconnect to a new url")
            self._session_ready.clear()
            return str(payload["session"]["reconnect_url"])

        if msg_type == "notification":
            sub_type = payload.get("subscription", {}).get("type")
            if sub_type == "stream.online":
                broadcaster_id = str(payload["event"]["broadcaster_user_id"])
                try:
                    await self._notify(broadcaster_id)
                except Exception:
                    log.exception("notify callback failed for %s", broadcaster_id)
            return None

        if msg_type == "revocation":
            log.warning("eventsub subscription revoked: %s", payload.get("subscription"))
            return None

        return None
