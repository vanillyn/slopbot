from __future__ import annotations

import asyncio
from pathlib import Path

from src.data.config import GuildConfig
from src.data.db import Database


def test_database_connect_handles_twitch_schema_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "bot.db"
    db = Database(str(db_path))

    asyncio.run(db.connect())
    try:
        assert db._conn is not None
    finally:
        asyncio.run(db.close())


def test_guild_config_roundtrips_through_the_unified_settings_table(tmp_path: Path) -> None:
    db_path = tmp_path / "bot.db"
    db = Database(str(db_path))

    async def scenario() -> None:
        await db.connect()
        try:
            cfg = await GuildConfig.load(db, 42)
            assert cfg.moderation.require_confirm is True

            cfg.moderation.require_confirm = False
            cfg.dashboard.ticket_channel = 999
            await cfg.save(db)

            reloaded = await GuildConfig.load(db, 42)
            assert reloaded.moderation.require_confirm is False
            assert reloaded.dashboard.ticket_channel == 999
        finally:
            await db.close()

    asyncio.run(scenario())
