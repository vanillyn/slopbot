from __future__ import annotations

import time

import discord

from src.data.db import Database


async def lock_channels(
    db: Database,
    guild: discord.Guild,
    channels: list[discord.TextChannel],
    roles: list[discord.Role],
    *,
    reason: str,
) -> list[discord.TextChannel]:
    """sets send_messages=False for every role on every channel, saving
    whatever was there before so it can be restored exactly later."""
    locked: list[discord.TextChannel] = []
    now = int(time.time())
    for channel in channels:
        changed = False
        for role in roles:
            prior = channel.overwrites_for(role).send_messages
            try:
                overwrite = channel.overwrites_for(role)
                overwrite.send_messages = False
                await channel.set_permissions(role, overwrite=overwrite, reason=reason)
            except discord.HTTPException:
                continue
            await db.execute(
                "insert into channel_lock_state"
                " (guild_id, channel_id, role_id, prior_send_messages, locked_at)"
                " values (?, ?, ?, ?, ?)"
                " on conflict (guild_id, channel_id, role_id) do update set"
                " prior_send_messages = excluded.prior_send_messages, locked_at = excluded.locked_at",
                (guild.id, channel.id, role.id, prior, now),
            )
            changed = True
        if changed:
            locked.append(channel)
    return locked


async def unlock_channels(
    db: Database,
    guild: discord.Guild,
    channels: list[discord.TextChannel],
    roles: list[discord.Role],
) -> list[discord.TextChannel]:
    """restores exactly whatever send_messages value each role had on each
    channel before the lock, instead of blindly clearing the override."""
    unlocked: list[discord.TextChannel] = []
    for channel in channels:
        changed = False
        for role in roles:
            row = await db.fetchone(
                "select prior_send_messages from channel_lock_state"
                " where guild_id = ? and channel_id = ? and role_id = ?",
                (guild.id, channel.id, role.id),
            )
            if row is None:
                continue
            prior = row[0]
            try:
                overwrite = channel.overwrites_for(role)
                overwrite.send_messages = None if prior is None else bool(prior)
                await channel.set_permissions(
                    role, overwrite=overwrite, reason="lockdown lifted"
                )
            except discord.HTTPException:
                continue
            await db.execute(
                "delete from channel_lock_state"
                " where guild_id = ? and channel_id = ? and role_id = ?",
                (guild.id, channel.id, role.id),
            )
            changed = True
        if changed:
            unlocked.append(channel)
    return unlocked
