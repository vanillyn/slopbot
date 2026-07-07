from __future__ import annotations

import discord
from discord.ext import commands

from src.config import BotConfig
from src.data.db import Database
from src.cogs.twitch.api import TwitchClient
from src.utils.logger import get_logger

log = get_logger("bot")

INITIAL_EXTENSIONS = (
    "src.cogs.moderation.cog",
    "src.cogs.antiraid.cog",
    "src.cogs.ticketing.cog",
    "src.cogs.twitch.cog",
    "src.cogs.music.queue",
    "src.cogs.music.cog",
    "src.cogs.dashboard.cog",
)


class Bot(commands.Bot):
    def __init__(self, config: BotConfig) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=config.command_prefix, intents=intents)
        self.config = config
        self.db = Database(config.db_path)
        self.twitch = TwitchClient()

    async def setup_hook(self) -> None:
        await self.db.connect()

        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("loaded extension %s", ext)
            except Exception:
                # a single cog failing to load (e.g. music/twitch deps missing)
                # must never take down moderation or anti-raid.
                log.exception("failed to load extension %s — continuing without it", ext)

        try:
            synced = await self.tree.sync()
            log.info("synced %d application command(s)", len(synced))
        except discord.HTTPException:
            log.exception("failed to sync application commands")

    async def close(self) -> None:
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("logged in as %s (%s)", self.user, self.user.id if self.user else "?")
