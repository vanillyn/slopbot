from __future__ import annotations

import discord

from src.data.db import Database
from src.cogs.moderation.infractions import Infraction
from src.utils.ui import BaseLayout
from src.utils.logger import get_logger

log = get_logger("moderation.logging")

_COLORS = {
    "warn": 0xFEE75C,
    "kick": 0xF57C00,
    "ban": 0xED4245,
    "mute": 0x5865F2,
    "slowmode": 0x5865F2,
    "shutdown": 0xED4245,
}


async def log_infraction(db: Database, guild: discord.Guild, infraction: Infraction) -> None:
    channel = guild.get_channel(1523774868158414848)
    if not isinstance(channel, discord.TextChannel):
        return

    moderator = guild.get_member(infraction.moderator_id)
    target = guild.get_member(infraction.target_id)
    lines = [
        f"**{infraction.infraction_type}** — case `{infraction.case_str}`",
        f"**target:** {target or infraction.target_name} (`{infraction.target_id}`)",
        f"**moderator:** {moderator or infraction.moderator_id}",
        f"**reason:** {infraction.reason}",
    ]
    if infraction.duration:
        lines.append(f"**duration:** {infraction.duration}s")

    layout = BaseLayout()
    layout.add_container(
        discord.ui.TextDisplay("\n".join(lines)),
        accent_color=_COLORS.get(infraction.infraction_type, 0x5865F2),
    )
    try:
        await channel.send(view=layout)
    except discord.HTTPException as e:
        log.error("failed to send mod log: %s", e)
