from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from aiohttp import web

from src.cogs.twitch.api import TWITCH_WEBHOOK_SECRET
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("twitch.webserver")

NotifyCallback = Callable[[str], Awaitable[None]]

WEBHOOK_PATH = "/webhook/twitch"


def _verify_signature(headers: "web.RequestHeaders", body: bytes) -> bool:
    if not TWITCH_WEBHOOK_SECRET:
        # misconfiguration — refuse rather than silently accepting unsigned payloads
        return False
    msg_id = headers.get("Twitch-Eventsub-Message-Id", "")
    timestamp = headers.get("Twitch-Eventsub-Message-Timestamp", "")
    signature = headers.get("Twitch-Eventsub-Message-Signature", "")
    hmac_message = (msg_id + timestamp).encode() + body
    expected = (
        "sha256="
        + hmac.new(TWITCH_WEBHOOK_SECRET.encode(), hmac_message, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


def build_app(notify_callback: NotifyCallback) -> web.Application:
    """builds the tiny aiohttp app that receives twitch's EventSub webhook
    deliveries. this is intentionally minimal — just the one route — and
    runs on its own port, independent of the main dashboard
    (src/web/server.py)."""
    app = web.Application()

    async def webhook_handler(request: web.Request) -> web.Response:
        body = await request.read()
        if not _verify_signature(request.headers, body):
            return web.Response(status=403, text="forbidden")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return web.Response(status=400, text="bad request")

        msg_type = request.headers.get("Twitch-Eventsub-Message-Type")

        if msg_type == "webhook_callback_verification":
            return web.Response(status=200, text=data["challenge"])

        if msg_type == "notification":
            sub_type = data.get("subscription", {}).get("type")
            if sub_type == "stream.online":
                broadcaster_id: str = data["event"]["broadcaster_user_id"]
                try:
                    await notify_callback(broadcaster_id)
                except Exception:
                    log.exception("notify callback failed for %s", broadcaster_id)

        if msg_type == "revocation":
            log.warning("eventsub webhook subscription revoked: %s", data.get("subscription"))

        return web.Response(status=204)

    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    return app


class TwitchWebhookServer:
    """runs the EventSub webhook receiver on its own port. requires a
    publicly reachable https url (TWITCH_WEBHOOK_CALLBACK_URL) pointing at
    this port + WEBHOOK_PATH — twitch will POST event deliveries here."""

    def __init__(
        self,
        notify_callback: NotifyCallback,
        host: str = "0.0.0.0",
        port: int = 8082,
    ) -> None:
        self._app = build_app(notify_callback)
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        log.info("twitch webhook listener started on %s:%s%s", self._host, self._port, WEBHOOK_PATH)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
