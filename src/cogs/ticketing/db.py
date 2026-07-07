from __future__ import annotations

import time

from src.data.db import Database


async def create_panel(
    db: Database,
    guild_id: int,
    channel_id: int,
    category_id: int,
    staff_role_id: int,
    title: str,
    description: str,
) -> int:
    await db.execute(
        "insert into ticket_panels"
        " (guild_id, channel_id, category_id, staff_role_id, title, description)"
        " values (?, ?, ?, ?, ?, ?)",
        (guild_id, channel_id, category_id, staff_role_id, title, description),
    )
    row = await db.fetchone(
        "select id from ticket_panels where guild_id = ? order by id desc limit 1",
        (guild_id,),
    )
    return int(row[0]) if row else 0


async def set_panel_message(db: Database, panel_id: int, message_id: int) -> None:
    await db.execute(
        "update ticket_panels set message_id = ? where id = ?", (message_id, panel_id)
    )


async def get_panel(db: Database, panel_id: int) -> dict[str, object] | None:
    row = await db.fetchone(
        "select id, guild_id, channel_id, message_id, category_id, staff_role_id,"
        " title, description from ticket_panels where id = ?",
        (panel_id,),
    )
    if row is None:
        return None
    keys = (
        "id", "guild_id", "channel_id", "message_id", "category_id",
        "staff_role_id", "title", "description",
    )
    return dict(zip(keys, row))


async def get_open_ticket_for(db: Database, guild_id: int, opener_id: int) -> dict[str, object] | None:
    row = await db.fetchone(
        "select id, guild_id, channel_id, opener_id, panel_id, status, created_at"
        " from tickets where guild_id = ? and opener_id = ? and status = 'open'",
        (guild_id, opener_id),
    )
    if row is None:
        return None
    keys = ("id", "guild_id", "channel_id", "opener_id", "panel_id", "status", "created_at")
    return dict(zip(keys, row))


async def get_ticket_by_channel(db: Database, channel_id: int) -> dict[str, object] | None:
    row = await db.fetchone(
        "select id, guild_id, channel_id, opener_id, panel_id, status, created_at"
        " from tickets where channel_id = ?",
        (channel_id,),
    )
    if row is None:
        return None
    keys = ("id", "guild_id", "channel_id", "opener_id", "panel_id", "status", "created_at")
    return dict(zip(keys, row))


async def create_ticket(
    db: Database, guild_id: int, channel_id: int, opener_id: int, panel_id: int
) -> int:
    await db.execute(
        "insert into tickets (guild_id, channel_id, opener_id, panel_id, created_at)"
        " values (?, ?, ?, ?, ?)",
        (guild_id, channel_id, opener_id, panel_id, int(time.time())),
    )
    row = await db.fetchone(
        "select id from tickets where channel_id = ?", (channel_id,)
    )
    return int(row[0]) if row else 0


async def close_ticket(db: Database, channel_id: int) -> None:
    await db.execute(
        "update tickets set status = 'closed', closed_at = ? where channel_id = ?",
        (int(time.time()), channel_id),
    )
