from __future__ import annotations

import time
from typing import Any

from src.data.db import Database


async def add_track(db: Database, guild_id: int, url: str, title: str, added_by: int) -> int:
    await db.execute(
        "insert into radio_playlist (guild_id, url, title, added_by, added_at)"
        " values (?, ?, ?, ?, ?)",
        (guild_id, url, title, added_by, int(time.time())),
    )
    row = await db.fetchone("select last_insert_rowid()")
    return int(row[0]) if row else 0


async def remove_track(db: Database, guild_id: int, track_id: int) -> None:
    await db.execute(
        "delete from radio_playlist where guild_id = ? and id = ?", (guild_id, track_id)
    )


async def list_tracks(db: Database, guild_id: int) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "select id, url, title from radio_playlist where guild_id = ? order by id",
        (guild_id,),
    )
    return [{"id": r[0], "url": r[1], "title": r[2]} for r in rows]


async def get_state(db: Database, guild_id: int) -> dict[str, Any]:
    row = await db.fetchone(
        "select enabled, voice_channel_id, shuffle from radio_state where guild_id = ?",
        (guild_id,),
    )
    if row is None:
        return {"enabled": False, "voice_channel_id": 0, "shuffle": True}
    return {"enabled": bool(row[0]), "voice_channel_id": row[1], "shuffle": bool(row[2])}


async def list_enabled_guilds(db: Database) -> list[int]:
    rows = await db.fetchall("select guild_id from radio_state where enabled = 1")
    return [int(r[0]) for r in rows]


async def set_state(
    db: Database, guild_id: int, *, enabled: bool, voice_channel_id: int, shuffle: bool = True
) -> None:
    await db.execute(
        "insert into radio_state (guild_id, enabled, voice_channel_id, shuffle)"
        " values (?, ?, ?, ?)"
        " on conflict (guild_id) do update set"
        " enabled = excluded.enabled, voice_channel_id = excluded.voice_channel_id,"
        " shuffle = excluded.shuffle",
        (guild_id, int(enabled), voice_channel_id, int(shuffle)),
    )
