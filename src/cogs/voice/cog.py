from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from src.bot import Bot


class VoiceCog(commands.Cog, name="voice"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot

    vc = app_commands.Group(name="vc", description="voice channel connection")

    @vc.command(name="join", description="join a voice channel")
    @app_commands.describe(channel="voice channel to join (defaults to your current channel)")
    async def join(
        self, interaction: discord.Interaction, channel: discord.VoiceChannel | None = None
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        member = guild.get_member(interaction.user.id)
        target = channel
        if target is None and member is not None and member.voice is not None:
            target = member.voice.channel  # type: ignore[assignment]
        if target is None:
            await interaction.response.send_message(
                "join a voice channel or specify one", ephemeral=True
            )
            return

        voice_client = guild.voice_client
        try:
            if voice_client is None:
                await target.connect()
            elif isinstance(voice_client, discord.VoiceClient):
                await voice_client.move_to(target)
        except discord.ClientException as e:
            await interaction.response.send_message(f"couldn't join: {e}", ephemeral=True)
            return
        await interaction.response.send_message(f"joined {target.mention}")

    @vc.command(name="leave", description="leave the current voice channel")
    async def leave(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        voice_client = guild.voice_client
        if voice_client is None or not isinstance(voice_client, discord.VoiceClient):
            await interaction.response.send_message("not connected to a voice channel", ephemeral=True)
            return
        await voice_client.disconnect(force=True)
        await interaction.response.send_message("left the voice channel")


async def setup(bot: "Bot") -> None:
    await bot.add_cog(VoiceCog(bot))
