from __future__ import annotations

import os
from typing import TYPE_CHECKING

import aiohttp
import discord
from aiohttp import web
from discord import ui

from src.config import BotConfig
from src.data.button_containers import (
    delete_container,
    get_containers,
    save_container,
)
from src.data.config import (
    get_all_config,
    set_config,
    delete_config,
    get_moderation_config,
    set_moderation_config,
)
from src.cogs.ticketing.cog import OpenTicketButton
from src.cogs.ticketing.db import create_panel, get_ticket_panels, set_panel_message
from src.utils.logger import get_logger
from src.utils.ui import BaseLayout

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("web.server")

_DISCORD_API = "https://discord.com/api/v10"
_ADMIN_BIT = 0x8


def _auth_header(request: web.Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return auth[7:].strip() or None


async def _fetch_discord_json(session: aiohttp.ClientSession, url: str, token: str) -> dict[str, object] | None:
    async with session.get(url, headers={"Authorization": f"Bearer {token}"}) as resp:
        if resp.status != 200:
            return None
        return await resp.json()


def _is_admin_guild(guild_data: dict[str, object]) -> bool:
    raw = str(guild_data.get("permissions", "0"))
    try:
        return bool(int(raw) & _ADMIN_BIT) or bool(guild_data.get("owner", False))
    except ValueError:
        return bool(guild_data.get("owner", False))


class DashboardServer:
    """the bot's one and only web server. serves the static dashboard frontend
    (src/web/static/) plus a JSON API, guarded by discord oauth (implicit
    grant — the frontend gets a user access token directly, no client secret
    involved on the frontend side).

    this can also be run headless: if you host the frontend elsewhere (e.g.
    GitHub Pages or Cloudflare Pages) and just want the API, set
    DASHBOARD_ORIGIN to that frontend's origin so CORS allows it through and
    point the frontend's `window.COCO_API_BASE` at wherever this server is
    reachable (see src/web/static/index.html).
    """

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self.config = bot.config
        self.app = web.Application()
        self.app["bot"] = bot
        self.app["session"] = None
        self.origin = self.config.dashboard_origin
        self._runner: web.AppRunner | None = None

        self.app.on_startup.append(self._on_startup)
        self.app.on_cleanup.append(self._on_cleanup)
        self.app.middlewares.append(self._cors_middleware)

        self._register_routes()

    async def _on_startup(self, app: web.Application) -> None:
        app["session"] = aiohttp.ClientSession()

    async def _on_cleanup(self, app: web.Application) -> None:
        session: aiohttp.ClientSession | None = app.get("session")
        if session is not None and not session.closed:
            await session.close()

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler: web.Handler) -> web.StreamResponse:
        if request.method == "OPTIONS":
            response: web.StreamResponse = web.Response(status=204)
        else:
            response = await handler(request)
        response.headers.update(
            {
                "Access-Control-Allow-Origin": self.origin,
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            }
        )
        return response

    def _register_routes(self) -> None:
        self.app.router.add_get("/", self._serve_index)
        self.app.router.add_get("/static/{filename}", self._serve_static)
        self.app.router.add_get("/api/guilds", self._handle_guilds)
        self.app.router.add_get("/api/guild/{guild_id}/config", self._handle_get_config)
        self.app.router.add_post("/api/guild/{guild_id}/config", self._handle_set_config)
        self.app.router.add_get("/api/guild/{guild_id}/moderation", self._handle_get_moderation)
        self.app.router.add_post("/api/guild/{guild_id}/moderation", self._handle_set_moderation)
        self.app.router.add_get("/api/guild/{guild_id}/channels", self._handle_get_channels)
        self.app.router.add_get("/api/guild/{guild_id}/roles", self._handle_get_roles)
        self.app.router.add_get("/api/guild/{guild_id}/ticket_panels", self._handle_get_ticket_panels)
        self.app.router.add_post("/api/guild/{guild_id}/ticket_panels", self._handle_create_ticket_panel)
        self.app.router.add_get("/api/guild/{guild_id}/containers", self._handle_get_containers)
        self.app.router.add_post("/api/guild/{guild_id}/containers", self._handle_save_container)
        self.app.router.add_delete("/api/guild/{guild_id}/containers/{name}", self._handle_delete_container)
        self.app.router.add_get("/api/guild/{guild_id}/state", self._handle_get_state)
        self.app.router.add_post("/api/guild/{guild_id}/actions/{action}", self._handle_action)
        self.app.router.add_get("/api/config", self._handle_public_config)

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.dashboard_host, self.config.dashboard_port)
        await site.start()
        log.info("dashboard available at http://%s:%s", self.config.dashboard_host, self.config.dashboard_port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _authenticated_user(self, request: web.Request) -> tuple[str, str] | web.Response:
        token = _auth_header(request)
        if not token:
            return web.json_response({"error": "unauthorized"}, status=401)
        session: aiohttp.ClientSession = request.app["session"]
        user = await _fetch_discord_json(session, f"{_DISCORD_API}/users/@me", token)
        if user is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        return token, str(user.get("id", ""))

    async def _check_guild_access(self, token: str, user_id: str, guild_id_str: str) -> web.Response | None:
        guild = self.bot.get_guild(int(guild_id_str))
        if guild is None:
            return web.json_response({"error": "guild not found"}, status=404)
        if user_id == str(guild.owner_id):
            return None
        session: aiohttp.ClientSession = self.app["session"]
        guilds = await _fetch_discord_json(session, f"{_DISCORD_API}/users/@me/guilds", token)
        if guilds is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not any(str(g.get("id")) == guild_id_str and _is_admin_guild(g) for g in guilds):
            return web.json_response({"error": "forbidden"}, status=403)
        return None

    async def _handle_public_config(self, request: web.Request) -> web.Response:
        """unauthenticated — tells the frontend which discord client id to use for
        the oauth redirect, so it doesn't need to be hardcoded in static JS."""
        return web.json_response({"discord_client_id": self.config.discord_client_id})

    async def _handle_guilds(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        session: aiohttp.ClientSession = request.app["session"]
        guilds = await _fetch_discord_json(session, f"{_DISCORD_API}/users/@me/guilds", token)
        if guilds is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        bot_guilds = {str(g.id) for g in self.bot.guilds}
        out: list[dict[str, object]] = []
        for guild_data in guilds:
            guild_id = str(guild_data.get("id", ""))
            if guild_id not in bot_guilds:
                continue
            if not _is_admin_guild(guild_data):
                continue
            out.append({
                "id": guild_id,
                "name": str(guild_data.get("name", "")),
                "icon": guild_data.get("icon"),
            })
        return web.json_response(out)

    async def _handle_get_config(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        config = await get_all_config(self.bot.db, guild_id)
        return web.json_response(config)

    async def _handle_set_config(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        payload = await request.json()
        for key, value in payload.items():
            if value is None or value == "":
                await delete_config(self.bot.db, guild_id, key)
            else:
                await set_config(self.bot.db, guild_id, key, value)
        return web.json_response({"ok": True})

    async def _handle_get_moderation(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        config = await get_moderation_config(self.bot.db, int(guild_id_str))
        return web.json_response(config)

    async def _handle_set_moderation(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        payload = await request.json()
        await set_moderation_config(self.bot.db, int(guild_id_str), payload)
        return web.json_response({"ok": True})

    async def _handle_get_channels(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild = self.bot.get_guild(int(guild_id_str))
        if guild is None:
            return web.json_response({"error": "guild not found"}, status=404)
        channels = []
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                channels.append({"id": str(channel.id), "name": channel.name, "type": "text"})
            elif isinstance(channel, discord.CategoryChannel):
                channels.append({"id": str(channel.id), "name": channel.name, "type": "category"})
        return web.json_response(channels)

    async def _handle_get_roles(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild = self.bot.get_guild(int(guild_id_str))
        if guild is None:
            return web.json_response({"error": "guild not found"}, status=404)
        roles = [
            {"id": str(role.id), "name": role.name, "color": f"#{role.color.value:06x}" if role.color.value else "#99aab5"}
            for role in reversed(guild.roles)
            if not role.is_default() and not role.managed
        ]
        return web.json_response(roles)

    async def _handle_get_state(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        queue_cog = self.bot.get_cog("queue")
        if queue_cog is None:
            return web.json_response({"ok": False, "error": "queue missing"}, status=500)
        state = queue_cog.get_state(guild_id)  # type: ignore[attr-defined]
        return web.json_response({"ok": True, "state": state})

    async def _handle_action(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        action = request.match_info["action"]
        payload = await request.json()
        queue_cog = self.bot.get_cog("queue")
        music_cog = self.bot.get_cog("music")
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return web.json_response({"error": "guild not found"}, status=404)

        if action == "play":
            url = str(payload.get("url", "")).strip()
            if not url:
                return web.json_response({"error": "missing url"}, status=400)
            if music_cog is None:
                return web.json_response({"error": "music disabled"}, status=500)
            voice_channel_id = int(payload.get("voice_channel_id", 0))
            voice_channel = guild.get_channel(voice_channel_id) if voice_channel_id else None
            ok, message = await music_cog.queue_from_url(guild_id, url, voice_channel if isinstance(voice_channel, discord.VoiceChannel) else None)  # type: ignore[attr-defined]
            return web.json_response({"ok": ok, "message": message})

        if action == "pause":
            vc = guild.voice_client
            if vc is None or not isinstance(vc, discord.VoiceClient):
                return web.json_response({"error": "not connected"}, status=400)
            if not vc.is_playing():
                return web.json_response({"error": "not playing"}, status=400)
            vc.pause()
            return web.json_response({"ok": True, "message": "paused"})

        if action == "resume":
            vc = guild.voice_client
            if vc is None or not isinstance(vc, discord.VoiceClient):
                return web.json_response({"error": "not connected"}, status=400)
            if not vc.is_paused():
                return web.json_response({"error": "not paused"}, status=400)
            vc.resume()
            return web.json_response({"ok": True, "message": "resumed"})

        if action in {"skip", "stop"}:
            if queue_cog is None:
                return web.json_response({"error": "queue missing"}, status=500)
            vc = guild.voice_client
            if action == "skip":
                if vc is None or not isinstance(vc, discord.VoiceClient) or not vc.is_playing():
                    return web.json_response({"error": "not playing"}, status=400)
                queue_cog.skip(guild_id, vc)  # type: ignore[attr-defined]
                return web.json_response({"ok": True, "message": "skipped"})
            queue_cog.clear(guild_id)  # type: ignore[attr-defined]
            if isinstance(vc, discord.VoiceClient):
                await vc.disconnect(force=True)
            return web.json_response({"ok": True, "message": "stopped"})

        if action == "open_twitch":
            twitch_url = str(payload.get("url", "")).strip()
            if not twitch_url:
                return web.json_response({"error": "missing url"}, status=400)
            return web.json_response({"ok": True, "url": twitch_url})

        return web.json_response({"error": "unknown action"}, status=400)

    async def _handle_get_ticket_panels(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        panels = await get_ticket_panels(self.bot.db, guild_id)
        return web.json_response(panels)

    async def _handle_create_ticket_panel(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        payload = await request.json()
        channel_id = int(payload.get("channel_id", 0))
        if channel_id <= 0:
            return web.json_response({"error": "missing channel_id"}, status=400)
        title = str(payload.get("title", "support")).strip() or "support"
        description = str(payload.get("description", "click below to open a ticket")).strip() or "click below to open a ticket"
        category_id = int(payload.get("category_id", 0)) if payload.get("category_id") else 0
        staff_role_id = int(payload.get("staff_role_id", 0)) if payload.get("staff_role_id") else 0

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return web.json_response({"error": "guild not found"}, status=404)

        channel = guild.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            return web.json_response({"error": "channel not found or not a text channel"}, status=404)

        panel_id = await create_panel(
            self.bot.db,
            guild_id,
            channel_id,
            category_id,
            staff_role_id,
            title,
            description,
        )
        layout = BaseLayout()
        layout.add_container(ui.TextDisplay(f"# {title}\n{description}"), accent_color=0x5865F2)
        layout.add_item(ui.ActionRow(OpenTicketButton(panel_id)))

        try:
            msg = await channel.send(view=layout)
        except discord.HTTPException as exc:
            return web.json_response({"error": f"failed to send ticket panel message: {exc}"}, status=500)

        await set_panel_message(self.bot.db, panel_id, msg.id)
        return web.json_response({"ok": True, "panel_id": panel_id, "message_id": msg.id})

    async def _handle_get_containers(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        containers = await get_containers(self.bot.db, guild_id)
        return web.json_response(containers)

    async def _handle_save_container(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        body = await request.json()
        name = str(body.get("name", "")).strip()
        items = body.get("items")
        accent_color = body.get("accent_color")
        if not name:
            return web.json_response({"error": "missing container name"}, status=400)
        if not isinstance(items, list):
            return web.json_response({"error": "items must be a list"}, status=400)

        if accent_color is not None:
            try:
                accent_color = int(accent_color)
            except (TypeError, ValueError):
                accent_color = None

        await save_container(
            self.bot.db,
            guild_id,
            name,
            int(user_id),
            items,
            accent_color,
        )
        return web.json_response({"ok": True})

    async def _handle_delete_container(self, request: web.Request) -> web.Response:
        auth = await self._authenticated_user(request)
        if isinstance(auth, web.Response):
            return auth
        token, user_id = auth
        guild_id_str = request.match_info["guild_id"]
        denied = await self._check_guild_access(token, user_id, guild_id_str)
        if denied:
            return denied
        guild_id = int(guild_id_str)
        name = request.match_info["name"]
        await delete_container(self.bot.db, guild_id, name)
        return web.json_response({"ok": True})

    async def _serve_index(self, request: web.Request) -> web.Response:
        path = os.path.join(os.path.dirname(__file__), "static", "index.html")
        with open(path, "r", encoding="utf-8") as file:
            return web.Response(text=file.read(), content_type="text/html")

    async def _serve_static(self, request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        path = os.path.join(os.path.dirname(__file__), "static", filename)
        if not os.path.exists(path) or ".." in filename:
            raise web.HTTPNotFound()
        content_type = "text/plain"
        if filename.endswith(".js"):
            content_type = "application/javascript"
        elif filename.endswith(".css"):
            content_type = "text/css"
        with open(path, "r", encoding="utf-8") as file:
            return web.Response(text=file.read(), content_type=content_type)
