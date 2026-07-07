from __future__ import annotations

import asyncio
import hashlib
import os
from functools import partial
from typing import TYPE_CHECKING

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("music")

CACHE_DIR = "data/youtube_cache"


class MusicCog(commands.Cog, name="music"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._metadata_cache: dict[str, dict[str, str]] = {}

    def _cache_filename(self, url: str) -> str:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{url_hash}.opus")

    def _extract_metadata(self, url: str) -> dict[str, str] | None:
        ydl_opts = {"format": "bestaudio/best", "quiet": True, "no_warnings": True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            log.exception("failed to extract metadata for %s", url)
            return None
        if not info:
            return None
        return {
            "title": info.get("title", "unknown"),
            "uploader": info.get("uploader", "unknown"),
            "duration": str(info.get("duration", 0)),
            "thumbnail": info.get("thumbnail", ""),
            "url": url,
        }

    def _download_audio(self, url: str, cache_file: str) -> str | None:
        if os.path.exists(cache_file):
            return cache_file
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": cache_file.replace(".opus", ".%(ext)s"),
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "opus", "preferredquality": "192"}
            ],
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            log.exception("failed to download %s", url)
            return None
        return cache_file if os.path.exists(cache_file) else None

    async def get_video_metadata(self, url: str) -> dict[str, str] | None:
        if url in self._metadata_cache:
            return self._metadata_cache[url]
        loop = asyncio.get_running_loop()
        metadata = await loop.run_in_executor(None, self._extract_metadata, url)
        if metadata:
            self._metadata_cache[url] = metadata
        return metadata

    async def download_audio(self, url: str) -> str | None:
        cache_file = self._cache_filename(url)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._download_audio, url, cache_file))

    async def queue_from_url(self, guild_id: int, url: str, voice_channel: discord.abc.Connectable | None = None) -> tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return False, "guild not found"

        metadata = await self.get_video_metadata(url)
        if metadata is None:
            return False, "couldn't get video info"

        filepath = await self.download_audio(url)
        if filepath is None:
            return False, "couldn't download audio"

        queue_cog = self.bot.get_cog("queue")
        if queue_cog is None:
            return False, "queue system not loaded"

        queue_cog.add_to_queue(guild_id, filepath, metadata, True)  # type: ignore[attr-defined]

        voice_client = guild.voice_client
        if voice_client is None:
            if voice_channel is None:
                voice_channel = guild.voice_channels[0] if guild.voice_channels else None
            if voice_channel is None:
                return False, "no voice channel available"
            try:
                voice_client = await voice_channel.connect()  # type: ignore[union-attr]
            except Exception as exc:
                return False, f"couldn't connect: {exc}"

        if isinstance(voice_client, discord.VoiceClient):
            if not voice_client.is_playing():
                queue_cog.play_next(guild_id, voice_client)  # type: ignore[attr-defined]
            return True, f"added to queue: {metadata['title']}"
        return False, "not connected properly"

    @app_commands.command(name="play", description="play audio from a youtube url")
    @app_commands.describe(url="youtube video url")
    async def play(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer()

        if interaction.guild is None:
            await interaction.followup.send("only works in servers")
            return

        member = interaction.guild.get_member(interaction.user.id)
        if member is None or member.voice is None or member.voice.channel is None:
            await interaction.followup.send("join a voice channel first")
            return

        ok, message = await self.queue_from_url(interaction.guild.id, url, member.voice.channel)
        if ok:
            await interaction.followup.send(message)
        else:
            await interaction.followup.send(message)

    @app_commands.command(name="skip", description="skip the current track")
    async def skip(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.voice_client is None:
            await interaction.response.send_message("not playing anything", ephemeral=True)
            return
        queue_cog = self.bot.get_cog("queue")
        vc = interaction.guild.voice_client
        if queue_cog is not None and isinstance(vc, discord.VoiceClient) and queue_cog.skip(interaction.guild.id, vc):  # type: ignore[attr-defined]
            await interaction.response.send_message("skipped")
        else:
            await interaction.response.send_message("nothing to skip", ephemeral=True)

    @app_commands.command(name="np", description="show the current track")
    async def now_playing(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("only works in servers", ephemeral=True)
            return
        queue_cog = self.bot.get_cog("queue")
        if queue_cog is None:
            await interaction.response.send_message("queue system not loaded", ephemeral=True)
            return
        state = queue_cog.get_state(interaction.guild.id)  # type: ignore[attr-defined]
        current = state["current"]
        if not current:
            await interaction.response.send_message("nothing is playing right now", ephemeral=True)
            return
        metadata = current["metadata"]
        title = metadata.get("title", "unknown")
        uploader = metadata.get("uploader", "unknown")
        await interaction.response.send_message(f"now playing: {title} — {uploader}")

    @app_commands.command(name="queue", description="show the current music queue")
    async def queue_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("only works in servers", ephemeral=True)
            return
        queue_cog = self.bot.get_cog("queue")
        if queue_cog is None:
            await interaction.response.send_message("queue system not loaded", ephemeral=True)
            return
        state = queue_cog.get_state(interaction.guild.id)  # type: ignore[attr-defined]
        current = state["current"]
        queue = state["queue"]
        lines: list[str] = []
        if current:
            metadata = current["metadata"]
            lines.append(f"now playing: {metadata.get('title', 'unknown')}")
        else:
            lines.append("now playing: nothing")
        if queue:
            for index, item in enumerate(queue[:10], start=1):
                metadata = item["metadata"]
                lines.append(f"{index}. {metadata.get('title', 'unknown')}")
            if len(queue) > 10:
                lines.append(f"...and {len(queue) - 10} more")
        else:
            lines.append("queue is empty")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="stop", description="stop playback, clear the queue, and disconnect")
    async def stop(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        queue_cog = self.bot.get_cog("queue")
        if queue_cog is not None:
            queue_cog.clear(interaction.guild.id)  # type: ignore[attr-defined]
        vc = interaction.guild.voice_client
        if isinstance(vc, discord.VoiceClient):
            await vc.disconnect(force=True)
        await interaction.response.send_message("stopped and disconnected")


async def setup(bot: "Bot") -> None:
    await bot.add_cog(MusicCog(bot))
