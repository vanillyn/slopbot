from __future__ import annotations

import random
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.data.config import GuildConfig
from src.utils.ui import BaseLayout

if TYPE_CHECKING:
    from src.bot import Bot


def _fmt(template: str, member: discord.Member) -> str:
    return (
        template.replace("{user}", str(member))
        .replace("{mention}", member.mention)
        .replace("{server}", member.guild.name)
    )


class GreetingsCog(commands.Cog, name="greetings"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        cfg = await GuildConfig.load(self.bot.db, member.guild.id)
        if not cfg.dashboard.join_channel or not cfg.dashboard.join_messages:
            return
        channel = member.guild.get_channel(cfg.dashboard.join_channel)
        if not isinstance(channel, discord.TextChannel):
            return
        text = _fmt(random.choice(cfg.dashboard.join_messages), member)
        layout = BaseLayout()
        layout.add_container(discord.ui.TextDisplay(text), accent_color=0x57F287)
        try:
            await channel.send(view=layout)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        cfg = await GuildConfig.load(self.bot.db, member.guild.id)
        if not cfg.dashboard.leave_channel or not cfg.dashboard.leave_messages:
            return
        channel = member.guild.get_channel(cfg.dashboard.leave_channel)
        if not isinstance(channel, discord.TextChannel):
            return
        text = _fmt(random.choice(cfg.dashboard.leave_messages), member)
        layout = BaseLayout()
        layout.add_container(discord.ui.TextDisplay(text), accent_color=0xED4245)
        try:
            await channel.send(view=layout)
        except discord.HTTPException:
            pass


async def setup(bot: "Bot") -> None:
    await bot.add_cog(GreetingsCog(bot))
