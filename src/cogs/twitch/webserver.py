from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from html import escape
from typing import TYPE_CHECKING

import discord
from aiohttp import web

from src.cogs.twitch.api import TWITCH_WEBHOOK_SECRET
from src.cogs.twitch.db import get_all_streamers, update_streamer
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.cogs.music.cog import MusicCog

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("twitch.webserver")

NotifyCallback = Callable[[str], Awaitable[None]]


def _verify_signature(headers: "web.RequestHeaders", body: bytes) -> bool:
    msg_id = headers.get("Twitch-Eventsub-Message-Id", "")
    timestamp = headers.get("Twitch-Eventsub-Message-Timestamp", "")
    signature = headers.get("Twitch-Eventsub-Message-Signature", "")
    hmac_message = (msg_id + timestamp).encode() + body
    expected = (
        "sha256="
        + hmac.new(TWITCH_WEBHOOK_SECRET.encode(), hmac_message, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


async def _build_dashboard_page(bot: "Bot | None") -> str:
    streamers = []
    guild_panels = []
    if bot is not None:
        streamers = await get_all_streamers(bot.db)  # type: ignore[attr-defined]
        for guild in bot.guilds:
            queue_cog = bot.get_cog("queue")
            state = queue_cog.get_state(guild.id) if queue_cog is not None else {"current": None, "queue": []}
            current = state.get("current")
            title = current.get("metadata", {}).get("title", "nothing") if current else "nothing"
            queue_items = state.get("queue", [])
            queue_lines = []
            for item in queue_items[:6]:
                metadata = item.get("metadata", {})
                queue_lines.append(f"<li>{escape(str(metadata.get('title', 'unknown')))}</li>")
            queue_markup = "<ul>" + "".join(queue_lines) + "</ul>" if queue_lines else "<p><small>queue is empty</small></p>"
            guild_panels.append(
                f"""
                <div class='panel'>
                  <h3>{escape(guild.name)}</h3>
                  <p><strong>Now playing:</strong> {escape(str(title))}</p>
                  <p><small>{len(queue_items)} queued</small></p>
                  <div class='queue-list'>{queue_markup}</div>
                  <form class='queue-form' data-guild-id='{guild.id}'>
                    <label>queue youtube url<input name='url' placeholder='https://youtube.com/watch?v=...' /></label>
                    <button type='submit'>queue</button>
                  </form>
                  <div class='controls'>
                    <button class='music-action' data-url='/api/music/skip?guild_id={guild.id}'>skip</button>
                    <button class='music-action' data-url='/api/music/stop?guild_id={guild.id}'>stop</button>
                  </div>
                </div>
                """
            )

    streamer_rows = []
    for streamer in streamers:
        streamer_rows.append(
            f"""
            <div class='panel streamer-card'>
              <h3>{escape(str(streamer['twitch_username']))}</h3>
              <p>Guild {escape(str(streamer.get('guild_id', 0)))} • Channel {escape(str(streamer.get('discord_channel_id', 0)))} • Role {escape(str(streamer.get('ping_role_id', 0)))}</p>
              <form class='config-form' data-twitch-id='{escape(str(streamer['twitch_user_id']))}' data-guild-id='{escape(str(streamer.get('guild_id', 0)))}'>
                <label>channel id<input name='discord_channel_id' value='{escape(str(streamer.get('discord_channel_id', 0)))}' /></label>
                <label>role id<input name='ping_role_id' value='{escape(str(streamer.get('ping_role_id', 0)))}' /></label>
                <label>message<input name='custom_message' value='{escape(str(streamer.get('custom_message', '')))}' /></label>
                <label>footer<input name='footer_message' value='{escape(str(streamer.get('footer_message', '')))}' /></label>
                <label>accent<input name='accent_color' value='{escape(str(streamer.get('accent_color', 0)))}' /></label>
                <button type='submit'>save</button>
              </form>
            </div>
            """
        )

    guild_panels_html = "".join(guild_panels)
    streamer_rows_html = "".join(streamer_rows)

    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset='utf-8' />
        <title>retro dashboard</title>
        <style>
          body {{ font-family: 'Trebuchet MS', 'Verdana', sans-serif; background: #111; color: #f7e7b2; padding: 24px; }}
          .wrap {{ max-width: 1120px; margin: 0 auto; }}
          .banner {{ border: 4px double #f7e7b2; background: #2b1d0f; padding: 16px 20px; box-shadow: 8px 8px 0 #000; }}
          .panel {{ border: 3px solid #f7e7b2; background: #1b140b; padding: 14px; margin-top: 16px; box-shadow: 6px 6px 0 #000; }}
          .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
          label {{ display: block; margin-top: 8px; font-size: 12px; text-transform: uppercase; }}
          input {{ width: 100%; padding: 6px; margin-top: 4px; background: #f8edd2; color: #111; border: 2px solid #000; }}
          button {{ margin-top: 10px; background: #f7e7b2; color: #111; border: 2px solid #000; padding: 8px 12px; cursor: pointer; }}
          .controls {{ display: flex; gap: 8px; flex-wrap: wrap; }}
          .queue-list {{ margin-top: 8px; padding: 8px; background: #0f0b06; border: 1px dashed #f7e7b2; }}
          .queue-list ul {{ margin: 0; padding-left: 16px; }}
        </style>
      </head>
      <body>
        <div class='wrap'>
          <div class='banner'>
            <h1>⋄ arcade control panel ⋄</h1>
            <p>retro twitch + music dashboard for the bot.</p>
          </div>
          <div class='panel'>
            <h2>server pulse</h2>
            <div class='grid'>{guild_panels_html}</div>
          </div>
          <div class='panel'>
            <h2>twitch streamers</h2>
            <div class='grid'>{streamer_rows_html}</div>
          </div>
        </div>
        <script>
          document.querySelectorAll('.config-form').forEach((form) => {{
            form.addEventListener('submit', async (event) => {{
              event.preventDefault();
              const payload = Object.fromEntries(new FormData(form));
              payload.twitch_user_id = form.dataset.twitchId;
              payload.guild_id = form.dataset.guildId;
              const response = await fetch('/api/streamers', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(payload)}});
              if (response.ok) {{
                alert('saved');
              }} else {{
                alert('save failed');
              }}
            }});
          }});
          document.querySelectorAll('.queue-form').forEach((form) => {{
            form.addEventListener('submit', async (event) => {{
              event.preventDefault();
              const guildId = form.dataset.guildId;
              const response = await fetch(`/api/music/queue?guild_id=${{guildId}}`, {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{url: form.elements.url.value}})}});
              const payload = await response.json();
              alert(payload.message || 'done');
              location.reload();
            }});
          }});
          document.querySelectorAll('.music-action').forEach((button) => {{
            button.addEventListener('click', async () => {{
              const response = await fetch(button.dataset.url, {{method: 'POST'}});
              const payload = await response.json();
              alert(payload.message || 'done');
              location.reload();
            }});
          }});
        </script>
      </body>
    </html>
    """


def build_app(notify_callback: NotifyCallback, bot: "Bot | None" = None) -> web.Application:
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

        return web.Response(status=204)

    async def dashboard_handler(request: web.Request) -> web.Response:
        page = await _build_dashboard_page(bot)
        return web.Response(text=page, content_type="text/html")

    async def streamer_api_handler(request: web.Request) -> web.Response:
        if bot is None:
            return web.json_response({"ok": False, "error": "bot unavailable"}, status=500)
        if request.method == "GET":
            streamers = await get_all_streamers(bot.db)  # type: ignore[attr-defined]
            return web.json_response(streamers)
        if request.method == "POST":
            payload = await request.json()
            twitch_user_id = str(payload.get("twitch_user_id", ""))
            guild_id = int(payload.get("guild_id", 0))
            fields: dict[str, object] = {}
            for key in ("discord_channel_id", "ping_role_id", "custom_message", "footer_message", "accent_color"):
                if key in payload:
                    value = payload[key]
                    if key in {"discord_channel_id", "ping_role_id", "accent_color"}:
                        value = int(value)
                    fields[key] = value
            if not twitch_user_id or not fields:
                return web.json_response({"ok": False, "error": "invalid payload"}, status=400)
            await update_streamer(bot.db, twitch_user_id, guild_id=guild_id, **fields)  # type: ignore[attr-defined]
            return web.json_response({"ok": True})
        return web.Response(status=405)

    async def music_api_handler(request: web.Request) -> web.Response:
        if bot is None:
            return web.json_response({"ok": False, "error": "bot unavailable"}, status=500)
        payload: list[dict[str, object]] = []
        for guild in bot.guilds:
            queue_cog = bot.get_cog("queue")
            if queue_cog is None:
                continue
            payload.append({"guild_id": guild.id, "name": guild.name, "state": queue_cog.get_state(guild.id)})  # type: ignore[attr-defined]
        return web.json_response(payload)

    async def music_action_handler(request: web.Request) -> web.Response:
        if bot is None:
            return web.json_response({"ok": False, "message": "bot unavailable"}, status=500)
        action = request.match_info.get("action", "")
        guild_id = int(request.query.get("guild_id", 0))
        if not guild_id:
            return web.json_response({"ok": False, "message": "missing guild_id"}, status=400)

        guild = bot.get_guild(guild_id)
        if guild is None:
            return web.json_response({"ok": False, "message": "guild not found"}, status=404)

        queue_cog = bot.get_cog("queue")
        if queue_cog is None:
            return web.json_response({"ok": False, "message": "queue system not loaded"}, status=500)

        if action == "skip":
            vc = guild.voice_client
            if vc is None or not isinstance(vc, discord.VoiceClient):
                return web.json_response({"ok": False, "message": "not connected"})
            queue_cog.skip(guild_id, vc)  # type: ignore[attr-defined]
            return web.json_response({"ok": True, "message": "skipped"})

        if action == "stop":
            queue_cog.clear(guild_id)  # type: ignore[attr-defined]
            vc = guild.voice_client
            if isinstance(vc, discord.VoiceClient):
                await vc.disconnect(force=True)
            return web.json_response({"ok": True, "message": "stopped"})

        if action == "queue":
            payload = await request.json()
            url = str(payload.get("url", ""))
            if not url:
                return web.json_response({"ok": False, "message": "missing url"}, status=400)
            music_cog = bot.get_cog("music")
            if music_cog is None:
                return web.json_response({"ok": False, "message": "music cog not loaded"}, status=500)
            ok, message = await music_cog.queue_from_url(guild_id, url)  # type: ignore[attr-defined]
            return web.json_response({"ok": ok, "message": message})

        return web.json_response({"ok": False, "message": "unknown action"}, status=400)

    app.router.add_post("/webhook/twitch", webhook_handler)
    app.router.add_get("/", dashboard_handler)
    app.router.add_route("*", "/api/streamers", streamer_api_handler)
    app.router.add_get("/api/music", music_api_handler)
    app.router.add_post("/api/music/{action}", music_action_handler)
    return app


class WebhookServer:
    """runs the eventsub listener and a tiny retro dashboard alongside the bot."""

    def __init__(
        self,
        notify_callback: NotifyCallback,
        host: str = "0.0.0.0",
        port: int = 8080,
        bot: "Bot | None" = None,
    ) -> None:
        self._app = build_app(notify_callback, bot=bot)
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        log.info("twitch webhook listener started on %s:%s", self._host, self._port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
