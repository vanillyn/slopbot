from __future__ import annotations

import os
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("dashboard")


class DashboardCog(commands.Cog, name="dashboard"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self._runner: discord.app_commands.CommandTree | None = None
        self._server: object | None = None

    async def cog_load(self) -> None:
        from src.web.server import DashboardServer

        config = self.bot.config
        if not config.dashboard_enabled:
            log.info("dashboard disabled by configuration")
            return

        self._server = DashboardServer(self.bot)
        await self._server.start()
        log.info("dashboard server started")

    async def cog_unload(self) -> None:
        if self._server is not None:
            await self._server.stop()
            log.info("dashboard server stopped")


async def setup(bot: "Bot") -> None:
    await bot.add_cog(DashboardCog(bot))
