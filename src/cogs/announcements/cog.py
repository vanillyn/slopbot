from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.data.config import GuildConfig
from src.utils.ui import BaseLayout

if TYPE_CHECKING:
    from src.bot import Bot


class AnnouncementsCog(commands.Cog, name="announcements"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot

    @app_commands.command(name="announce", description="post an announcement")
    @app_commands.describe(
        message="the announcement text",
        channel="channel to post in (defaults to the configured announcement channel)",
        ping="ping the configured announcement role",
        title="optional bold title shown above the message",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def announce(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: discord.TextChannel | None = None,
        ping: bool = False,
        title: str | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        cfg = await GuildConfig.load(self.bot.db, guild.id)

        target = channel
        if target is None and cfg.dashboard.announcement_channel:
            configured = guild.get_channel(cfg.dashboard.announcement_channel)
            if isinstance(configured, discord.TextChannel):
                target = configured
        if target is None:
            await interaction.response.send_message(
                "no channel specified and no announcement channel configured", ephemeral=True
            )
            return

        content = f"# {title}\n{message}" if title else message
        mention = ""
        if ping and cfg.dashboard.announcement_role:
            role = guild.get_role(cfg.dashboard.announcement_role)
            if role is not None:
                mention = role.mention + "\n"

        layout = BaseLayout()
        layout.add_container(discord.ui.TextDisplay(content), accent_color=0x5865F2)
        try:
            await target.send(content=mention or None, view=layout)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"failed to post: {e}", ephemeral=True)
            return
        await interaction.response.send_message(f"posted in {target.mention}", ephemeral=True)


async def setup(bot: "Bot") -> None:
    await bot.add_cog(AnnouncementsCog(bot))
