from __future__ import annotations

import asyncio

from aiohttp import web

from src.bot import Bot
from src.config import BotConfig
from src.web.server import DashboardServer


def test_dashboard_server_routes_exist(monkeypatch) -> None:
    config = BotConfig()
    bot = Bot(config)
    server = DashboardServer(bot)
    assert isinstance(server.app, web.Application)
    routes = {route.resource.canonical for route in server.app.router.routes()}
    assert "/" in routes
    assert "/api/guilds" in routes
