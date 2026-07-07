from __future__ import annotations

from src.data.db import Database

_COLUMNS = (
    "twitch_user_id, twitch_username, guild_id, discord_channel_id, ping_role_id,"
    " custom_message, footer_message, accent_color, subscription_id, is_live"
)
_KEYS = (
    "twitch_user_id",
    "twitch_username",
    "guild_id",
    "discord_channel_id",
    "ping_role_id",
    "custom_message",
    "footer_message",
    "accent_color",
    "subscription_id",
    "is_live",
)


def _row_to_dict(row: tuple[object, ...]) -> dict[str, object]:
    return dict(zip(_KEYS, row))


async def add_streamer(
    db: Database,
    twitch_user_id: str,
    twitch_username: str,
    discord_channel_id: int,
    guild_id: int = 0,
) -> None:
    await db.execute(
        "insert into twitch_streamers (twitch_user_id, twitch_username, guild_id, discord_channel_id)"
        " values (?, ?, ?, ?)",
        (twitch_user_id, twitch_username, guild_id, discord_channel_id),
    )


async def get_streamer(db: Database, twitch_user_id: str, guild_id: int | None = None) -> dict[str, object] | None:
    query = f"select {_COLUMNS} from twitch_streamers where twitch_user_id = ?"
    params: tuple[object, ...] = (twitch_user_id,)
    if guild_id is not None:
        query += " and guild_id = ?"
        params = (twitch_user_id, guild_id)
    row = await db.fetchone(query, params)
    return _row_to_dict(row) if row else None


async def get_streamer_by_username(
    db: Database, username: str, guild_id: int | None = None
) -> dict[str, object] | None:
    query = (
        f"select {_COLUMNS} from twitch_streamers where twitch_username = ? collate nocase"
    )
    params: tuple[object, ...] = (username,)
    if guild_id is not None:
        query += " and guild_id = ?"
        params = (username, guild_id)
    row = await db.fetchone(query, params)
    return _row_to_dict(row) if row else None


async def get_all_streamers(db: Database) -> list[dict[str, object]]:
    rows = await db.fetchall(f"select {_COLUMNS} from twitch_streamers")
    return [_row_to_dict(r) for r in rows]


async def remove_streamer(db: Database, twitch_user_id: str, guild_id: int | None = None) -> None:
    query = "delete from twitch_streamers where twitch_user_id = ?"
    params: tuple[object, ...] = (twitch_user_id,)
    if guild_id is not None:
        query += " and guild_id = ?"
        params = (twitch_user_id, guild_id)
    await db.execute(query, params)


async def update_streamer(
    db: Database, twitch_user_id: str, guild_id: int | None = None, **fields: object
) -> None:
    if not fields:
        return
    query = f"update twitch_streamers set {', '.join(f'{k} = ?' for k in fields)} where twitch_user_id = ?"
    params: tuple[object, ...] = (*fields.values(), twitch_user_id)
    if guild_id is not None:
        query += " and guild_id = ?"
        params = (*fields.values(), twitch_user_id, guild_id)
    await db.execute(query, params)
