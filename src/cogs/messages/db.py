from __future__ import annotations

from typing import Any

from src.data.db import Database

_COLUMNS = (
    "name, channel_id, message_id, content, action,"
    " action_role_id, action_emoji, container_name"
)


async def upsert_message(
    db: Database,
    guild_id: int,
    name: str,
    content: str,
    action: str,
    action_role_id: int,
    action_emoji: str,
    container_name: str | None,
    created_by: int,
) -> None:
    await db.execute(
        "insert into custom_messages"
        " (guild_id, name, content, action, action_role_id, action_emoji, container_name, created_by)"
        " values (?, ?, ?, ?, ?, ?, ?, ?)"
        " on conflict (guild_id, name) do update set"
        " content = excluded.content, action = excluded.action,"
        " action_role_id = excluded.action_role_id, action_emoji = excluded.action_emoji,"
        " container_name = excluded.container_name",
        (guild_id, name, content, action, action_role_id, action_emoji, container_name, created_by),
    )


async def set_posted(db: Database, guild_id: int, name: str, channel_id: int, message_id: int) -> None:
    await db.execute(
        "update custom_messages set channel_id = ?, message_id = ? where guild_id = ? and name = ?",
        (channel_id, message_id, guild_id, name),
    )


async def get_message(db: Database, guild_id: int, name: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        f"select {_COLUMNS} from custom_messages where guild_id = ? and name = ?",
        (guild_id, name),
    )
    if row is None:
        return None
    return _row_to_dict(row)


async def get_message_by_message_id(db: Database, message_id: int) -> dict[str, Any] | None:
    row = await db.fetchone(
        f"select {_COLUMNS} from custom_messages where message_id = ?",
        (message_id,),
    )
    if row is None:
        return None
    return _row_to_dict(row)


async def list_messages(db: Database, guild_id: int) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        f"select {_COLUMNS} from custom_messages where guild_id = ? order by name",
        (guild_id,),
    )
    return [_row_to_dict(r) for r in rows]


async def delete_message(db: Database, guild_id: int, name: str) -> None:
    await db.execute(
        "delete from custom_messages where guild_id = ? and name = ?", (guild_id, name)
    )


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "name": row[0],
        "channel_id": row[1],
        "message_id": row[2],
        "content": row[3],
        "action": row[4],
        "action_role_id": row[5],
        "action_emoji": row[6],
        "container_name": row[7],
    }
