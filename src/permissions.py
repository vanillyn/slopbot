from __future__ import annotations

import discord

from src.data.db import Database


async def grant(db: Database, guild_id: int, role_id: int, node: str) -> None:
    await db.execute(
        "insert or ignore into permission_overrides (guild_id, role_id, node)"
        " values (?, ?, ?)",
        (guild_id, role_id, node),
    )


async def revoke(db: Database, guild_id: int, role_id: int, node: str) -> None:
    await db.execute(
        "delete from permission_overrides where guild_id = ? and role_id = ? and node = ?",
        (guild_id, role_id, node),
    )


async def get_role_nodes(db: Database, guild_id: int, role_id: int) -> list[str]:
    rows = await db.fetchall(
        "select node from permission_overrides where guild_id = ? and role_id = ?",
        (guild_id, role_id),
    )
    return [str(r[0]) for r in rows]


async def has_permission(db: Database, member: discord.Member, node: str) -> bool:
    if member.guild_permissions.administrator:
        return True
    role_ids = [r.id for r in member.roles]
    if not role_ids:
        return False
    placeholders = ",".join("?" * len(role_ids))
    row = await db.fetchone(
        f"select 1 from permission_overrides"
        f" where guild_id = ? and role_id in ({placeholders}) and node = ?",
        (member.guild.id, *role_ids, node),
    )
    return row is not None
