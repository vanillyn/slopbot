from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("music.queue")


@dataclass
class Track:
    filepath: str
    metadata: dict[str, str]
    requested: bool = True


class QueueCog(commands.Cog, name="queue"):
    """holds the per-guild playback queue and current track state."""

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self._queues: dict[int, deque[Track]] = defaultdict(deque)
        self._current: dict[int, Track | None] = {}

    def add_to_queue(
        self, guild_id: int, filepath: str, metadata: dict[str, str], requested: bool = True
    ) -> Track:
        track = Track(filepath, metadata, requested)
        self._queues[guild_id].append(track)
        return track

    def peek(self, guild_id: int) -> list[Track]:
        return list(self._queues[guild_id])

    def get_current_track(self, guild_id: int) -> Track | None:
        return self._current.get(guild_id)

    def get_state(self, guild_id: int) -> dict[str, object]:
        current = self.get_current_track(guild_id)
        return {
            "current": None if current is None else {
                "filepath": current.filepath,
                "metadata": current.metadata,
                "requested": current.requested,
            },
            "queue": [
                {
                    "filepath": track.filepath,
                    "metadata": track.metadata,
                    "requested": track.requested,
                }
                for track in self.peek(guild_id)
            ],
        }

    def play_next(self, guild_id: int, voice_client: discord.VoiceClient) -> None:
        queue = self._queues[guild_id]
        if not queue:
            self._current[guild_id] = None
            return
        track = queue.popleft()
        self._current[guild_id] = track
        try:
            source = discord.FFmpegOpusAudio(track.filepath)
        except Exception:
            log.exception("failed to build audio source for %s", track.filepath)
            self._current[guild_id] = None
            self.play_next(guild_id, voice_client)
            return

        def _after(error: Exception | None) -> None:
            if error is not None:
                log.error("playback error in guild %s: %s", guild_id, error)
            self._current[guild_id] = None
            self.play_next(guild_id, voice_client)

        voice_client.play(source, after=_after)

    def skip(self, guild_id: int, voice_client: discord.VoiceClient) -> bool:
        if not voice_client.is_playing():
            return False
        voice_client.stop()
        self._current[guild_id] = None
        return True

    def clear(self, guild_id: int) -> None:
        self._queues[guild_id].clear()
        self._current[guild_id] = None


async def setup(bot: "Bot") -> None:
    await bot.add_cog(QueueCog(bot))
