from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from src.cogs.messages.db import get_message, upsert_message
from src.data.button_actions import get_handler
from src.data.button_containers import (
    add_item,
    find_item_by_id,
    get_container,
    remove_item,
)
from src.data.db import Database


def test_add_item_creates_container_and_is_findable_by_id(tmp_path: Path) -> None:
    db_path = tmp_path / "bot.db"
    db = Database(str(db_path))

    async def scenario() -> None:
        await db.connect()
        try:
            item_id = await add_item(
                db,
                guild_id=1,
                container_name="verify",
                created_by=42,
                label="Verify",
                style="success",
                action="give_role",
                data={"role_id": 555},
            )

            container = await get_container(db, 1, "verify")
            assert container is not None
            assert len(container["items"]) == 1
            assert container["items"][0]["id"] == item_id

            found = await find_item_by_id(db, 1, item_id)
            assert found is not None
            assert found["action"] == "give_role"
            assert found["data"] == {"role_id": 555}

            # handler must be registered for whatever action a saved item uses
            assert get_handler(found["action"]) is not None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_remove_item_only_removes_the_targeted_button(tmp_path: Path) -> None:
    db_path = tmp_path / "bot.db"
    db = Database(str(db_path))

    async def scenario() -> None:
        await db.connect()
        try:
            id_a = await add_item(
                db, guild_id=1, container_name="verify", created_by=42,
                label="A", style="success", action="give_role", data={"role_id": 1},
            )
            id_b = await add_item(
                db, guild_id=1, container_name="verify", created_by=42,
                label="B", style="secondary", action="grant_role", data={"role_id": 2},
            )

            removed = await remove_item(db, 1, "verify", id_a)
            assert removed is True

            container = await get_container(db, 1, "verify")
            assert container is not None
            ids = [i["id"] for i in container["items"]]
            assert id_a not in ids
            assert id_b in ids

            # removing something already gone reports False rather than raising
            removed_again = await remove_item(db, 1, "verify", id_a)
            assert removed_again is False
        finally:
            await db.close()

    asyncio.run(scenario())


def test_find_item_by_id_is_scoped_per_guild(tmp_path: Path) -> None:
    db_path = tmp_path / "bot.db"
    db = Database(str(db_path))

    async def scenario() -> None:
        await db.connect()
        try:
            item_id = await add_item(
                db, guild_id=1, container_name="verify", created_by=42,
                label="Verify", style="success", action="give_role", data={"role_id": 555},
            )
            # same item id can't leak across guilds
            found_wrong_guild = await find_item_by_id(db, 2, item_id)
            assert found_wrong_guild is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_message_can_reference_a_button_container(tmp_path: Path) -> None:
    db_path = tmp_path / "bot.db"
    db = Database(str(db_path))

    async def scenario() -> None:
        await db.connect()
        try:
            await add_item(
                db, guild_id=1, container_name="verify", created_by=42,
                label="Verify", style="success", action="give_role", data={"role_id": 555},
            )
            await upsert_message(
                db, guild_id=1, name="verify", content="click to verify",
                action="none", action_role_id=0, action_emoji="",
                container_name="verify", created_by=42,
            )

            msg = await get_message(db, 1, "verify")
            assert msg is not None
            assert msg["container_name"] == "verify"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_connect_migrates_pre_container_name_custom_messages_table(tmp_path: Path) -> None:
    db_path = tmp_path / "bot.db"

    async def prepare_old_schema() -> None:
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute(
            """
            create table custom_messages (
                guild_id integer not null,
                name text not null,
                channel_id integer not null default 0,
                message_id integer not null default 0,
                content text not null default '',
                action text not null default 'none',
                action_role_id integer not null default 0,
                action_emoji text not null default '',
                created_by integer not null,
                primary key (guild_id, name)
            )
            """
        )
        await conn.execute(
            "insert into custom_messages (guild_id, name, action, action_role_id, created_by)"
            " values (1, 'oldmsg', 'button_role', 123, 42)"
        )
        await conn.commit()
        await conn.close()

    async def scenario() -> None:
        await prepare_old_schema()
        db = Database(str(db_path))
        await db.connect()  # must not raise, and must add container_name in place
        try:
            msg = await get_message(db, 1, "oldmsg")
            assert msg is not None
            assert msg["container_name"] is None
            assert msg["action"] == "button_role"  # old rows keep their stale action value as-is
        finally:
            await db.close()

    asyncio.run(scenario())
