from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.logger import get_logger

log = get_logger("help")


class HelpCog(commands.Cog, name="help"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="show available bot commands")
    async def help(self, interaction: discord.Interaction) -> None:
        commands_list = []
        for command in sorted(self.bot.tree.walk_commands(), key=lambda c: c.name):
            if isinstance(command, app_commands.Group):
                commands_list.append(f"/{command.name} — {command.description}")
                for sub in command.commands:
                    commands_list.append(f"/{command.name} {sub.name} — {sub.description}")
            else:
                commands_list.append(f"/{command.name} — {command.description}")

        if not commands_list:
            await interaction.response.send_message("no commands available", ephemeral=True)
            return

        text = "**available commands**\n" + "\n".join(commands_list)
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
