from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.cogs.radio.db import (
    add_track,
    get_state,
    list_enabled_guilds,
    list_tracks,
    remove_track,
    set_state,
)
from src.utils.logger import get_logger
from src.utils.ui import BaseLayout

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("radio")


class RadioCog(commands.Cog, name="radio"):
    """a per-guild endless shuffle of an admin-curated playlist. separate from
    the regular music queue on purpose — /music play is a one-off request,
    /radio is a background loop that just keeps going until stopped."""

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def cog_unload(self) -> None:
        for task in self._tasks.values():
            task.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild_id in await list_enabled_guilds(self.bot.db):
            self._start_task(guild_id)

    async def _run_loop(self, guild_id: int) -> None:
        music_cog = self.bot.get_cog("music")
        if music_cog is None:
            log.warning("radio loop for guild %s ended — music cog not loaded", guild_id)
            return
        try:
            while True:
                state = await get_state(self.bot.db, guild_id)
                if not state["enabled"]:
                    return
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    return
                tracks = await list_tracks(self.bot.db, guild_id)
                if not tracks:
                    log.info("radio playlist empty for guild %s, stopping", guild_id)
                    await set_state(self.bot.db, guild_id, enabled=False, voice_channel_id=0)
                    return
                track = random.choice(tracks) if state["shuffle"] else tracks[0]

                voice_channel = guild.get_channel(state["voice_channel_id"])
                if not isinstance(voice_channel, discord.VoiceChannel):
                    log.warning("radio voice channel missing for guild %s, stopping", guild_id)
                    await set_state(self.bot.db, guild_id, enabled=False, voice_channel_id=0)
                    return

                voice_client = guild.voice_client
                if voice_client is None or not isinstance(voice_client, discord.VoiceClient):
                    try:
                        voice_client = await voice_channel.connect()
                    except discord.HTTPException:
                        await asyncio.sleep(10)
                        continue
                elif voice_client.channel.id != voice_channel.id:
                    await voice_client.move_to(voice_channel)

                metadata = await music_cog.get_video_metadata(track["url"])  # type: ignore[attr-defined]
                filepath = await music_cog.download_audio(track["url"])  # type: ignore[attr-defined]
                if metadata is None or filepath is None:
                    log.warning("radio couldn't load track %s, skipping", track["url"])
                    await asyncio.sleep(2)
                    continue

                finished = asyncio.Event()

                def _after(error: Exception | None) -> None:
                    if error is not None:
                        log.error("radio playback error in guild %s: %s", guild_id, error)
                    self.bot.loop.call_soon_threadsafe(finished.set)

                try:
                    source = discord.FFmpegOpusAudio(filepath)
                    voice_client.play(source, after=_after)
                except discord.ClientException:
                    await asyncio.sleep(2)
                    continue

                await finished.wait()
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(guild_id, None)

    def _start_task(self, guild_id: int) -> None:
        existing = self._tasks.get(guild_id)
        if existing is not None and not existing.done():
            return
        self._tasks[guild_id] = asyncio.create_task(self._run_loop(guild_id))

    radio = app_commands.Group(
        name="radio",
        description="24/7 playlist radio",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @radio.command(name="add", description="add a video to the radio playlist")
    @app_commands.describe(url="youtube video url to add")
    async def add(self, interaction: discord.Interaction, url: str) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        music_cog = self.bot.get_cog("music")
        title = url
        if music_cog is not None:
            metadata = await music_cog.get_video_metadata(url)  # type: ignore[attr-defined]
            if metadata is not None:
                title = metadata.get("title", url)
        track_id = await add_track(self.bot.db, interaction.guild.id, url, title, interaction.user.id)
        await interaction.followup.send(f"added to radio playlist (#{track_id}): {title}", ephemeral=True)

    @radio.command(name="remove", description="remove a track from the radio playlist")
    @app_commands.describe(track_id="track id, from /radio list")
    async def remove(self, interaction: discord.Interaction, track_id: int) -> None:
        if interaction.guild is None:
            return
        await remove_track(self.bot.db, interaction.guild.id, track_id)
        await interaction.response.send_message(f"removed track #{track_id}", ephemeral=True)

    @radio.command(name="list", description="show the radio playlist")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        tracks = await list_tracks(self.bot.db, interaction.guild.id)
        if not tracks:
            await interaction.response.send_message("radio playlist is empty", ephemeral=True)
            return
        lines = [f"`#{t['id']}` {t['title']}" for t in tracks[:25]]
        layout = BaseLayout()
        layout.add_container(
            discord.ui.TextDisplay("**radio playlist**\n" + "\n".join(lines)),
            accent_color=0x5865F2,
        )
        await interaction.response.send_message(view=layout, ephemeral=True)

    @radio.command(name="start", description="start the 24/7 radio in a voice channel")
    @app_commands.describe(
        channel="voice channel to play in (defaults to your current channel)",
        shuffle="pick tracks in random order (default) instead of playlist order",
    )
    async def start(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel | None = None,
        shuffle: bool = True,
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
        tracks = await list_tracks(self.bot.db, guild.id)
        if not tracks:
            await interaction.response.send_message(
                "the radio playlist is empty — add tracks with `/radio add` first", ephemeral=True
            )
            return
        await set_state(self.bot.db, guild.id, enabled=True, voice_channel_id=target.id, shuffle=shuffle)
        self._start_task(guild.id)
        await interaction.response.send_message(f"radio started in {target.mention}")

    @radio.command(name="stop", description="stop the 24/7 radio and disconnect")
    async def stop(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        await set_state(self.bot.db, guild.id, enabled=False, voice_channel_id=0)
        task = self._tasks.get(guild.id)
        if task is not None:
            task.cancel()
        vc = guild.voice_client
        if isinstance(vc, discord.VoiceClient):
            await vc.disconnect(force=True)
        await interaction.response.send_message("radio stopped")


async def setup(bot: "Bot") -> None:
    await bot.add_cog(RadioCog(bot))
