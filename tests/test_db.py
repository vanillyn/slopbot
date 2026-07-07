from __future__ import annotations

import asyncio
from pathlib import Path

from src.data.db import Database


def test_database_connect_handles_twitch_schema_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "bot.db"
    db = Database(str(db_path))

    asyncio.run(db.connect())
    try:
        assert db._conn is not None
    finally:
        asyncio.run(db.close())
